"""Practical browser test against a local HTTP server.

Skipped when Playwright or a supported installed browser is unavailable.
Uses the system Chrome/Edge channel; no browser is downloaded.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from himari.browser import BrowserManager, detect_browsers, fill, locate, navigate, read_page

PAGE = b"""<!doctype html>
<html><head><title>Himari Test Page</title></head>
<body>
<h1>Hello from the local test page</h1>
<input id="query" type="text" placeholder="Search query">
<button id="go" onclick="document.getElementById('out').innerText='clicked'">Go</button>
<div id="out"></div>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        pass


@pytest.fixture()
def local_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()
    server.server_close()


def test_local_page_navigation_reading_and_interaction(local_url):
    browsers = detect_browsers()
    if not browsers:
        pytest.skip("no supported installed browser found")
    browser = "chrome" if "chrome" in browsers else browsers[0]

    with BrowserManager(headless=True, permission_check=lambda: True) as manager:
        try:
            page = manager.open(browser)
        except Exception as exc:
            pytest.skip(f"installed browser could not be automated: {exc}")

        result = navigate(page, local_url)
        assert result["ok"] is True
        assert result["title"] == "Himari Test Page"

        content = read_page(page)
        assert "Hello from the local test page" in content["text"]

        locator, metadata = locate(page, "query")
        assert fill(page, locator, metadata, "himari")["ok"] is True

        locator, metadata = locate(page, "Go")
        from himari.browser import click
        assert click(page, locator, metadata)["ok"] is True
        assert "clicked" in read_page(page)["text"]


def test_managed_session_keeps_tabs_alive_between_calls(local_url, monkeypatch):
    browsers = detect_browsers()
    if not browsers:
        pytest.skip("no supported installed browser found")
    browser = "chrome" if "chrome" in browsers else browsers[0]

    from himari.browser import tabs as browser_tabs
    from himari.browser import session as session_module
    from himari.browser.session import BrowserSession

    monkeypatch.setattr(session_module, "browser_allowed", lambda: True)
    session = BrowserSession(headless=True)
    try:
        try:
            session.call(lambda manager: manager.open(browser))
        except Exception as exc:
            pytest.skip(f"installed browser could not be automated: {exc}")

        first = session.call(browser_tabs.open_page, local_url, True)
        assert first["ok"] is True
        second = session.call(browser_tabs.open_page, local_url, True)
        assert second["total"] == 2

        listed = session.call(browser_tabs.manage_tabs, "list")
        assert "1." in listed["message"] and "2." in listed["message"]

        kept = session.call(browser_tabs.manage_tabs, "close_others", 1)
        assert "Closed 1 other tab(s)" in kept["message"]
        assert session.call(lambda manager: len(manager.pages())) == 1
    finally:
        session.shutdown()