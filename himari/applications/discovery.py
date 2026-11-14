"""Generic Windows application discovery and capability levels.

Himari must not depend on a hardcoded list of applications. This module turns
Start Menu shortcuts, registry entries and packaged Store apps into one
registry with aliases, fuzzy resolution, running state and an honest support
level:

- discovered   : Himari can see it
- launchable   : a target exists that Windows can start
- inspectable  : a window can be enumerated for it
- interactable : UI Automation can read its controls
- integrated   : a dedicated integration exists
"""

import difflib
import logging
import re
from dataclasses import dataclass

from .. import windows

log = logging.getLogger("himari.applications.discovery")

MAX_CANDIDATES = 8
FUZZY_CUTOFF = 0.72

ALIASES = {
    "browser": ("Google Chrome", "Microsoft Edge", "Firefox", "Opera", "Brave"),
    "web browser": ("Google Chrome", "Microsoft Edge", "Firefox"),
    "default browser": ("Google Chrome", "Microsoft Edge", "Firefox"),
    "code editor": ("Visual Studio Code",),
    "editor": ("Visual Studio Code", "Notepad"),
    "vscode": ("Visual Studio Code",),
    "vs code": ("Visual Studio Code",),
    "music": ("Spotify",),
    "music app": ("Spotify",),
    "terminal": ("Windows Terminal", "PowerShell", "Command Prompt"),
    "shell": ("PowerShell", "Command Prompt"),
    "files": ("File Explorer",),
    "explorer": ("File Explorer",),
    "qoder": ("Qoder",),
}
INTEGRATED_APPS = {"spotify", "steam", "visual studio code", "chrome", "google chrome", "discord"}


@dataclass(frozen=True)
class ApplicationRecord:
    name: str
    target: str
    source: str
    running: bool = False
    windows: tuple = ()
    support: str = "discovered"
    alias: str = ""

    def to_dict(self):
        return {
            "name": self.name,
            "target": self.target,
            "source": self.source,
            "running": self.running,
            "windows": list(self.windows),
            "support": self.support,
            "alias": self.alias,
        }


