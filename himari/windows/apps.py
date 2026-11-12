"""Read-only discovery of installed Windows applications.

Sources: Start Menu shortcuts, registry App Paths, and packaged Store apps
enumerated through Get-StartApps. Discovery never launches or modifies
anything.
"""

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("himari.windows")

STORE_LOOKUP_TIMEOUT_SECONDS = 15
CACHE_TTL_SECONDS = 60.0
_CACHE = None
_CACHE_TIME = 0.0


@dataclass(frozen=True)
class AppInfo:
    name: str
    target: str
    source: str  # "start_menu" | "registry" | "store"


def _start_menu_roots():
    return [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]


def _start_menu_apps():
    apps = []
    for root in _start_menu_roots():
        if not root.is_dir():
            continue
        for shortcut in sorted(root.rglob("*.lnk")):
            apps.append(AppInfo(name=shortcut.stem, target=str(shortcut), source="start_menu"))
    return apps


def _registry_apps():
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    apps = []
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (
            getattr(winreg, "KEY_WOW64_64KEY", 0),
            getattr(winreg, "KEY_WOW64_32KEY", 0),
        ):
            try:
                with winreg.OpenKey(hive, base, 0, winreg.KEY_READ | view) as key:
                    index = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                exe_path, _ = winreg.QueryValueEx(subkey, "")
                        except OSError:
                            continue
                        if not exe_path:
                            continue
                        name = subkey_name
                        if name.casefold().endswith(".exe"):
                            name = name[:-4]
                        apps.append(AppInfo(
                            name=name,
                            target=os.path.expandvars(str(exe_path)),
                            source="registry",
                        ))
            except OSError:
                continue
    return apps


def _store_apps():
    if os.name != "nt":
        return []
    script = "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=STORE_LOOKUP_TIMEOUT_SECONDS,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Could not enumerate Windows Store apps: %s", exc)
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        log.warning("Could not parse the Get-StartApps output.")
        return []
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return []
    apps = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("Name") or "").strip()
        app_id = str(entry.get("AppID") or "").strip()
        if name and app_id:
            apps.append(AppInfo(name=name, target=app_id, source="store"))
    return apps


def installed_apps(refresh=False):
    """Return every discovered application, deduplicated and sorted by name.

    Results are cached briefly so repeated lookups stay fast; discovery itself
    is always read-only.
    """
    global _CACHE, _CACHE_TIME
    now = time.monotonic()
    if not refresh and _CACHE is not None and now - _CACHE_TIME < CACHE_TTL_SECONDS:
        return _CACHE
    unique = {}
    for app in [*_start_menu_apps(), *_registry_apps(), *_store_apps()]:
        key = (app.name.casefold(), app.target.casefold())
        unique.setdefault(key, app)
    result = sorted(
        unique.values(),
        key=lambda app: (app.name.casefold(), app.source, app.target.casefold()),
    )
    _CACHE = result
    _CACHE_TIME = now
    return result


def find_app(name):
    """Return all applications matching a name.

    Exact (case-insensitive) matches win; otherwise substring matches are
    returned. Duplicate names are all returned so callers never have to guess.
    """
    requested = (name or "").strip().casefold()
    if not requested:
        return []
    apps = installed_apps()
    exact = [app for app in apps if app.name.casefold() == requested]
    if exact:
        return exact
    return [app for app in apps if requested in app.name.casefold()]