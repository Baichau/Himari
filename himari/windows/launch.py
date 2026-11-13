"""Launch and graceful close of applications, gated by existing settings."""

import logging
import os
import subprocess
from pathlib import Path

from ..config import load as load_config
from .apps import find_app
from .enumeration import list_windows, request_window_close
from .errors import AmbiguousAppError, AppNotFoundError

log = logging.getLogger("himari.windows")

BROWSER_NAMES = {
    "chrome.exe": {"chrome", "google chrome"},
    "msedge.exe": {"edge", "microsoft edge"},
    "firefox.exe": {"firefox", "mozilla firefox"},
    "brave.exe": {"brave", "brave browser"},
    "opera.exe": {"opera"},
    "vivaldi.exe": {"vivaldi"},
    "arc.exe": {"arc"},
}


def _browser_aliases(process_name):
    return BROWSER_NAMES.get((process_name or "").casefold())


def _allowed():
    config = load_config()
    permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
    return bool(permissions.get("allow_open_app", False))


def launch_app(name):
    """Open exactly one discovered application; refuse ambiguous matches."""
    if not _allowed():
        raise PermissionError("Permission denied: opening applications is disabled in Settings.")
    requested = (name or "").strip()
    if not requested:
        raise AppNotFoundError("Tell me which application to open.")
    matches = find_app(requested)
    if not matches:
        raise AppNotFoundError(f"Could not find an installed application matching '{requested}'.")
    if len(matches) > 1:
        raise AmbiguousAppError(
            requested,
            [f"{app.name} ({app.source}: {app.target})" for app in matches],
        )
    return _launch_target(matches[0])


def _launch_target(app):
    try:
        if app.source == "store":
            if os.name != "nt":
                raise OSError("Store apps can only be opened on Windows.")
            os.startfile(f"shell:AppsFolder\\{app.target}")
        else:
            target = Path(app.target)
            if not target.is_file():
                return {
                    "ok": False,
                    "app": app.name,
                    "message": (
                        f"'{app.name}' is registered but its files are missing "
                        f"({app.target}). It may have been uninstalled."
                    ),
                }
            if os.name == "nt":
                os.startfile(str(target))
            else:
                subprocess.Popen([str(target)])
    except OSError as exc:
        log.warning("Launch failed for %s: %s", app.name, exc)
        return {"ok": False, "app": app.name, "message": f"Could not open '{app.name}': {exc}"}
    return {"ok": True, "app": app.name, "message": f"Opened {app.name}."}


def close_app(name):
    """Send a normal close request to exactly one matching open window."""
    if not _allowed():
        raise PermissionError("Permission denied: closing applications is disabled in Settings.")
    requested = (name or "").strip()
    if not requested:
        raise AppNotFoundError("Tell me which application to close.")
    needle = requested.casefold()
    matches = []
    for window in list_windows():
        process_stem = window.process_name.casefold()
        if process_stem.endswith(".exe"):
            process_stem = process_stem[:-4]
        if needle == process_stem or needle in window.title.casefold():
            matches.append(window)
    if not matches:
        raise AppNotFoundError(f"No open window matches '{requested}'.")
    if len(matches) > 1:
        raise AmbiguousAppError(
            requested,
            [f"{window.title} ({window.process_name})" for window in matches],
        )
    window = matches[0]
    aliases = _browser_aliases(window.process_name)
    if aliases and needle not in aliases:
        return {
            "ok": False,
            "app": window.title,
            "message": (
                "Refusing to close this browser window: it would close every tab "
                "inside it. Individual tabs in the user's own browser cannot be "
                "closed; a whole browser window can only be closed when the user "
                "asks for the browser itself."
            ),
        }
    try:
        request_window_close(window.hwnd)
    except (OSError, RuntimeError) as exc:
        return {"ok": False, "app": requested, "message": f"Could not send a normal close request: {exc}"}
    return {
        "ok": True,
        "app": window.title,
        "message": (
            f"Sent a normal close request to '{window.title}'. "
            "The application may ask you to save changes."
        ),
    }