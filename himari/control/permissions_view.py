"""Read-only permission overview for the Control Center."""

from ..config import load
from .settings import SettingsService

PERMISSION_LABELS = {
    "allow_open_app": (
        "Open apps and games",
        "Launch installed applications, Steam games, and integrations.",
    ),
    "allow_open_url": (
        "Open websites",
        "Open links and search results in the default browser.",
    ),
    "allow_web_research": (
        "Background web research",
        "Quietly check DuckDuckGo for factual questions; search terms leave the device.",
    ),
    "allow_read_file": (
        "Read files",
        "Read text files inside the allowed folders after confirmation.",
    ),
    "allow_volume": (
        "Volume control",
        "Change the system volume on request.",
    ),
    "allow_write_file": (
        "Write files",
        "Write files inside the allowed folders after confirmation.",
    ),
    "allow_screen_capture": (
        "Screen capture",
        "One-shot capture with per-capture confirmation; the image stays in memory "
        "as an attachment and is discarded after the chat.",
    ),
    "allow_vision": (
        "Image understanding",
        "Send attached or captured images to the local Ollama vision model on Send.",
    ),
    "allow_screen_control": (
        "Screen control",
        "Click named controls, type text, and send key presses to open windows. "
        "Every input action asks for confirmation.",
    ),
    "allow_active_window": (
        "Active-window detection",
        "Read the foreground window title only when explicitly requested.",
    ),
    "allow_media_control": (
        "Media keys",
        "Send media keys to the active Windows media session.",
    ),
    "allow_browser_automation": (
        "Browser automation",
        "Drive a local browser; payments, logins, and CAPTCHA bypass are refused.",
    ),
    "allow_run_command": (
        "Shell commands",
        "Reserved and disabled; dedicated tools replace arbitrary shell access.",
    ),
}

_UNSAFE_KEYS = {"allow_run_command"}


def permission_rows(config=None):
    config = load() if config is None else config
    permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
    rows = []
    for key, (label, description) in PERMISSION_LABELS.items():
        rows.append({
            "key": key,
            "label": label,
            "description": description,
            "enabled": bool(permissions.get(key, False)),
            "editable": key not in _UNSAFE_KEYS,
        })
    rows.append({
        "key": "allowed_folders",
        "label": "Allowed folders",
        "description": "Folders file tools may access: "
        + (", ".join(permissions.get("allowed_folders", [])) or "none"),
        "enabled": bool(permissions.get("allowed_folders")),
        "editable": True,
    })
    return rows


def set_permission(key, enabled, service=None):
    if key in _UNSAFE_KEYS:
        raise ValueError(f"'{key}' cannot be enabled from the Control Center.")
    service = service or SettingsService()
    return service.set_permission(key, enabled)


def enabled_capabilities(config=None):
    return [row["label"] for row in permission_rows(config) if row["enabled"]]


def requires_confirmation_summary(config=None):
    config = load() if config is None else config
    permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
    return {
        "file_access": bool(permissions.get("allow_read_file")),
        "file_writes": bool(permissions.get("allow_write_file")),
        "screen": bool(permissions.get("allow_screen_capture")),
        "browser": bool(permissions.get("allow_browser_automation", False)),
    }
