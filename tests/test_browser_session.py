import threading

import pytest

from himari.browser import session as session_module
from himari.browser.browser_manager import BrowserError
from himari.browser.session import BrowserSession


def test_session_refuses_when_browser_automation_is_off(monkeypatch):
    monkeypatch.setattr(session_module, "browser_allowed", lambda: False)
    browser = BrowserSession()

    with pytest.raises(PermissionError, match="disabled in Settings"):
        browser.call(lambda manager: "never")


def test_session_runs_calls_on_its_own_thread(monkeypatch):
    monkeypatch.setattr(session_module, "browser_allowed", lambda: True)
    browser = BrowserSession()
    try:
        name = browser.call(lambda manager: threading.current_thread().name)
        assert name == "himari-browser"
        assert browser.call(lambda manager, value: value * 2, 21) == 42
    finally:
        browser.shutdown()


def test_session_propagates_call_errors(monkeypatch):
    monkeypatch.setattr(session_module, "browser_allowed", lambda: True)
    browser = BrowserSession()

    def explode(manager):
        raise BrowserError("navigation failed")

    try:
        with pytest.raises(BrowserError, match="navigation failed"):
            browser.call(explode)
    finally:
        browser.shutdown()


def test_session_reports_use_after_shutdown(monkeypatch):
    monkeypatch.setattr(session_module, "browser_allowed", lambda: True)
    browser = BrowserSession()
    browser.shutdown()

    with pytest.raises(BrowserError, match="closed"):
        browser.call(lambda manager: "never")
