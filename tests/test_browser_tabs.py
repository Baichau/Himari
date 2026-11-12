from unittest.mock import Mock

import pytest

from himari.browser import tabs


class FakePage:
    def __init__(self, title, url):
        self._title = title
        self.url = url
        self.closed = False
        self.focused = 0

    def title(self):
        return self._title

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True

    def bring_to_front(self):
        self.focused += 1


class FakeManager:
    def __init__(self, pages):
        self._pages = list(pages)
        self.page = self._pages[0] if self._pages else None

    def pages(self):
        return [page for page in self._pages if not page.closed]

    def new_page(self):
        page = FakePage("New Tab", "about:blank")
        self._pages.append(page)
        return page

    def open(self):
        if self.page is not None and not self.page.closed:
            return self.page
        return self.new_page()


def _manager(*titles):
    pages = [FakePage(title, f"https://example.com/{index}") for index, title in enumerate(titles, 1)]
    return FakeManager(pages), pages


def test_search_url_encodes_and_rejects_unknown_engine():
    assert tabs.search_url("christmas & lights") == "https://duckduckgo.com/?q=christmas+%26+lights"
    assert "google.com" in tabs.search_url("cats", "google")
    with pytest.raises(tabs.BrowserError):
        tabs.search_url(" ")
    with pytest.raises(tabs.BrowserError, match="Unsupported search engine"):
        tabs.search_url("cats", "altavista")


def test_manage_tabs_lists_every_open_tab():
    manager, _ = _manager("Pinterest", "Christmas images")

    result = tabs.manage_tabs(manager, "list")

    assert result["ok"] is True
    assert "1. Pinterest — https://example.com/1" in result["message"]
    assert "2. Christmas images — https://example.com/2" in result["message"]


def test_manage_tabs_focuses_requested_tab():
    manager, pages = _manager("One", "Two")

    result = tabs.manage_tabs(manager, "focus", 2)

    assert manager.page is pages[1]
    assert pages[1].focused == 1
    assert "Focused tab 2 of 2" in result["message"]


def test_manage_tabs_closes_one_tab_and_keeps_the_rest():
    manager, pages = _manager("One", "Two", "Three")

    result = tabs.manage_tabs(manager, "close", 2)

    assert pages[1].closed is True
    assert "2 tab(s) remain" in result["message"]
    assert [page._title for page in manager.pages()] == ["One", "Three"]


def test_manage_tabs_close_others_keeps_requested_tab():
    manager, pages = _manager("Pinterest", "Search", "Shop")

    result = tabs.manage_tabs(manager, "close_others", 1)

    assert [page._title for page in manager.pages()] == ["Pinterest"]
    assert manager.page is pages[0]
    assert "Closed 2 other tab(s)" in result["message"]


def test_manage_tabs_close_all_leaves_no_page():
    manager, pages = _manager("One", "Two")

    result = tabs.manage_tabs(manager, "close_all")

    assert all(page.closed for page in pages)
    assert manager.page is None
    assert "Closed all 2 tab(s)" in result["message"]


def test_manage_tabs_rejects_bad_index_and_action():
    manager, _ = _manager("One")

    with pytest.raises(tabs.BrowserError, match="does not exist"):
        tabs.manage_tabs(manager, "focus", 4)
    with pytest.raises(tabs.BrowserError, match="whole number"):
        tabs.manage_tabs(manager, "focus", "first")
    with pytest.raises(tabs.BrowserError, match="Unsupported tab action"):
        tabs.manage_tabs(manager, "explode")


def test_open_page_navigates_new_tab_and_reports_it(monkeypatch):
    manager, _ = _manager("Existing")

    def fake_navigate(page, url, timeout_ms=None):
        page.url = url
        page._title = "Pinterest"
        return {"ok": True, "url": url, "title": "Pinterest"}

    monkeypatch.setattr(tabs, "navigate", fake_navigate)

    result = tabs.open_page(manager, "https://pinterest.com/", new_tab=True)

    assert result["ok"] is True
    assert result["title"] == "Pinterest"
    assert result["index"] == 2
    assert result["total"] == 2
    assert manager.page.url == "https://pinterest.com/"


def test_open_page_closes_blank_tab_when_navigation_fails(monkeypatch):
    manager, pages = _manager("Existing")
    monkeypatch.setattr(tabs, "navigate", lambda page, url, timeout_ms=None: {
        "ok": False, "error": "ERR_NAME_NOT_RESOLVED",
    })

    result = tabs.open_page(manager, "https://bad.example/", new_tab=True)

    assert result == {"ok": False, "error": "ERR_NAME_NOT_RESOLVED"}
    assert len(manager.pages()) == 1
    assert manager.pages()[0] is pages[0]


def test_read_active_returns_current_page(monkeypatch):
    manager, pages = _manager("One", "Two")
    manager.page = pages[1]
    monkeypatch.setattr(tabs, "read_page", lambda page: {
        "title": page.title(), "url": page.url, "text": "visible text",
    })

    result = tabs.read_active(manager)

    assert result == {
        "ok": True, "title": "Two", "url": "https://example.com/2", "text": "visible text",
    }
