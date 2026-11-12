import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from himari.browser import (
    AmbiguousElementError,
    BrowserCancelledError,
    BrowserError,
    BrowserManager,
    CancellationToken,
    ElementNotFoundError,
    click,
    detect_browsers,
    fill,
    list_elements,
    locate,
    navigate,
    read_page,
    screenshot,
    submit,
    validate_url,
)
from himari.browser import browser_manager, interactions, navigation, page_reader
from himari.windows import AppInfo


def _fake_playwright(monkeypatch, launch=None):
    page = Mock(name="page")
    context = Mock(name="context")
    context.new_page.return_value = page
    browser = Mock(name="browser")
    browser.new_context.return_value = context
    launcher = Mock(name="launcher")
    launcher.launch = launch or Mock(return_value=browser)
    pw = SimpleNamespace(chromium=launcher, firefox=launcher)
    starter = Mock()
    starter.start.return_value = pw
    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=lambda: starter),
    )
    return SimpleNamespace(page=page, context=context, browser=browser, launcher=launcher, pw=pw)


def test_detect_browsers_uses_windows_discovery(monkeypatch):
    monkeypatch.setattr(
        "himari.windows.installed_apps",
        lambda: [
            AppInfo("Google Chrome", "chrome.lnk", "start_menu"),
            AppInfo("Microsoft Edge", "edge.lnk", "start_menu"),
            AppInfo("Spotify", "spotify.lnk", "start_menu"),
        ],
    )

    assert detect_browsers() == ["chrome", "edge"]


def test_open_requires_permission(monkeypatch):
    manager = BrowserManager(permission_check=lambda: False)

    with pytest.raises(PermissionError):
        manager.open("chrome")


def test_open_rejects_unsupported_browsers():
    manager = BrowserManager(permission_check=lambda: True)

    with pytest.raises(BrowserError, match="Unsupported browser"):
        manager.open("safari")


def test_open_launches_installed_channel_and_close_releases(monkeypatch):
    fake = _fake_playwright(monkeypatch)
    manager = BrowserManager(permission_check=lambda: True)

    page = manager.open("chrome")

    assert page is fake.page
    fake.launcher.launch.assert_called_once_with(channel="chrome", headless=True)
    fake.page.set_default_navigation_timeout.assert_called_once_with(manager.timeout_ms)
    manager.close()
    fake.page.close.assert_called_once()
    fake.context.close.assert_called_once()
    fake.browser.close.assert_called_once()
    manager.close()  # idempotent


def test_open_reports_unavailable_browser(monkeypatch):
    fake = _fake_playwright(monkeypatch, launch=Mock(side_effect=RuntimeError("executable not found")))
    manager = BrowserManager(permission_check=lambda: True)

    with pytest.raises(BrowserError, match="executable not found"):
        manager.open("chrome")
    assert manager.page is None


def test_cancellation_blocks_actions(monkeypatch):
    token = CancellationToken()
    token.cancel()
    manager = BrowserManager(permission_check=lambda: True, token=token)

    with pytest.raises(BrowserCancelledError):
        manager.open("chrome")
    with pytest.raises(BrowserCancelledError):
        navigate(Mock(), "https://example.com", token=token)
    with pytest.raises(BrowserCancelledError):
        click(Mock(), Mock(), {}, token=token)


def test_validate_url_rules():
    assert validate_url("example.com") == "https://example.com"
    assert validate_url("http://example.com") == "http://example.com"
    for bad in ("", "   ", "ftp://example.com", "javascript:alert(1)", "https://exa mple.com", "https://example.com\r\n"):
        with pytest.raises(BrowserError):
            validate_url(bad)


def test_navigate_returns_structured_result():
    page = Mock()
    page.url = "https://example.com/"
    page.title.return_value = "Example"

    result = navigate(page, "example.com", timeout_ms=1234)

    assert result == {"ok": True, "url": "https://example.com/", "title": "Example"}
    page.goto.assert_called_once_with("https://example.com", wait_until="domcontentloaded", timeout=1234)


def test_navigate_reports_errors():
    page = Mock()
    page.goto.side_effect = RuntimeError("net::ERR_NAME_NOT_RESOLVED")

    result = navigate(page, "https://invalid.example")

    assert result["ok"] is False
    assert "ERR_NAME_NOT_RESOLVED" in result["error"]