def _stem(value):
    text = str(value or "").casefold().strip()
    text = re.split(r"[\\/]", text)[-1]
    for suffix in (".exe", ".lnk", ".url"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def _normalize(value):
    text = re.sub(r"[^a-z0-9 ]+", " ", str(value or "").casefold())
    return re.sub(r"\s+", " ", text).strip()


def _running_stems():
    stems = set()
    try:
        for process in windows.running_processes():
            stems.add(_stem(process.name))
    except Exception as exc:
        log.debug("Could not read running processes: %s", exc)
    return stems


def _windows_by_name():
    grouped = {}
    try:
        open_windows = windows.list_windows()
    except Exception as exc:
        log.debug("Could not enumerate windows: %s", exc)
        return grouped
    for window in open_windows:
        key = _stem(window.process_name)
        grouped.setdefault(key, []).append(window.title)
    return grouped


def _windows_for(record):
    grouped = _windows_by_name()
    target_stem = _stem(record.target)
    if target_stem in grouped:
        return tuple(grouped[target_stem])
    wanted = _normalize(record.name)
    if not wanted:
        return tuple(record.windows)
    matched = []
    for stem, titles in grouped.items():
        normalized = _normalize(stem)
        if not normalized:
            continue
        if normalized in wanted or wanted in normalized:
            matched.extend(titles)
    return tuple(matched) or tuple(record.windows)


def _support_level(name, record_windows, integrated):
    if integrated:
        return "integrated"
    if record_windows:
        return "inspectable"
    return "launchable" if name else "discovered"


def _integrated_names():
    try:
        from ..integrations.registry import all_integrations

        return {item.name.casefold() for item in all_integrations()}
    except Exception:
        return set(INTEGRATED_APPS)


def registry(refresh=False):
    """Return every discovered application with running and support state."""
    apps = list(windows.installed_apps(refresh=refresh))
    running = _running_stems()
    grouped = _windows_by_name()
    integrated = _integrated_names()
    records = []
    for app in apps:
        stem = _stem(app.target if app.source != "store" else app.name)
        app_windows = tuple(grouped.get(stem, ()))
        is_running = stem in running or bool(app_windows)
        name_key = _normalize(app.name)
        support = _support_level(app.name, app_windows, name_key in integrated)
        records.append(
            ApplicationRecord(
                name=app.name,
                target=app.target,
                source=app.source,
                running=is_running,
                windows=app_windows,
                support=support,
            )
        )
    records.sort(key=lambda item: (not item.running, item.name.casefold()))
    return records


def _alias_targets(query):
    key = _normalize(query)
    names = ALIASES.get(key)
    return tuple(names or ())


def resolve(query, records=None, limit=MAX_CANDIDATES):
    """Resolve a name or alias to ranked candidates; never guesses silently."""
    requested = str(query or "").strip()
    if not requested:
        return []
    records = records if records is not None else registry()
    by_name = {}
    for record in records:
        by_name.setdefault(_normalize(record.name), record)

    candidates = []
    for alias_name in _alias_targets(requested):
        record = by_name.get(_normalize(alias_name))
        if record is not None:
            candidates.append(
                ApplicationRecord(
                    name=record.name,
                    target=record.target,
                    source=record.source,
                    running=record.running,
                    windows=record.windows,
                    support=record.support,
                    alias=requested,
                )
            )
    if candidates:
        return candidates[:limit]

    wanted = _normalize(requested)
    exact = [record for record in records if _normalize(record.name) == wanted]
    if exact:
        return exact[:limit]
    partial = [record for record in records if wanted in _normalize(record.name)]
    if partial:
        return sorted(partial, key=lambda item: len(item.name))[:limit]
    names = {_normalize(record.name): record for record in records}
    scored = sorted(
        (
            (difflib.SequenceMatcher(None, wanted, name).ratio(), record)
            for name, record in names.items()
        ),
        key=lambda item: -item[0],
    )
    return [record for score, record in scored if score >= FUZZY_CUTOFF][:limit]


def describe(query):
    """Return one resolved app plus its windows, or ambiguity candidates."""
    records = registry()
    candidates = resolve(query, records=records)
    if not candidates:
        return {
            "ok": False,
            "error": f"No installed application matches '{query}'.",
            "hint": "Use list_apps to see discovered applications.",
        }
    if len(candidates) > 1:
        first = candidates[0]
        same_target = all(item.target == first.target for item in candidates)
        if not same_target:
            return {
                "ok": False,
                "ambiguous": True,
                "error": f"{len(candidates)} applications match '{query}'.",
                "candidates": [item.name for item in candidates],
            }
    record = candidates[0]
    windows_for_app = _windows_for(record)
    support = record.support
    if windows_for_app and support == "launchable":
        support = "inspectable"
    return {
        "ok": True,
        "application": record.name,
        "target": record.target,
        "source": record.source,
        "running": record.running or bool(windows_for_app),
        "windows": list(windows_for_app),
        "alias": record.alias,
        "support": support,
        "note": (
            "Integrated means a dedicated integration exists. Inspectable means a "
            "window can be read. Interactable is verified per control through "
            "list_controls, not assumed from installation."
        ),
    }


def list_apps(query="", limit=25):
    """Search the registry; an empty query lists running apps first."""
    records = registry()
    needle = _normalize(query)
    if needle:
        records = [
            record
            for record in resolve(query, records=records, limit=limit)
        ]
    running = [record for record in records if record.running]
    idle = [record for record in records if not record.running]
    combined = (running + idle)[: max(1, min(int(limit), 100))]
    return {
        "ok": True,
        "count": len(combined),
        "applications": [record.to_dict() for record in combined],
    }
