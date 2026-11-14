"""Opt-in, bounded screen watching for gaming and app companionship.

A watch session takes one local look at a fixed interval, keeps only short
text observations in memory, shows a visible indicator in the UI, and always
stops itself after the configured limit. Screenshots are discarded by the
perception layer immediately; nothing is written to disk.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .common import bounded_lines, bounded_text, config_section, permission, stamp

MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 20
MAX_MINUTES = 30
DEFAULT_MINUTES = 30
MAX_OBSERVATIONS = 60
MAX_TEXT_CHARS = 1500
MAX_DIGEST_OBSERVATIONS = 8
MAX_ERRORS = 3

GAME_HINTS = (
    "valorant",
    "league of legends",
    "leagueclient",
    "counter-strike",
    "cs2.exe",
    "csgo.exe",
    "dota 2",
    "dota2.exe",
    "minecraft",
    "genshin impact",
    "genshinimpact",
    "fortnite",
    "apex legends",
    "r5apex",
    "rainbow six",
    "rocket league",
    "grand theft auto",
    "gta5.exe",
    "red dead redemption",
    "elden ring",
    "stardew valley",
    "terraria",
    "roblox",
    "overwatch",
    "destiny 2",
    "warframe",
    "cyberpunk 2077",
    "baldur's gate",
    "palworld",
    "helldivers",
    "the sims 4",
    "football manager",
    "fifa",
    "ea sports fc",
)


class WatchPermissionError(PermissionError):
    """Watch mode or one-time screen capture is disabled in Settings."""


class WatchError(RuntimeError):
    """A watch session could not be started or has nothing to report."""


@dataclass(frozen=True)
class WatchObservation:
    at: float
    application: str = ""
    window_title: str = ""
    game: str = ""
    visible_text: str = ""
    windows: tuple = ()
    error: str = ""

    def to_dict(self):
        return {
            "at": stamp(self.at),
            "application": self.application,
            "window_title": self.window_title,
            "game": self.game,
            "visible_text": self.visible_text,
            "windows": list(self.windows),
            "error": self.error,
        }

    def line(self):
        subject = self.game or self.application or "unknown app"
        title = f' — "{self.window_title}"' if self.window_title else ""
        return f"[{stamp(self.at)}] {subject}{title}"


def _configured_interval():
    value = config_section("screen").get("watch_interval_seconds")
    try:
        return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS


def _configured_minutes():
    value = config_section("screen").get("watch_max_minutes")
    try:
        return max(1, min(MAX_MINUTES, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_MINUTES


def detect_game(application="", title=""):
    """Return the matched game hint, or an empty string."""
    text = f"{application} {title}".casefold()
    for hint in GAME_HINTS:
        if hint in text:
            return hint.replace(".exe", "").title()
    return ""


def _scene():
    """One local capture + OCR scene; separated so tests can replace it."""
    from ..perception.scene import build_scene

    active = permission("allow_active_window")
    return build_scene(active_window=bool(active))


def _observation_from_scene(scene):
    visible = bounded_text(" ".join(scene.get("visible_text") or []), MAX_TEXT_CHARS)
    windows = bounded_lines(
        [
            f"{item.get('title')} [{item.get('process')}]"
            for item in (scene.get("ui_elements") or [])
            if isinstance(item, dict)
        ],
        8,
    )
    application = str(scene.get("application") or "")
    title = str(scene.get("window_title") or "")
    return WatchObservation(
        at=time.time(),
        application=application,
        window_title=title,
        game=detect_game(application, title),
        visible_text=visible,
        windows=tuple(windows),
        error=str(scene.get("ocr_error") or ""),
    )


class WatchSession:
    """One in-memory watch session; never shared across processes."""

    def __init__(self, scene_reader=None, clock=None):
        self._scene_reader = scene_reader or _scene
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._capture_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._running = False
        self._started_at = 0.0
        self._ends_at = 0.0
        self._interval = DEFAULT_INTERVAL_SECONDS
        self._minutes = DEFAULT_MINUTES
        self._game_only = False
        self._observations = []
        self._reason = ""
        self._errors = 0

    def _now(self):
        return float(self._clock())

    def is_running(self):
        with self._lock:
            return bool(
                self._running
                and not self._stop_event.is_set()
                and self._now() < self._ends_at
            )

    def start(self, interval_seconds=None, minutes=None, game_only=False):
        if not permission("allow_watch_mode"):
            raise WatchPermissionError(
                "Permission denied: 'allow_watch_mode' is disabled in Settings."
            )
        if not permission("allow_screen_capture"):
            raise WatchPermissionError(
                "Permission denied: one-time screen capture is disabled in Settings."
            )
        with self._lock:
            if self.is_running():
                raise WatchError("A watch session is already running.")
            try:
                interval = int(interval_seconds)
            except (TypeError, ValueError):
                interval = _configured_interval()
            try:
                limit = int(minutes)
            except (TypeError, ValueError):
                limit = _configured_minutes()
            self._interval = max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, interval))
            self._minutes = max(1, min(MAX_MINUTES, limit))
            self._game_only = bool(game_only)
            self._started_at = self._now()
            self._ends_at = self._started_at + self._minutes * 60
            self._observations = []
            self._reason = ""
            self._errors = 0
            self._stop_event.clear()
            self._running = True
            self._thread = threading.Thread(
                target=self._run, name="himari-watch", daemon=True
            )
            self._thread.start()
            return self.status()

    def stop(self, reason="stopped"):
        with self._lock:
            was_running = self._running
            self._running = False
            self._reason = str(reason or "stopped")
            self._stop_event.set()
        return {"was_running": was_running, **self.status()}

    def _run(self):
        while not self._stop_event.is_set():
            if not self.is_running():
                break
            self.capture()
            remaining = max(0.5, self._ends_at - self._now())
            self._stop_event.wait(min(self._interval, remaining))
        with self._lock:
            if self._running and self._now() >= self._ends_at:
                self._reason = "time limit reached"
            self._running = False
            self._stop_event.set()

    def _permissions_ok(self):
        if not permission("allow_watch_mode"):
            self.stop("watch permission turned off")
            return False
        if not permission("allow_screen_capture"):
            self.stop("screen capture permission turned off")
            return False
        return True

    def capture(self, force=False):
        """Take one look. Always in-memory; never persisted."""
        if not force and not self.is_running():
            raise WatchError("The watch session is not running.")
        if not self._permissions_ok():
            raise WatchPermissionError("Watch permissions were turned off.")
        if not self._capture_lock.acquire(blocking=False):
            return None
        try:
            try:
                scene = self._scene_reader()
                observation = _observation_from_scene(scene or {})
                self._errors = 0
            except Exception as exc:
                self._errors += 1
                observation = WatchObservation(
                    at=self._now(),
                    error=bounded_text(exc, 240),
                )
            with self._lock:
                if self._game_only and not observation.game:
                    if self._errors >= MAX_ERRORS:
                        self.stop("repeated capture errors")
                    return observation
                self._observations.append(observation)
                if len(self._observations) > MAX_OBSERVATIONS:
                    del self._observations[:-MAX_OBSERVATIONS]
            if self._errors >= MAX_ERRORS:
                self.stop("repeated capture errors")
            return observation
        finally:
            self._capture_lock.release()

    def observe_now(self):
        if not self.is_running():
            raise WatchError("Start a watch session before asking for a new look.")
        observation = self.capture(force=True)
        if observation is None:
            raise WatchError("The previous look is still finishing.")
        return observation

    def observations(self):
        with self._lock:
            return list(self._observations)

    def latest(self):
        with self._lock:
            return self._observations[-1] if self._observations else None

    def status(self):
        with self._lock:
            now = self._now()
            running = bool(
                self._running
                and not self._stop_event.is_set()
                and now < self._ends_at
            )
            remaining = max(0, int(self._ends_at - now)) if self._ends_at else 0
            latest = self._observations[-1] if self._observations else None
            return {
                "running": running,
                "interval_seconds": self._interval,
                "limit_minutes": self._minutes,
                "remaining_seconds": remaining,
                "remaining_text": f"{remaining // 60}:{remaining % 60:02d}",
                "observations": len(self._observations),
                "game_only": self._game_only,
                "started_at": stamp(self._started_at) if self._started_at else "",
                "last": latest.to_dict() if latest else None,
                "reason": self._reason,
            }

    def digest(self, max_chars=4000):
        """Recent observations as bounded text for the local model."""
        observations = self.observations()[-MAX_DIGEST_OBSERVATIONS:]
        if not observations:
            return "No watch observations yet."
        lines = []
        for observation in observations:
            lines.append(observation.line())
            if observation.error:
                lines.append(f"  look failed: {observation.error}")
            elif observation.visible_text:
                lines.append(f"  visible text: {observation.visible_text}")
            if observation.windows:
                lines.append("  windows: " + "; ".join(observation.windows))
        text = "\n".join(lines)
        return text[:max_chars]

    def summary(self):
        observations = self.observations()
        status = self.status()
        if not observations:
            return (
                "The watch session ended without observations. "
                "Nothing was saved."
            )
        games = sorted({item.game for item in observations if item.game})
        apps = sorted(
            {
                item.application
                for item in observations
                if item.application and not item.game
            }
        )
        duration = max(0, int(self._now() - self._started_at))
        lines = [
            f"Watch session: {len(observations)} look(s) over "
            f"{duration // 60}m {duration % 60}s.",
            "Games seen: " + (", ".join(games) if games else "none detected."),
            "Apps seen: " + (", ".join(apps[:6]) if apps else "none."),
            f"Stopped: {status.get('reason') or 'user request'}.",
            "Screenshots were discarded immediately; nothing was saved.",
            "",
            "Most recent looks:",
            self.digest(1800),
        ]
        return "\n".join(lines)


_SESSION = WatchSession()


def session():
    return _SESSION


def observe_once():
    """A single opt-in look that does not start a session."""
    if not permission("allow_watch_mode"):
        raise WatchPermissionError(
            "Permission denied: 'allow_watch_mode' is disabled in Settings."
        )
    if not permission("allow_screen_capture"):
        raise WatchPermissionError(
            "Permission denied: one-time screen capture is disabled in Settings."
        )
    scene = _scene()
    return _observation_from_scene(scene)


def _status_text(status):
    if not status.get("running"):
        reason = status.get("reason") or "not running"
        looks = status.get("observations") or 0
        return (
            f"Watch session is not running ({reason}). "
            f"Looks this session: {looks}. Nothing is saved."
        )
    last = status.get("last") or {}
    subject = last.get("game") or last.get("application") or "unknown app"
    return (
        f"Watching: one look every {status['interval_seconds']}s, "
        f"{status['remaining_text']} left (max {status['limit_minutes']} min). "
        f"Looks: {status['observations']}. Last: {subject}. "
        "A visible indicator is shown and screenshots are discarded."
    )


def watch_start(interval_seconds=None, minutes=None, game_only=False):
    try:
        status = session().start(interval_seconds, minutes, game_only)
    except (WatchPermissionError, WatchError) as exc:
        return f"Watch not started: {exc}"
    game_note = " Only game looks are kept." if status.get("game_only") else ""
    return (
        "Watch session started. Himari takes one local look every "
        f"{status['interval_seconds']} seconds and stops automatically after "
        f"{status['limit_minutes']} minutes.{game_note} "
        "The watch indicator is visible in the sidebar; say 'stop watching' "
        "or use the Stop button. Screenshots are discarded and nothing is saved."
    )


def watch_stop():
    status = session().stop("stopped by user")
    if not status.get("was_running"):
        return "No watch session was running."
    return session().summary()


def watch_status():
    return _status_text(session().status())


def watch_observe():
    try:
        if session().is_running():
            observation = session().observe_now()
        else:
            observation = observe_once()
    except (WatchPermissionError, WatchError) as exc:
        return f"Could not look at the screen: {exc}"
    if observation.error and not observation.visible_text:
        return f"Look failed: {observation.error}"
    lines = [observation.line()]
    if observation.visible_text:
        lines.append("Visible text: " + observation.visible_text)
    if observation.windows:
        lines.append("Windows: " + "; ".join(observation.windows))
    lines.append("The screenshot was discarded immediately and was not saved.")
    return "\n".join(lines)


TOOLS = [
    {
        "name": "watch_start",
        "confirm": True,
        "confirm_message": (
            "Allow Himari to start a bounded watch session? It takes one local "
            "look every few seconds while a visible indicator is shown, stops "
            "after the configured limit, and never saves screenshots."
        ),
        "timeout_seconds": 30,
        "spec": {
            "type": "function",
            "function": {
                "name": "watch_start",
                "description": (
                    "Start an explicit, visible watch session for gaming or app "
                    "companionship. Looks at the screen once every interval, keeps "
                    "only short text observations in memory, and stops automatically "
                    "after the limit (30 minutes maximum). Never continuous recording."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interval_seconds": {
                            "type": "integer",
                            "description": "Seconds between looks, 10 to 60; default from Settings.",
                        },
                        "minutes": {
                            "type": "integer",
                            "description": "Session limit in minutes, 1 to 30; default from Settings.",
                        },
                        "game_only": {
                            "type": "boolean",
                            "description": "Keep only looks where a game is detected.",
                        },
                    },
                },
            },
        },
        "fn": watch_start,
    },
    {
        "name": "watch_stop",
        "confirm": False,
        "silent": True,
        "spec": {
            "type": "function",
            "function": {
                "name": "watch_stop",
                "description": (
                    "Stop the current watch session immediately and return a short "
                    "in-memory summary. Nothing was saved."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "fn": watch_stop,
    },
    {
        "name": "watch_status",
        "confirm": False,
        "spec": {
            "type": "function",
            "function": {
                "name": "watch_status",
                "description": (
                    "Report whether a watch session is running, how long is left, "
                    "and the latest observation. Read-only."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "fn": watch_status,
    },
    {
        "name": "watch_observe",
        "confirm": True,
        "confirm_message": (
            "Allow Himari to take one local look at the screen and read the visible "
            "text? The screenshot is discarded immediately."
        ),
        "timeout_seconds": 30,
        "spec": {
            "type": "function",
            "function": {
                "name": "watch_observe",
                "description": (
                    "Take one additional look right now, inside a running watch "
                    "session or as a single opt-in look. Reads local OCR text and "
                    "window titles; the image is discarded and nothing is saved."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "fn": watch_observe,
    },
]
