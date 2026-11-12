"""Browser session management on top of Playwright.

Drives browsers that are already installed (Chrome/Edge/Firefox channels);
it never downloads browsers. A small permission interface is used here and
can later be replaced by the centralized security module.
"""

import logging
import threading

from ..config import load as load_config

log = logging.getLogger("himari.browser")

DEFAULT_TIMEOUT_MS = 15_000
ACTION_TIMEOUT_MS = 5_000

SUPPORTED_BROWSERS = {"chrome": "chrome", "edge": "msedge", "firefox": "firefox"}


class BrowserError(RuntimeError):
    """Base error for browser automation."""


class BrowserCancelledError(BrowserError):
    """The caller cancelled the pending browser action."""


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set()

    def check(self):
        if self.cancelled:
            raise BrowserCancelledError("Browser action was cancelled.")


def browser_allowed():
    config = load_config()
    permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
    return bool(permissions.get("allow_browser_automation", False))


def detect_browsers():
    """Return supported browsers found by the read-only Windows discovery."""
    from ..windows import installed_apps

    names = {app.name.casefold() for app in installed_apps()}
    markers = {
        "chrome": ("google chrome",),
        "edge": ("microsoft edge",),
        "firefox": ("firefox",),
    }
    return [
        browser
        for browser, candidates in markers.items()
        if any(candidate in name for name in names for candidate in candidates)
    ]


class BrowserManager:
    def __init__(self, headless=True, timeout_ms=DEFAULT_TIMEOUT_MS,
                 permission_check=None, token=None):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._permission_check = permission_check or browser_allowed
        self.token = token or CancellationToken()
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    def open(self, browser="chrome"):
        if not self._permission_check():
            raise PermissionError(
                "Permission denied: browser automation is disabled in Settings."
            )
        self.token.check()
        if self._browser is not None and not self._browser.is_connected():
            self.close()
        if self.page is not None and not self.page.is_closed():
            return self.page
        if self._context is not None:
            self.page = self._context.new_page()
            self.page.set_default_navigation_timeout(self.timeout_ms)
            return self.page
        if browser not in SUPPORTED_BROWSERS:
            raise BrowserError(
                f"Unsupported browser '{browser}. Choose from: {', '.join(SUPPORTED_BROWSERS)}."
            )
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserError(
                "Playwright is not installed. Run: pip install playwright"
            ) from exc
        self._playwright = sync_playwright().start()
        try:
            launcher = (
                self._playwright.firefox
                if browser == "firefox"
                else self._playwright.chromium
            )
            self._browser = launcher.launch(
                channel=SUPPORTED_BROWSERS[browser], headless=self.headless
            )
            self._context = self._browser.new_context()
            self._context.set_default_timeout(ACTION_TIMEOUT_MS)
            self.page = self._context.new_page()
            self.page.set_default_navigation_timeout(self.timeout_ms)
        except Exception as exc:
            self.close()
            raise BrowserError(
                f"Could not start {browser}: {exc}. Is it installed?"
            ) from exc
        return self.page

    @property
    def context(self):
        return self._context

    def pages(self):
        """Open pages/tabs in creation order, ignoring tabs the user closed."""
        if self._context is None:
            return []
        pages = []
        for page in self._context.pages:
            try:
                if page.is_closed():
                    continue
            except Exception:
                continue
            pages.append(page)
        return pages

    def new_page(self):
        self.open()
        if self._context is None:
            return self.page
        created = self._context.new_page()
        created.set_default_navigation_timeout(self.timeout_ms)
        return created

    def close(self):
        resources = [self.page, self._context, self._browser]
        self.page = self._context = self._browser = None
        for resource in resources:
            if resource is None:
                continue
            try:
                resource.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False