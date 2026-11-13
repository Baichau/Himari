import logging
import sys
import threading
from types import SimpleNamespace

import pytest

from himari import crash


@pytest.fixture()
def restore_hooks():
    original_excepthook = sys.excepthook
    original_thread_hook = threading.excepthook
    yield
    sys.excepthook = original_excepthook
    threading.excepthook = original_thread_hook


def test_unhandled_exceptions_are_logged_and_reported(monkeypatch, caplog, restore_hooks):
    reported = []
    monkeypatch.setattr(crash, "_report", lambda app, error: reported.append(error))
    caplog.set_level(logging.CRITICAL)

    crash.install(None)
    sys.excepthook(RuntimeError, RuntimeError("boom"), None)

    assert [str(error) for error in reported] == ["boom"]
    assert any("Unhandled exception" in record.getMessage() for record in caplog.records)


def test_keyboard_interrupt_is_not_reported(monkeypatch, restore_hooks):
    reported = []
    monkeypatch.setattr(crash, "_report", lambda app, error: reported.append(error))

    crash.install(None)
    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

    assert reported == []


def test_thread_exceptions_are_logged_without_touching_the_ui(caplog, restore_hooks):
    caplog.set_level(logging.CRITICAL)

    crash.install(None)
    threading.excepthook(SimpleNamespace(
        thread=SimpleNamespace(name="worker"),
        exc_type=ValueError,
        exc_value=ValueError("bad worker"),
        exc_traceback=None,
    ))

    assert any(
        "Unhandled exception in thread worker" in record.getMessage()
        for record in caplog.records
    )


def test_qt_messages_map_to_log_levels(caplog):
    from PySide6.QtCore import QtMsgType

    caplog.set_level(logging.DEBUG)
    crash._qt_handler(QtMsgType.QtWarningMsg, "careful", QtMsgType)

    record = caplog.records[-1]
    assert record.levelno == logging.WARNING
    assert "careful" in record.getMessage()
