"""URL validation and navigation with explicit timeouts."""

import re
from urllib.parse import urlparse

from .browser_manager import DEFAULT_TIMEOUT_MS, BrowserError

_SCHEME = re.compile(r"^([a-z][a-z0-9+.-]*):", re.IGNORECASE)


def validate_url(url):
    if not isinstance(url, str) or not url.strip():
        raise BrowserError("Provide a website URL.")
    if any(char in url for char in "\r\n\x00"):
        raise BrowserError("The URL contains invalid whitespace or control characters.")
    url = url.strip()
    scheme_match = _SCHEME.match(url)
    if scheme_match:
        if scheme_match.group(1).lower() not in {"http", "https"}:
            raise BrowserError("Only valid HTTP or HTTPS URLs can be opened.")
    else:
        url = "https://" + url
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError:
        raise BrowserError("Only valid HTTP or HTTPS URLs can be opened.") from None
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise BrowserError("Only valid HTTP or HTTPS URLs can be opened.")
    if any(char.isspace() or char == "\x00" for char in url):
        raise BrowserError("The URL contains invalid whitespace or control characters.")
    return url


def navigate(page, url, timeout_ms=DEFAULT_TIMEOUT_MS, token=None):
    if token is not None:
        token.check()
    target = validate_url(url)
    try:
        page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
        return {"ok": True, "url": page.url, "title": page.title()}
    except Exception as exc:
        return {"ok": False, "url": target, "error": str(exc)}