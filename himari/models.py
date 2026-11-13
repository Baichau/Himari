"""Capability detection for locally installed Ollama models.

Ollama reports capabilities such as ``completion``, ``tools``, ``thinking`` and
``vision`` per model. Himari uses this to avoid sending unsupported options and
to explain a missing backend honestly instead of retrying blindly.
"""

import logging
import threading
import time

from .config import load

log = logging.getLogger("himari.models")

CACHE_TTL_SECONDS = 300
_capabilities_cache = {}
_cache_lock = threading.Lock()


def _client(timeout=5):
    import ollama

    settings = load().get("ollama", {})
    return ollama.Client(
        host=settings.get("host", "http://127.0.0.1:11434"),
        timeout=timeout,
    )


def _extract_capabilities(response):
    if isinstance(response, dict):
        raw = response.get("capabilities")
    else:
        raw = getattr(response, "capabilities", None)
    if raw is None:
        return None
    return frozenset(str(item).casefold() for item in raw)


def model_capabilities(model=None, client=None):
    """Return a frozenset of capabilities, or None when they cannot be read."""
    settings = load().get("ollama", {})
    name = str(model or settings.get("chat_model") or "").strip()
    if not name:
        return None
    key = (str(settings.get("host") or ""), name)
    now = time.monotonic()
    with _cache_lock:
        cached = _capabilities_cache.get(key)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
    try:
        info = (client or _client()).show(name)
    except Exception as exc:
        log.info("Could not read capabilities for '%s': %s", name, exc)
        return None
    capabilities = _extract_capabilities(info)
    with _cache_lock:
        _capabilities_cache[key] = (now, capabilities)
    return capabilities


def supports(capability, model=None, client=None):
    """True/False when capabilities are known, None when they are not."""
    capabilities = model_capabilities(model, client)
    if capabilities is None:
        return None
    return str(capability).casefold() in capabilities


def clear_cache():
    with _cache_lock:
        _capabilities_cache.clear()
