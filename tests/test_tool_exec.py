import threading
import time

import pytest

from himari.tool_exec import ToolTimeoutError, call


def test_call_returns_the_handler_result():
    assert call(lambda value: value * 2, {"value": 3}, timeout=1) == 6


def test_call_propagates_handler_errors():
    def boom():
        raise ValueError("no")

    with pytest.raises(ValueError, match="no"):
        call(boom, {}, timeout=1)


def test_call_times_out_without_blocking_the_caller():
    gate = threading.Event()
    finished = threading.Event()

    def slow():
        gate.wait(5)
        finished.set()
        return "late"

    started = time.monotonic()
    with pytest.raises(ToolTimeoutError, match="will not be retried"):
        call(slow, {}, timeout=0.05)

    assert time.monotonic() - started < 2
    gate.set()
    assert finished.wait(2)


def test_timed_out_tool_runs_on_a_daemon_worker():
    gate = threading.Event()

    def stuck():
        gate.wait(5)

    with pytest.raises(ToolTimeoutError):
        call(stuck, {}, timeout=0.05)

    worker = next(
        thread for thread in threading.enumerate() if thread.name == "tool:stuck"
    )
    assert worker.daemon is True
    gate.set()
