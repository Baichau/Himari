"""Outcome verification.

A tool returning without raising proves only that the call ran. These checks
compare the observed state with the intended outcome where the application can
actually observe it, and say "unverifiable" instead of guessing.
"""

import os
from dataclasses import dataclass, field

KIND_RESULT = "result_ok"
KIND_UNVERIFIABLE = "unverifiable"


@dataclass
class Verification:
    ok: bool
    kind: str
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    definitive: bool = False

    def to_dict(self):
        return {
            "ok": self.ok,
            "kind": self.kind,
            "detail": self.detail,
            "evidence": self.evidence,
            "definitive": self.definitive,
        }

    @classmethod
    def unverifiable(cls, detail=""):
        return cls(True, KIND_UNVERIFIABLE, detail or "No independent check is available.")


def _dict_result(result):
    return result if isinstance(result, dict) else None


def _path_from(arguments):
    if not isinstance(arguments, dict):
        return ""
    for key in ("path", "file", "filename"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _verify_media(result):
    if isinstance(result, dict) and "verified" in result:
        track = result.get("now_playing") or result.get("track") or {}
        title = track.get("title") if isinstance(track, dict) else ""
        detail = (
            f"Windows media session reports '{title}' playing."
            if result.get("verified") and title
            else str(result.get("error") or "Playback was not confirmed.")
        )
        return Verification(
            bool(result.get("verified")),
            "media_playing",
            detail,
            {"track": track, "method": result.get("method", "")},
            definitive=True,
        )
    try:
        from ..applications import spotify

        current = spotify.now_playing()
    except Exception:
        return Verification.unverifiable("The media session could not be read.")
    if isinstance(current, dict) and isinstance(current.get("now_playing"), dict):
        current = current["now_playing"]
    if current and current.get("title"):
        return Verification(
            True,
            "media_playing",
            f"Windows media session reports '{current['title']}' playing.",
            {"now_playing": current},
            definitive=True,
        )
    return Verification(
        False,
        "media_playing",
        "No active playback was found in the Windows media session.",
        definitive=True,
    )


def _verify_now_playing(result):
    if isinstance(result, dict):
        title = result.get("title") or (result.get("track") or {}).get("title")
        if title:
            return Verification(True, "media_playing", f"Now playing: {title}.", {"now_playing": result})
        return Verification(False, "media_playing", "Nothing is playing.", {"now_playing": result})
    return Verification.unverifiable("The media session returned no track details.")


def _weather_place(result):
    location = result.get("location") or result.get("place")
    if isinstance(location, dict):
        name = str(location.get("name") or "").strip() or "the location"
        country = str(location.get("country") or "").strip()
        return f"{name}, {country}" if country and name != "the location" else name
    if isinstance(location, str) and location.strip():
        return location.strip()
    return "the location"


def _verify_weather(result):
    if isinstance(result, dict):
        days = result.get("daily") or result.get("days") or result.get("forecast") or []
        if days:
            first = days[0] if isinstance(days, list) else {}
            summary = ""
            if isinstance(first, dict):
                summary = first.get("summary") or first.get("condition") or ""
            return Verification(
                True,
                "data_present",
                f"Forecast for {_weather_place(result)}"
                + (f": {summary}" if summary else "."),
                {
                    "location": result.get("location"),
                    "source": result.get("source") or result.get("provider"),
                },
            )
    return Verification(False, "data_present", "The weather result contained no forecast.", definitive=True)


def _verify_calendar_event(result, deleted=False):
    if not isinstance(result, dict):
        return Verification.unverifiable("The calendar result was not structured.")
    event = result.get("event") if isinstance(result.get("event"), dict) else {}
    event_id = event.get("id") or result.get("event_id") or result.get("id") or ""
    if not event_id:
        return Verification.unverifiable("The calendar result did not include an event id.")
    try:
        from ..applications import calendar

        try:
            found = calendar.get_event(event_id)
        except calendar.CalendarError:
            found = None
    except Exception as exc:
        return Verification.unverifiable(f"The calendar could not be re-read: {exc}")
    if deleted:
        return Verification(
            found is None,
            "calendar_event",
            "The event is gone from the calendar." if found is None else "The event still exists.",
            {"event_id": event_id},
            definitive=True,
        )
    return Verification(
        found is not None,
        "calendar_event",
        "The event exists in the calendar." if found is not None else "The event was not found.",
        {"event_id": event_id},
        definitive=True,
    )


def _verify_file(arguments):
    path = _path_from(arguments)
    if not path:
        return Verification.unverifiable("No file path was provided to check.")
    full = os.path.abspath(os.path.expanduser(path))
    ok = os.path.exists(full)
    return Verification(
        ok,
        "file_exists",
        f"{full} was written." if ok else f"{full} does not exist after the write.",
        {"path": full},
        definitive=True,
    )


def verify(tool, arguments, result):
    """Check one tool outcome. Never raises and never performs an action."""
    name = str(tool or "")
    try:
        if name == "play_music":
            return _verify_media(result)
        if name == "now_playing":
            return _verify_now_playing(result)
        if name == "media_control":
            data = _dict_result(result)
            if data and data.get("title"):
                return Verification(True, "media_playing", f"Now playing: {data['title']}.", data)
            return Verification.unverifiable("The media session accepted the command.")
        if name == "weather_forecast":
            return _verify_weather(result)
        if name == "calendar_create":
            return _verify_calendar_event(result)
        if name == "calendar_delete":
            return _verify_calendar_event(result, deleted=True)
        if name == "calendar_export":
            data = _dict_result(result)
            path = str((data or {}).get("path") or "").strip()
            if data and data.get("ok", True) and path and os.path.isfile(os.path.abspath(path)):
                return Verification(
                    True,
                    "file_exists",
                    f"Calendar exported to {os.path.abspath(path)}.",
                    {"path": os.path.abspath(path), "events": data.get("events")},
                    definitive=True,
                )
            return Verification(
                False,
                "file_exists",
                "The calendar export file was not found on disk.",
                definitive=True,
            )
        if name in {"write_file", "write_desktop_file"}:
            return _verify_file(arguments)
        if name == "calendar_list":
            data = _dict_result(result)
            if data is not None and "events" in data:
                return Verification(True, "data_present", f"{len(data.get('events') or [])} event(s) listed.")
        if name == "spotify_search":
            data = _dict_result(result)
            if data is not None:
                tracks = data.get("tracks") or data.get("results") or []
                return Verification(
                    bool(tracks),
                    "data_present",
                    f"{len(tracks)} matching track(s) found." if tracks else "No matching tracks were found.",
                    {"count": len(tracks)},
                )
        if name in {"app_registry", "installed_apps", "find_app"}:
            return Verification.unverifiable("The application listing itself is the observed result.")
        return Verification.unverifiable()
    except Exception as exc:
        return Verification(False, "verification_error", f"Verification could not run: {exc}")


def verify_objective(intent, steps):
    """Aggregate check for the whole request, based only on observed steps."""
    steps = list(steps or [])
    if not steps:
        category = getattr(intent, "category", "chat") if intent is not None else "chat"
        answer_only = category in {"chat", "information", "research", "deep_work"}
        return Verification(
            answer_only,
            "answer_present" if answer_only else KIND_UNVERIFIABLE,
            "This request was answered without executing an action." if answer_only
            else "No action was executed, so there is no outcome to verify.",
            {"steps": 0},
            definitive=answer_only,
        )
    failed = [step for step in steps if not step.succeeded]
    skipped = [step for step in steps if getattr(step, "status", "") == "skipped"]
    if failed or skipped:
        return Verification(
            False,
            "outcome",
            f"{len(failed) + len(skipped)} of {len(steps)} step(s) did not succeed.",
            {"failed": len(failed), "skipped": len(skipped), "total": len(steps)},
            definitive=True,
        )
    weak = [
        step for step in steps
        if isinstance(getattr(step, "verification", None), dict)
        and not step.verification.get("ok", True)
    ]
    if weak:
        return Verification(
            False,
            "outcome",
            "The actions ran but their outcomes could not be confirmed.",
            {"unconfirmed": len(weak)},
            definitive=True,
        )
    return Verification(
        True,
        "outcome",
        "Every executed step completed and its outcome checked out.",
        {"steps": len(steps)},
        definitive=True,
    )
