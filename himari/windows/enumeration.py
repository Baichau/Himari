"""Windows-native window enumeration and graceful close requests."""

import ctypes
import logging
import os
from dataclasses import dataclass

log = logging.getLogger("himari.windows")

WM_CLOSE = 0x0010


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process_name: str


def _get_user32():
    return ctypes.windll.user32


def _process_name(pid):
    if not pid:
        return ""
    try:
        import psutil

        return psutil.Process(pid).name() or ""
    except Exception:
        return ""


def _enum_raw_windows():
    """Return (hwnd, title, pid) for visible windows with a title."""
    if os.name != "nt":
        return []
    user32 = _get_user32()
    results = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            title = buffer.value.strip()
            if title:
                results.append((int(hwnd), title, int(pid.value)))
        except OSError:
            pass
        return True

    user32.EnumWindows(callback_type(_callback), 0)
    return results


def list_windows():
    """Enumerate open windows with title, owning process name, and handle."""
    return [
        WindowInfo(hwnd=hwnd, title=title, pid=pid, process_name=_process_name(pid))
        for hwnd, title, pid in _enum_raw_windows()
    ]


def request_window_close(hwnd):
    """Post WM_CLOSE so the application can save and shut down normally.

    This never force-terminates a process.
    """
    if os.name != "nt":
        raise RuntimeError("Window management is only available on Windows.")
    user32 = _get_user32()
    if not user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
        raise OSError(f"Could not post a close request to window {hwnd}.")
    return True