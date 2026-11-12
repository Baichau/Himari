"""A long-lived browser window owned by Himari.

Playwright's sync API is bound to the thread that created it, while chat tools
run on a worker thread that changes between requests. This module keeps one
browser and one Playwright instance on a dedicated thread and forwards calls to
it, so tabs survive between messages and can be listed, focused, and closed.

The session is separate from the user's everyday Chrome window: it starts a
new Chrome window with an isolated profile, so saved logins are not available.
"""

import atexit
import logging
import queue
import threading

from .browser_manager import BrowserError, BrowserManager, browser_allowed

log = logging.getLogger("himari.browser.session")

CALL_TIMEOUT_SECONDS = 60
SHUTDOWN_TIMEOUT_SECONDS = 8


class _Call:
    __slots__ = ("func", "args", "kwargs", "done", "result", "error")

    def __init__(self, func, args, kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.done = threading.Event()
        self.result = None
        self.error = None


class BrowserSession:
    def __init__(self, headless=False):
        self.headless = headless
        self._queue = queue.Queue()
        self._thread = None
        self._lock = threading.Lock()
        self._stopped = False

    def _start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopped = False
            self._thread = threading.Thread(
                target=self._run, name="himari-browser", daemon=True
            )
            self._thread.start()

    def _run(self):
        manager = BrowserManager(headless=self.headless, permission_check=lambda: True)
        try:
            while True:
                call = self._queue.get()
                if call is None:
                    return
                try:
                    call.result = call.func(manager, *call.args, **call.kwargs)
                except Exception as exc:
                    call.error = exc
                finally:
                    call.done.set()
        finally:
            manager.close()

    def call(self, func, *args, timeout=CALL_TIMEOUT_SECONDS, **kwargs):
        if not browser_allowed():
            raise PermissionError(
                "Permission denied: browser automation is disabled in Settings."
            )
        if self._stopped:
            raise BrowserError(
                "The Himari browser was closed. Open a page again to restart it."
            )
        self._start()
        pending = _Call(func, args, kwargs)
        self._queue.put(pending)
        if not pending.done.wait(timeout):
            raise BrowserError("The Himari browser did not respond in time.")
        if pending.error is not None:
            raise pending.error
        return pending.result

    def shutdown(self, timeout=SHUTDOWN_TIMEOUT_SECONDS):
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stopped = True
        if thread is None or not thread.is_alive():
            return
        self._queue.put(None)
        thread.join(timeout)


session = BrowserSession()
atexit.register(session.shutdown)
