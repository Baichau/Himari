"""Shared bounded tool invocation used by chat and the agent.

A handler runs on a daemon worker thread so a wedged tool cannot freeze the
caller forever or keep the process alive at exit. Timeouts are honest: the
tool is not retried and the message says it may still be running.
"""

import threading

DEFAULT_TOOL_TIMEOUT_SECONDS = 30


class ToolTimeoutError(RuntimeError):
    pass


def timeout_for(entry, default=DEFAULT_TOOL_TIMEOUT_SECONDS):
    configured = entry.get("timeout_seconds") if isinstance(entry, dict) else None
    if isinstance(configured, (int, float)) and configured > 0:
        return float(configured)
    return float(default)


def call(handler, arguments, timeout=None, label=None):
    timeout = float(timeout if timeout is not None else DEFAULT_TOOL_TIMEOUT_SECONDS)
    label = label or getattr(handler, "__name__", "tool")
    outcome = {}
    done = threading.Event()

    def work():
        try:
            outcome["value"] = handler(**(arguments or {}))
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=work, name=f"tool:{label}", daemon=True)
    worker.start()
    if not done.wait(timeout):
        raise ToolTimeoutError(
            f"'{label}' did not finish within {timeout:g} seconds and will "
            "not be retried automatically. The action may still be running "
            "in the background."
        )
    error = outcome.get("error")
    if error is not None:
        raise error
    return outcome.get("value")
