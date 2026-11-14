"""On-demand awareness of the desktop environment.

Nothing here runs continuously and no screen is captured. A snapshot is taken
only when a request needs it, and the prompt gets a short, relevant brief
instead of a raw dump of the machine.
"""

import ctypes
import logging
from dataclasses import dataclass, field
from datetime import datetime

from ..config import load

log = logging.getLogger("himari.core.context")

WINDOW_LIMIT = 20
RUNNING_LIMIT = 30


@dataclass
class EnvironmentSnapshot:
    now: str = ""
    weekday: str = ""
    timezone: str = ""
    active_window: dict = field(default_factory=dict)
    windows: list = field(default_factory=list)
    running: list = field(default_factory=list)
    media: dict = field(default_factory=dict)
    spotify: dict = field(default_factory=dict)
    upcoming_events: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def to_dict(self):
        return {
            "now": self.now,
            "weekday": self.weekday,
            "timezone": self.timezone,
            "active_window": self.active_window,
            "windows": self.windows,
            "running": self.running,
            "media": self.media,
            "spotify": self.spotify,
            "upcoming_events": self.upcoming_events,
            "notes": self.notes,
        }


def _active_window():
    try:
        hwnd = int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:
        return {}
    if not hwnd:
        return {}
    try:
        from ..windows import list_windows

        for window in list_windows():
            if int(window.hwnd) == hwnd:
                return {
                    "title": window.title,
                    "process": window.process_name,
                    "hwnd": window.hwnd,
                }
    except Exception as exc:
        log.debug("Could not read the active window: %s", exc)
    return {}


def _window_list():
    try:
        from ..windows import list_windows

        return [
            {"title": window.title, "process": window.process_name}
            for window in list_windows()
        ][:WINDOW_LIMIT]
    except Exception as exc:
        log.debug("Could not enumerate windows: %s", exc)
        return []


def _running_list():
    try:
        from ..windows import running_processes

        names = sorted({process.name for process in running_processes() if process.name})
        return names[:RUNNING_LIMIT]
    except Exception as exc:
        log.debug("Could not list running processes: %s", exc)
        return []


def _media_now_playing():
    try:
        from ..windows import media_session

        item = media_session.now_playing()
        return item.to_dict() if item is not None else {}
    except Exception as exc:
        log.debug("Media session unavailable: %s", exc)
        return {}


def _spotify_status():
    try:
        from ..applications import spotify

        return spotify.status()
    except Exception as exc:
        return {"error": str(exc)}


def _upcoming(days=2, limit=3):
    try:
        from ..applications import calendar

        return [event.to_dict() for event in calendar.list_events(days=days)[:limit]]
    except Exception as exc:
        log.debug("Calendar unavailable: %s", exc)
        return []


class EnvironmentContext:
    def __init__(self, config_loader=None, clock=None):
        self._config_loader = config_loader or load
        self._clock = clock

    def snapshot(self, intent=None, include_windows=False, include_apps=False, include_calendar=False):
        now = datetime.now().astimezone()
        snapshot = EnvironmentSnapshot(
            now=now.isoformat(timespec="seconds"),
            weekday=now.strftime("%A"),
            timezone=now.strftime("%Z") or "local",
            active_window=_active_window(),
        )
        if include_apps:
            snapshot.running = _running_list()
        if include_windows:
            snapshot.windows = _window_list()
        category = getattr(intent, "category", "") if intent is not None else ""
        if include_apps or category in {"music", "app_control", "system"}:
            snapshot.media = _media_now_playing()
        if category == "music" or include_apps:
            snapshot.spotify = _spotify_status()
        if include_calendar or category == "calendar":
            snapshot.upcoming_events = _upcoming()
        return snapshot

    def brief(self, intent=None):
        """Short prompt section, or an empty string when context is irrelevant."""
        category = getattr(intent, "category", "") if intent is not None else "chat"
        include_apps = category in {"music", "app_control", "system", "development", "deep_work"}
        include_windows = category in {"app_control", "screen"}
        snapshot = self.snapshot(
            intent,
            include_windows=include_windows,
            include_apps=include_apps,
            include_calendar=category == "calendar",
        )
        lines = [
            f"Current local time: {snapshot.now} ({snapshot.weekday}, {snapshot.timezone})"
        ]
        active = snapshot.active_window
        contextual = category not in {"chat", "information", "research", "weather", "calendar"}
        if active and contextual:
            lines.append(
                f"Active window: {active.get('title')} [{active.get('process')}]"
            )
        if snapshot.windows:
            titles = "; ".join(
                f"{item.get('title')} [{item.get('process')}]"
                for item in snapshot.windows[:10]
            )
            lines.append(f"Open windows: {titles}")
        if snapshot.running:
            lines.append("Running processes: " + ", ".join(snapshot.running[:20]))
        if category in {"development", "deep_work", "file"}:
            try:
                from ..development import active_project

                project = active_project()
            except Exception as exc:
                log.debug("Active project unavailable: %s", exc)
                project = None
            if project is not None:
                lines.append(
                    f"Open project: {project} — relative file paths resolve there"
                )
            try:
                config = self._config_loader()
                permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
                if permissions.get("allow_vscode_state", False):
                    from ..skills import pair

                    editors = pair.open_editors()
                    active_file = editors.get("active") or ""
                    if active_file:
                        lines.append(f"VS Code active file: {active_file}")
            except Exception as exc:
                log.debug("VS Code editor context unavailable: %s", exc)
        try:
            from ..skills import watch as watch_skill

            watch_status = watch_skill.session().status()
        except Exception as exc:
            log.debug("Watch status unavailable: %s", exc)
            watch_status = {}
        if watch_status.get("running"):
            last = watch_status.get("last") or {}
            subject = last.get("game") or last.get("application") or "unknown app"
            lines.append(
                f"Watch session: running, {watch_status.get('remaining_text')} left; "
                f"last look: {subject}. Observations are in-memory only."
            )
        media = snapshot.media
        if media:
            state = "playing" if media.get("playing") else "paused"
            lines.append(
                f"Active media session: {media.get('title')} — {media.get('artist')} "
                f"[{media.get('app')}, {state}]"
            )
        spotify = snapshot.spotify
        if spotify and category == "music":
            lines.append(
                "Spotify: "
                + (
                    f"installed={spotify.get('installed')}, running={spotify.get('running')}, "
                    f"web_api={'ready' if spotify.get('api_ready') else 'not configured'}"
                )
            )
        if snapshot.upcoming_events:
            lines.append(
                "Upcoming events: "
                + "; ".join(
                    f"{item.get('when')} {item.get('title')}"
                    for item in snapshot.upcoming_events
                )
            )
        if len(lines) == 1 and category == "chat":
            return ""
        return "CURRENT ENVIRONMENT (observed on demand, untrusted data):\n" + "\n".join(lines)


_DEFAULT = EnvironmentContext()


def brief(intent=None):
    try:
        return _DEFAULT.brief(intent)
    except Exception as exc:
        log.warning("Environment brief failed: %s", exc)
        return ""
