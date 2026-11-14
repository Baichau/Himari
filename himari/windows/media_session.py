"""Read and control the active Windows media session.

Windows exposes the currently playing track (title, artist, album, playback
state) for media apps such as Spotify. This is the only trustworthy local way
to verify that a requested song is actually playing, so the music tools use it
instead of assuming a launched app is enough.
"""

import asyncio
import logging
from dataclasses import dataclass

log = logging.getLogger("himari.windows.media")

REQUEST_TIMEOUT_SECONDS = 5.0

# The WinRT projection is imported on first use, never at module import:
# loading it before Qt's DLLs crashes with an access violation on some
# machines, and the app may import this module before the UI starts.
_SessionManager = None
_import_error = None


def _session_manager():
    global _SessionManager, _import_error
    if _SessionManager is not None or _import_error is not None:
        return _SessionManager
    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as manager,
        )
    except Exception as exc:  # pragma: no cover - needs the package to be missing
        _import_error = exc
        return None
    _SessionManager = manager
    return _SessionManager


def _package_installed():
    try:
        from importlib.metadata import version

        version("winrt-Windows-Media-Control")
        return True
    except Exception:
        return False


class MediaSessionError(RuntimeError):
    """Raised when the Windows media session cannot be read or controlled."""


@dataclass(frozen=True)
class NowPlaying:
    app: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    playing: bool = False
    position_seconds: float = 0.0
    duration_seconds: float = 0.0

    @property
    def label(self):
        if self.title and self.artist:
            return f"{self.title} — {self.artist}"
        return self.title or self.artist or "Nothing playing"

    def to_dict(self):
        return {
            "app": self.app,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "playing": self.playing,
            "position_seconds": round(self.position_seconds, 1),
            "duration_seconds": round(self.duration_seconds, 1),
            "label": self.label,
        }


def available():
    if _SessionManager is not None:
        return True
    if _import_error is not None:
        return False
    return _package_installed()


def _run(coro, timeout=REQUEST_TIMEOUT_SECONDS):
    if _session_manager() is None:
        coro.close()
        raise MediaSessionError(
            "Windows media session support needs the 'winrt-Windows.Media.Control' "
            "package. Install it with: pip install winrt-Windows.Media.Control"
        )

    async def bounded():
        return await asyncio.wait_for(coro, timeout)

    try:
        return asyncio.run(bounded())
    except asyncio.TimeoutError as exc:
        raise MediaSessionError("Windows did not answer the media request in time.") from exc
    except RuntimeError as exc:
        # A loop is already running on this thread (for example inside an app).
        raise MediaSessionError(f"Could not use the Windows media session: {exc}") from exc


def _playback_status_name(info):
    status = getattr(info, "playback_status", None)
    name = getattr(status, "name", "")
    if name:
        return str(name).casefold()
    try:
        return "playing" if int(status) == 4 else "paused"
    except (TypeError, ValueError):
        return ""


async def _read_session(session):
    props = await session.try_get_media_properties_async()
    timeline = None
    try:
        timeline = session.get_timeline_properties()
    except Exception:
        timeline = None
    info = None
    try:
        info = session.get_playback_info()
    except Exception:
        info = None
    status = _playback_status_name(info)
    position = 0.0
    duration = 0.0
    if timeline is not None:
        position = float(getattr(timeline, "position", 0) or 0)
        duration = float(getattr(timeline, "end_time", 0) or 0)
    return NowPlaying(
        app=str(getattr(session, "source_app_user_model_id", "") or ""),
        title=str(getattr(props, "title", "") or "").strip(),
        artist=str(getattr(props, "artist", "") or "").strip(),
        album=str(getattr(props, "album_title", "") or "").strip(),
        playing=status == "playing",
        position_seconds=position,
        duration_seconds=duration,
    )


async def _all_sessions():
    manager_class = _session_manager()
    if manager_class is None:
        raise MediaSessionError(
            "Windows media session support needs the 'winrt-Windows.Media.Control' "
            "package. Install it with: pip install winrt-Windows.Media.Control"
        )
    manager = await manager_class.request_async()
    sessions = []
    try:
        sessions = list(manager.get_sessions())
    except Exception:
        current = manager.get_current_session()
        if current is not None:
            sessions = [current]
    return sessions


def sessions():
    """Return every media session Windows knows about, current one first."""

    async def collect():
        manager_class = _session_manager()
        if manager_class is None:
            raise MediaSessionError(
                "Windows media session support needs the 'winrt-Windows.Media.Control' "
                "package. Install it with: pip install winrt-Windows.Media.Control"
            )
        manager = await manager_class.request_async()
        ordered = []
        current = manager.get_current_session()
        if current is not None:
            ordered.append(current)
        for session in manager.get_sessions():
            if not any(session is item for item in ordered):
                ordered.append(session)
        return [await _read_session(session) for session in ordered]

    try:
        return _run(collect())
    except MediaSessionError:
        raise
    except Exception as exc:
        raise MediaSessionError(f"Could not read Windows media sessions: {exc}") from exc


def now_playing(app_hint=None):
    """Return the current track, optionally restricted to one application."""
    hint = str(app_hint or "").strip().casefold()
    found = sessions()
    if hint:
        for item in found:
            if hint in item.app.casefold():
                return item
        return None
    return found[0] if found else None


def _session_matching(app_hint):
    async def select():
        for session in await _all_sessions():
            app = str(getattr(session, "source_app_user_model_id", "") or "")
            if not app_hint or app_hint.casefold() in app.casefold():
                return session
        return None

    return select()


async def _control(app_hint, method_name):
    session = await _session_matching(app_hint)
    if session is None:
        raise MediaSessionError(
            "There is no active media session"
            + (f" for {app_hint}." if app_hint else ".")
        )
    method = getattr(session, method_name, None)
    if method is None:
        raise MediaSessionError(f"This media app does not support {method_name}.")
    return bool(await method())


def play_pause(app_hint=None):
    try:
        return _run(_control(app_hint, "try_toggle_play_pause_async"))
    except MediaSessionError:
        raise
    except Exception as exc:
        raise MediaSessionError(f"Could not toggle playback: {exc}") from exc


def next_track(app_hint=None):
    try:
        return _run(_control(app_hint, "try_skip_next_async"))
    except MediaSessionError:
        raise
    except Exception as exc:
        raise MediaSessionError(f"Could not skip to the next track: {exc}") from exc


def previous_track(app_hint=None):
    try:
        return _run(_control(app_hint, "try_skip_previous_async"))
    except MediaSessionError:
        raise
    except Exception as exc:
        raise MediaSessionError(f"Could not go to the previous track: {exc}") from exc


def stop(app_hint=None):
    try:
        return _run(_control(app_hint, "try_stop_async"))
    except MediaSessionError:
        raise
    except Exception as exc:
        raise MediaSessionError(f"Could not stop playback: {exc}") from exc
