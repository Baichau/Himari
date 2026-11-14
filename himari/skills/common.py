"""Small shared helpers for the opt-in capability skills.

Nothing here talks to a model. The helpers keep outputs bounded and make sure
secret-looking config values can never be echoed into a chat reply.
"""

import os
import time

from ..config import load

SECRET_WORDS = (
    "secret",
    "token",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "client_id",
)


def permission(key):
    config = load()
    permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
    return bool(permissions.get(key, False))


def config_section(name):
    config = load()
    section = config.get(name, {}) if isinstance(config, dict) else {}
    return section if isinstance(section, dict) else {}


def looks_secret(key):
    lowered = str(key or "").casefold()
    return any(word in lowered for word in SECRET_WORDS)


def mask_value(key, value):
    """Replace secret-looking values with a presence marker, never the value."""
    if not looks_secret(key):
        return value
    if isinstance(value, str):
        return "configured" if value.strip() else "missing"
    return "configured" if value else "missing"


def mask_mapping(mapping):
    result = {}
    for key, value in (mapping or {}).items():
        if isinstance(value, dict):
            result[key] = mask_mapping(value)
        else:
            result[key] = mask_value(key, value)
    return result


def bounded_text(text, limit=4000):
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def bounded_lines(lines, limit=40):
    result = []
    for line in lines or []:
        value = " ".join(str(line or "").split())
        if value:
            result.append(value)
        if len(result) >= limit:
            break
    return result


def stamp(when=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when or time.time()))


def is_windows():
    return os.name == "nt"
