"""Confirmed, bounded page interactions.

Purchases and payments are refused outright, CAPTCHA/authentication challenges
are never automated, password fields are never filled, and anything that
sends or submits content requires explicit confirmation. Screenshots stay in
memory; nothing is written to disk here.
"""

import re

from .browser_manager import ACTION_TIMEOUT_MS, BrowserError

_PAYMENT_TEXT = re.compile(
    r"\b(buy|buy now|purchase|pay|pay now|payment|checkout|place order|donate)\b",
    re.IGNORECASE,
)
_CAPTCHA_TEXT = re.compile(r"captcha|recaptcha|hcaptcha|security challenge", re.IGNORECASE)
_SUBMIT_TEXT = re.compile(
    r"^(send|post|submit|publish|reply|comment|tweet)\b", re.IGNORECASE
)


def _element_text(metadata):
    return " ".join(
        str(metadata.get(key) or "") for key in ("text", "label", "id", "name")
    )


def _guard(metadata, confirm, action):
    text = _element_text(metadata)
    if _PAYMENT_TEXT.search(text):
        raise BrowserError("Purchases and payments are not permitted.")
    if _CAPTCHA_TEXT.search(text):
        raise BrowserError("CAPTCHA and authentication challenges cannot be automated.")
    submit_like = (
        metadata.get("type") == "submit"
        or bool(_SUBMIT_TEXT.match(str(metadata.get("text") or "").strip()))
    )
    if submit_like or action == "submit":
        if confirm is None or not confirm(action, metadata):
            raise PermissionError(
                "This action sends or submits content and requires explicit confirmation."
            )


def click(page, locator, metadata, confirm=None, token=None, timeout_ms=ACTION_TIMEOUT_MS):
    if token is not None:
        token.check()
    _guard(metadata, confirm, "click")
    try:
        locator.click(timeout=timeout_ms)
    except Exception as exc:
        return {"ok": False, "action": "click", "error": str(exc)}
    return {
        "ok": True,
        "action": "click",
        "element": metadata.get("text") or metadata.get("label") or metadata.get("id"),
    }


def fill(page, locator, metadata, value, confirm=None, token=None,
         timeout_ms=ACTION_TIMEOUT_MS):
    if token is not None:
        token.check()
    if metadata.get("type") == "password":
        raise BrowserError("Password fields are never filled or stored.")
    if not isinstance(value, str):
        raise BrowserError("Fill value must be a string.")
    _guard(metadata, confirm, "fill")
    try:
        locator.fill(value, timeout=timeout_ms)
    except Exception as exc:
        return {"ok": False, "action": "fill", "error": str(exc)}
    return {"ok": True, "action": "fill", "element": metadata.get("id") or metadata.get("name")}


def submit(page, locator, metadata, confirm, token=None, timeout_ms=ACTION_TIMEOUT_MS):
    if token is not None:
        token.check()
    if confirm is None or not confirm("submit", metadata):
        raise PermissionError("Submitting forms requires explicit confirmation.")
    _guard(metadata, lambda action, meta: True, "submit")
    try:
        locator.click(timeout=timeout_ms)
    except Exception as exc:
        return {"ok": False, "action": "submit", "error": str(exc)}
    return {"ok": True, "action": "submit"}


def screenshot(page, token=None, timeout_ms=ACTION_TIMEOUT_MS):
    if token is not None:
        token.check()
    try:
        data = page.screenshot(type="png", full_page=False, timeout=timeout_ms)
    except Exception as exc:
        return {"ok": False, "action": "screenshot", "error": str(exc)}
    return {"ok": True, "action": "screenshot", "format": "png", "bytes": data}