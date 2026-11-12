"""Browser automation: installed-browser sessions, navigation, reading,
confirmed interactions. Disabled by default (allow_browser_automation)."""

from .browser_manager import (
    ACTION_TIMEOUT_MS,
    DEFAULT_TIMEOUT_MS,
    SUPPORTED_BROWSERS,
    BrowserCancelledError,
    BrowserError,
    BrowserManager,
    CancellationToken,
    browser_allowed,
    detect_browsers,
)
from .interactions import click, fill, screenshot, submit
from .navigation import navigate, validate_url
from .page_reader import (
    AmbiguousElementError,
    ElementNotFoundError,
    list_elements,
    locate,
    read_page,
)
from .session import BrowserSession
from .tabs import (
    close_browser,
    manage_tabs,
    open_page,
    open_search,
    read_active,
    search_url,
)

__all__ = [
    "ACTION_TIMEOUT_MS",
    "DEFAULT_TIMEOUT_MS",
    "SUPPORTED_BROWSERS",
    "AmbiguousElementError",
    "BrowserCancelledError",
    "BrowserError",
    "BrowserManager",
    "BrowserSession",
    "CancellationToken",
    "ElementNotFoundError",
    "browser_allowed",
    "close_browser",
    "detect_browsers",
    "manage_tabs",
    "navigate",
    "open_page",
    "open_search",
    "read_active",
    "search_url",
    "validate_url",
    "read_page",
    "list_elements",
    "locate",
    "click",
    "fill",
    "submit",
    "screenshot",
]