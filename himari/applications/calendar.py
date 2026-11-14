"""Local calendar stored in Himari's database.

Events live on this machine, are created only after approval, and can be
exported as a standard .ics file. Nothing is sent to an external service.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import db
from ..config import APP_DIR

DAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
DEFAULT_DURATION_MINUTES = 60
MIN_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 24 * 60


class CalendarError(ValueError):
    pass


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    uid: str
    title: str
    start: datetime
    end: datetime
    location: str = ""
    notes: str = ""
    attendees: str = ""

    def to_dict(self):
        return {
            "id": self.id,
            "uid": self.uid,
            "title": self.title,
            "start": self.start.isoformat(timespec="minutes"),
            "end": self.end.isoformat(timespec="minutes"),
            "duration_minutes": int((self.end - self.start).total_seconds() // 60),
            "location": self.location,
            "notes": self.notes,
            "attendees": self.attendees,
            "when": self.start.strftime("%A %d %B %Y at %H:%M"),
        }


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _localize(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=_local_tz())
    return value.astimezone(_local_tz())


def _time_from_match(hour_text, minute_text, meridiem):
    hour = int(hour_text)
    minute = int(minute_text or 0)
    if minute > 59 or hour > 23:
        raise CalendarError(f"'{hour_text}:{minute_text or '00'}' is not a valid time.")
    if meridiem:
        marker = meridiem.casefold()
        if hour == 12:
            hour = 0 if marker == "am" else 12
        elif marker == "pm":
            hour += 12
    if hour > 23:
        raise CalendarError("The time must be between 00:00 and 23:59.")
    return hour, minute


def parse_when(text, now=None, require_time=True):
    """Parse a natural-language or ISO start time into a local datetime."""
    value = str(text or "").strip()
    if not value:
        raise CalendarError("Tell me when the event should start.")
    now = _localize(now or datetime.now())

    for parser in (
        lambda item: datetime.fromisoformat(item.replace("Z", "+00:00")),
    ):
        try:
            return _localize(parser(value))
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H.%M", "%d.%m.%Y %H:%M"):
        try:
            return _localize(datetime.strptime(value, fmt))
        except ValueError:
            continue

    lowered = value.casefold()
    base_date = None
    if "day after tomorrow" in lowered:
        base_date = now.date() + timedelta(days=2)
    elif "tomorrow" in lowered:
        base_date = now.date() + timedelta(days=1)
    elif "today" in lowered or "tonight" in lowered:
        base_date = now.date()
    else:
        weekday_match = re.search(
            r"\b(next\s+|this\s+)?(" + "|".join(DAY_NAMES) + r")\b", lowered
        )
        if weekday_match:
            target = DAY_NAMES[weekday_match.group(2)]
            ahead = (target - now.weekday()) % 7
            if ahead == 0:
                ahead = 7
            base_date = now.date() + timedelta(days=ahead)

    relative = re.search(r"\bin\s+(\d+)\s*(minute|minutes|min|hour|hours|hrs?)\b", lowered)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        delta = timedelta(hours=amount) if unit.startswith(("hour", "hr")) else timedelta(minutes=amount)
        return _localize(now + delta)

    iso_date = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", lowered)
    if iso_date:
        base_date = datetime(
            int(iso_date.group(1)), int(iso_date.group(2)), int(iso_date.group(3))
        ).date()

    if base_date is None:
        base_date = now.date()

    hour = minute = None
    if "noon" in lowered:
        hour, minute = 12, 0
    elif "midnight" in lowered:
        hour, minute = 0, 0
    else:
        time_match = re.search(
            r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lowered
        )
        if time_match and (time_match.group(3) or ":" in (time_match.group(0) or "")):
            hour, minute = _time_from_match(
                time_match.group(1), time_match.group(2), time_match.group(3)
            )
        else:
            bare = re.search(r"\bat\s+(\d{1,2})\b", lowered)
            if bare:
                hour, minute = int(bare.group(1)), 0

    if hour is None:
        if require_time:
            raise CalendarError(
                "I need a start time as well as a date. Say, for example, "
                "'tomorrow at 12:00'."
            )
        hour, minute = 9, 0
    start = datetime.combine(base_date, datetime.min.time()).replace(hour=hour, minute=minute)
    return _localize(start)


def _clamp_duration(minutes):
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        value = DEFAULT_DURATION_MINUTES
    return max(MIN_DURATION_MINUTES, min(value, MAX_DURATION_MINUTES))


def _row_to_event(row):
    return CalendarEvent(
        id=str(row["id"]),
        uid=str(row["uid"]),
        title=str(row["title"]),
        start=_localize(datetime.fromisoformat(row["start_iso"])),
        end=_localize(datetime.fromisoformat(row["end_iso"])),
        location=str(row["location"] or ""),
        notes=str(row["notes"] or ""),
        attendees=str(row["attendees"] or ""),
    )


def create_event(title, start, duration_minutes=DEFAULT_DURATION_MINUTES, location="", notes="", attendees=""):
    """Create one local event and return it with any overlapping events."""
    clean_title = str(title or "").strip()
    if not clean_title:
        raise CalendarError("The event needs a title.")
    if len(clean_title) > 200:
        raise CalendarError("The event title is too long.")
    start_dt = parse_when(start) if not isinstance(start, datetime) else _localize(start)
    minutes = _clamp_duration(duration_minutes)
    end_dt = start_dt + timedelta(minutes=minutes)
    conflicts = list_events(start=start_dt, end=end_dt)
    event_id = uuid.uuid4().hex[:12]
    uid = f"himari-{event_id}@local"
    now = datetime.now().timestamp()
    with db.conn() as connection:
        connection.execute(
            "INSERT INTO calendar_events(id,uid,title,start_ts,end_ts,start_iso,end_iso,"
            "location,notes,attendees,created,updated) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                uid,
                clean_title,
                start_dt.timestamp(),
                end_dt.timestamp(),
                start_dt.isoformat(timespec="minutes"),
                end_dt.isoformat(timespec="minutes"),
                str(location or "").strip()[:300],
                str(notes or "").strip()[:4000],
                str(attendees or "").strip()[:500],
                now,
                now,
            ),
        )
    return {"event": get_event(event_id).to_dict(), "conflicts": [item.to_dict() for item in conflicts]}


def list_events(days=7, start=None, end=None):
    """List events between two local datetimes, or from now to ``days`` ahead."""
    now = _localize(datetime.now())
    if start is None:
        start_dt = now
    elif isinstance(start, str):
        start_dt = parse_when(start, require_time=False)
    else:
        start_dt = _localize(start)
    if end is None:
        try:
            span = max(1, min(int(days), 366))
        except (TypeError, ValueError):
            span = 7
        end_dt = start_dt + timedelta(days=span)
    elif isinstance(end, str):
        end_dt = parse_when(end, require_time=False)
    else:
        end_dt = _localize(end)
    with db.conn() as connection:
        rows = connection.execute(
            "SELECT * FROM calendar_events WHERE start_ts < ? AND end_ts > ? "
            "ORDER BY start_ts ASC",
            (end_dt.timestamp(), start_dt.timestamp()),
        ).fetchall()
    return [_row_to_event(row) for row in rows]


def get_event(event_id):
    key = str(event_id or "").strip()
    if not key:
        raise CalendarError("An event id is required.")
    with db.conn() as connection:
        row = connection.execute(
            "SELECT * FROM calendar_events WHERE id=? OR uid=?",
            (key, key),
        ).fetchone()
    if row is None:
        raise CalendarError(f"No calendar event matches '{key}'.")
    return _row_to_event(row)


def delete_event(event_id):
    event = get_event(event_id)
    with db.conn() as connection:
        connection.execute("DELETE FROM calendar_events WHERE id=?", (event.id,))
    return {"deleted": event.to_dict()}


def _ics_escape(value):
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _ics_time(value):
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold(line):
    if len(line) <= 75:
        return line
    parts = [line[:75]]
    rest = line[75:]
    while rest:
        parts.append(" " + rest[:74])
        rest = rest[74:]
    return "\r\n".join(parts)


def export_ics(path=None):
    """Write every event to an .ics file and return the path."""
    events = list_events(
        start=datetime.now() - timedelta(days=365 * 2),
        end=datetime.now() + timedelta(days=366 * 5),
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Himari//Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for event in events:
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event.uid}",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{_ics_time(event.start)}",
                f"DTEND:{_ics_time(event.end)}",
                _fold(f"SUMMARY:{_ics_escape(event.title)}"),
                _fold(f"DESCRIPTION:{_ics_escape(event.notes)}"),
                _fold(f"LOCATION:{_ics_escape(event.location)}"),
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    target = Path(path) if path else APP_DIR / "exports" / "himari-calendar.ics"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return {"path": str(target), "events": len(events)}


def format_event(event):
    return (
        f"{event.start.strftime('%a %d %b %Y %H:%M')}–{event.end.strftime('%H:%M')}: "
        f"{event.title}"
        + (f" at {event.location}" if event.location else "")
        + (f" (id {event.id})" if event.id else "")
    )


def format_events(events):
    if not events:
        return "No events in that period."
    return "\n".join(format_event(event) for event in events)
