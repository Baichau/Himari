from unittest.mock import Mock

import pytest

from himari import tools
from himari.security import policies

RESULTS = [
    {"title": "Christmas decoration ideas", "url": "https://decor.example/list", "snippet": ""},
    {"title": "Free Christmas images", "url": "https://images.example/free", "snippet": ""},
]


def _allow(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)


def test_new_browser_tools_are_registered():
    names = {entry["name"] for entry in tools.TOOLS}
    assert {
        "open_first_result",
        "browser_open",
        "browser_search",
        "browser_open_result",
        "browser_tabs",
        "browser_read",
        "browser_close",
        "find_video",
    } <= names
    for name in names & {
        "open_first_result",
        "browser_open",
        "browser_search",
        "browser_open_result",
        "browser_tabs",
        "browser_read",
        "browser_close",
        "find_video",
    }:
        assert name in policies.TOOL_RISKS
        assert name in policies.TOOL_PERMISSIONS


def test_browser_tool_descriptions_state_their_limits():
    by_name = {entry["name"]: entry for entry in tools.TOOLS}
    tabs_text = by_name["browser_tabs"]["spec"]["function"]["description"]
    play_text = by_name["play_music"]["spec"]["function"]["description"]
    assert "never touches the user's everyday Chrome tabs" in tabs_text
    assert "Only report success when the result says playback was verified" in play_text


def test_browser_open_verifies_the_real_page(monkeypatch):
    seen = {}

    def fake_run(func, *args, **kwargs):
        seen["func"] = func
        seen["args"] = args
        return {"ok": True, "index": 2, "total": 3, "title": "Pinterest", "url": "https://www.pinterest.com/"}

    _allow(monkeypatch)
    monkeypatch.setattr(tools, "_run_browser", fake_run)

    result = tools.browser_open("pinterest.com")

    assert 'Opened "Pinterest"' in result
    assert "tab 2 of 3" in result
    assert "separate Chrome window" in result
    assert seen["args"] == ("https://pinterest.com", True)


def test_browser_open_rejects_invalid_urls(monkeypatch):
    _allow(monkeypatch)
    assert tools.browser_open("ftp://example.com").startswith("Invalid URL")
    assert tools.browser_open("  ").startswith("Provide a website URL")


def test_browser_open_reports_permission_denial(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: False)

    assert "disabled in Settings" in tools.browser_open("https://example.com")


def test_browser_search_returns_real_result_list(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(tools, "_fetch_web_results", lambda query: (RESULTS, None))
    monkeypatch.setattr(
        tools, "_run_browser",
        lambda func, *args, **kwargs: {
            "ok": True, "index": 1, "total": 1,
            "title": "DuckDuckGo", "url": "https://duckduckgo.com/?q=christmas+images",
        },
    )

    result = tools.browser_search("christmas images")

    assert "1. Christmas decoration ideas" in result
    assert "https://images.example/free" in result
    assert "browser_open_result" in result


def test_browser_search_stays_honest_when_results_cannot_be_read(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(tools, "_fetch_web_results", lambda query: ([], "DuckDuckGo returned no usable results."))
    monkeypatch.setattr(
        tools, "_run_browser",
        lambda func, *args, **kwargs: {
            "ok": True, "index": 1, "total": 1,
            "title": "DuckDuckGo", "url": "https://duckduckgo.com/",
        },
    )

    result = tools.browser_search("christmas images")

    assert "could not read the result list" in result
    assert "1. Christmas" not in result


def test_browser_open_result_opens_requested_number(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(tools, "_fetch_web_results", lambda query: (RESULTS, None))
    seen = {}

    def fake_run(func, url, new_tab):
        seen["url"] = url
        seen["new_tab"] = new_tab
        return {
            "ok": True, "index": 2, "total": 2,
            "title": "Free Christmas images", "url": "https://images.example/free",
        }

    monkeypatch.setattr(tools, "_run_browser", fake_run)

    result = tools.browser_open_result("christmas images", 2)

    assert seen == {"url": "https://images.example/free", "new_tab": False}
    assert "result 2 of 2" in result
    assert "Free Christmas images" in result
    assert "current tab" in result
    assert "replaced" in result


def test_browser_open_result_opens_a_new_tab_only_when_asked(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(tools, "_fetch_web_results", lambda query: (RESULTS, None))
    seen = {}

    def fake_run(func, url, new_tab):
        seen["new_tab"] = new_tab
        return {
            "ok": True, "index": 3, "total": 3,
            "title": "Free Christmas images", "url": "https://images.example/free",
        }

    monkeypatch.setattr(tools, "_run_browser", fake_run)

    result = tools.browser_open_result("christmas images", 2, new_tab=True)

    assert seen["new_tab"] is True
    assert "new tab" in result
    assert "replaced" not in result


def test_browser_open_result_validates_the_number(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(tools, "_fetch_web_results", lambda query: (RESULTS, None))

    assert "does not exist" in tools.browser_open_result("christmas images", 7)
    assert "whole number" in tools.browser_open_result("christmas images", "first")


def test_open_first_result_opens_in_the_user_browser(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(tools, "_fetch_web_results", lambda query: (RESULTS, None))
    opened = Mock(return_value="Opened https://images.example/free")
    monkeypatch.setattr(tools, "open_url", opened)

    result = tools.open_first_result("christmas images", 2)

    opened.assert_called_once_with("https://images.example/free")
    assert 'result 2 of 2: "Free Christmas images"' in result


def test_open_first_result_reports_search_failure(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(tools, "_fetch_web_results", lambda query: ([], "internet may be unavailable"))
    monkeypatch.setattr(tools, "open_url", Mock(side_effect=AssertionError("must not open")))

    assert "internet may be unavailable" in tools.open_first_result("christmas images")


def test_open_first_result_requires_website_permission(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: name != "allow_open_url")

    assert "disabled in Settings" in tools.open_first_result("christmas images")


def test_browser_tabs_maps_actions_and_rejects_unknown(monkeypatch):
    _allow(monkeypatch)
    seen = {}

    def fake_run(func, action, index):
        seen["action"] = action
        seen["index"] = index
        return {"ok": True, "message": "Closed 2 other tab(s). Kept tab 1: Pinterest."}

    monkeypatch.setattr(tools, "_run_browser", fake_run)

    assert tools.browser_tabs("close_others", 1).startswith("Closed 2 other tab(s)")
    assert seen == {"action": "close_others", "index": 1}
    assert "Unsupported tab action" in tools.browser_tabs("explode")


def test_browser_read_and_close_report_real_outcomes(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(
        tools, "_run_browser",
        lambda func, *args, **kwargs: {
            "ok": True, "title": "Pinterest", "url": "https://pinterest.com/", "text": "pins",
        }
        if func.__name__ == "read_active"
        else {"ok": True, "message": "Closed Himari's browser window."},
    )

    assert "Pinterest" in tools.browser_read()
    assert "pins" in tools.browser_read()
    assert tools.browser_close() == "Closed Himari's browser window."