def test_read_page_bounds_visible_text():
    page = Mock()
    page.title.return_value = "Title"
    page.url = "https://example.com"
    page.inner_text.return_value = "  line one  \n\n line two \n" + "x" * 9000

    result = read_page(page, max_chars=100)

    assert result["title"] == "Title"
    assert result["text"].startswith("line one\nline two")
    assert len(result["text"]) == 100


def test_list_elements_extracts_metadata(monkeypatch):
    handle = Mock()
    handle.evaluate.return_value = {
        "tag": "button", "type": "", "id": "go", "name": "", "text": "Go", "label": "", "href": "",
    }
    page = Mock()
    page.query_selector_all.return_value = [handle]

    elements = list_elements(page)

    assert elements[0]["tag"] == "button"
    assert elements[0]["text"] == "Go"
    assert elements[0]["index"] == 0
    handle.evaluate.assert_called_once()


def _element(index, text, **extra):
    base = {"index": index, "tag": "button", "type": "", "id": "", "name": "", "text": text, "label": "", "href": ""}
    base.update(extra)
    return base


def test_locate_rejects_ambiguous_and_missing(monkeypatch):
    page = Mock()
    monkeypatch.setattr(page_reader, "list_elements", lambda p: [
        _element(0, "Send"), _element(1, "Send"),
    ])
    with pytest.raises(AmbiguousElementError):
        locate(page, "Send")

    monkeypatch.setattr(page_reader, "list_elements", lambda p: [_element(0, "Other")])
    with pytest.raises(ElementNotFoundError):
        locate(page, "Send")
    with pytest.raises(ElementNotFoundError):
        locate(page, "  ")


def test_locate_returns_unique_locator(monkeypatch):
    page = Mock()
    element = _element(3, "Search", id="search-box")
    monkeypatch.setattr(page_reader, "list_elements", lambda p: [element])

    locator, metadata = locate(page, "search-box")

    assert metadata is element
    page.locator.assert_called_once_with(page_reader.ELEMENT_SELECTOR)
    page.locator.return_value.nth.assert_called_once_with(3)


def test_click_refuses_payments_and_captcha():
    locator = Mock()
    with pytest.raises(BrowserError, match="payments"):
        click(Mock(), locator, {"text": "Buy now"})
    with pytest.raises(BrowserError, match="CAPTCHA"):
        click(Mock(), locator, {"text": "", "id": "recaptcha-anchor"})
    locator.click.assert_not_called()


def test_submit_like_clicks_require_confirmation():
    locator = Mock()
    metadata = {"text": "Send message", "type": ""}

    with pytest.raises(PermissionError):
        click(Mock(), locator, metadata)
    with pytest.raises(PermissionError):
        click(Mock(), locator, metadata, confirm=lambda action, meta: False)
    locator.click.assert_not_called()

    result = click(Mock(), locator, metadata, confirm=lambda action, meta: True)

    assert result["ok"] is True
    locator.click.assert_called_once()


def test_plain_click_uses_explicit_timeout():
    locator = Mock()

    result = click(Mock(), locator, {"text": "Open menu"}, timeout_ms=999)

    assert result["ok"] is True
    locator.click.assert_called_once_with(timeout=999)


def test_fill_never_touches_passwords_or_submits():
    locator = Mock()
    with pytest.raises(BrowserError, match="Password"):
        fill(Mock(), locator, {"type": "password"}, "secret")

    result = fill(Mock(), locator, {"type": "text", "id": "q"}, "hello")

    assert result["ok"] is True
    locator.fill.assert_called_once_with("hello", timeout=5000)
    locator.press.assert_not_called()
    locator.click.assert_not_called()


def test_submit_requires_confirmation_and_still_blocks_payments():
    locator = Mock()
    with pytest.raises(PermissionError):
        submit(Mock(), locator, {"text": "Submit form"}, confirm=None)
    with pytest.raises(BrowserError, match="payments"):
        submit(Mock(), locator, {"text": "Pay now"}, confirm=lambda action, meta: True)

    result = submit(Mock(), locator, {"text": "Submit form"}, confirm=lambda action, meta: True)

    assert result["ok"] is True
    locator.click.assert_called_once()


def test_screenshot_stays_in_memory():
    page = Mock()
    page.screenshot.return_value = b"png-bytes"

    result = screenshot(page)

    assert result == {"ok": True, "action": "screenshot", "format": "png", "bytes": b"png-bytes"}
    page.screenshot.assert_called_once_with(type="png", full_page=False, timeout=5000)