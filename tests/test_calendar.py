import sqlite3
from datetime import datetime, timedelta

import pytest

from himari.applications import calendar


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    path = tmp_path / "calendar.db"

    def connection():
        connect = sqlite3.connect(path)
        connect.row_factory = sqlite3.Row
        connect.executescript(
            """
            CREATE TABLE IF NOT EXISTS calendar_events(
                id TEXT PRIMARY KEY, uid TEXT, title TEXT, start_ts REAL, end_ts REAL,
                start_iso TEXT, end_iso TEXT, location TEXT, notes TEXT,
                attendees TEXT, created REAL, updated REAL
            );
            """
        )
        return connect

    monkeypatch.setattr(calendar.db, "conn", connection)
    return path


NOW = datetime(2026, 11, 13, 9, 30)  # a Friday


def test_parse_relative_dates_and_times():
    tomorrow_noon = calendar.parse_when("tomorrow at 12", now=NOW)
    assert tomorrow_noon.date().isoformat() == "2026-11-14"
    assert (tomorrow_noon.hour, tomorrow_noon.minute) == (12, 0)

    tonight = calendar.parse_when("tonight at 9pm", now=NOW)
    assert tonight.date().isoformat() == "2026-11-13"
    assert tonight.hour == 21

    next_friday = calendar.parse_when("friday at 3pm", now=NOW)
    assert next_friday.date().isoformat() == "2026-11-20"
    assert next_friday.hour == 15

    iso = calendar.parse_when("2026-12-01 08:15", now=NOW)
    assert iso.date().isoformat() == "2026-12-01"
    assert iso.hour == 8


def test_parse_relative_offsets_ignore_the_clock_text():
    later = calendar.parse_when("in 2 hours", now=NOW)
    assert later == calendar._localize(NOW + timedelta(hours=2))


def test_missing_or_invalid_times_are_rejected():
    with pytest.raises(calendar.CalendarError):
        calendar.parse_when("tomorrow", now=NOW)
    with pytest.raises(calendar.CalendarError):
        calendar.parse_when("tomorrow at 25:00", now=NOW)


def test_events_are_created_listed_and_deleted(isolated_db):
    start = calendar._localize(datetime(2026, 11, 14, 12, 0))
    created = calendar.create_event(
        "Project meeting",
        start,
        duration_minutes=45,
        location="Room 4",
        notes="Bring the plan",
    )
    event = created["event"]
    assert event["title"] == "Project meeting"
    assert event["duration_minutes"] == 45

    listed = calendar.list_events(
        start=start - timedelta(hours=1), end=start + timedelta(hours=2)
    )
    assert [item.title for item in listed] == ["Project meeting"]

    fetched = calendar.get_event(event["id"])
    assert fetched.location == "Room 4"

    calendar.delete_event(event["id"])
    with pytest.raises(calendar.CalendarError):
        calendar.get_event(event["id"])


def test_overlapping_events_are_reported_as_conflicts(isolated_db):
    start = calendar._localize(datetime(2026, 11, 14, 12, 0))
    calendar.create_event("First", start, duration_minutes=60)
    second = calendar.create_event("Second", start + timedelta(minutes=30), duration_minutes=60)
    assert [item["title"] for item in second["conflicts"]] == ["First"]


def test_duration_is_clamped(isolated_db):
    start = calendar._localize(datetime(2026, 11, 14, 12, 0))
    short = calendar.create_event("Quick", start, duration_minutes=0)["event"]
    assert short["duration_minutes"] == 5
    long = calendar.create_event("Long", start, duration_minutes=99999)["event"]
    assert long["duration_minutes"] == 24 * 60


def test_empty_titles_are_rejected(isolated_db):
    with pytest.raises(calendar.CalendarError):
        calendar.create_event("   ", datetime(2026, 11, 14, 12, 0))


def test_export_writes_utc_ics(isolated_db, tmp_path):
    start = calendar._localize(datetime(2026, 11, 14, 12, 0))
    calendar.create_event("Planning, review", start, duration_minutes=60)
    target = tmp_path / "calendar.ics"

    result = calendar.export_ics(target)

    assert result["events"] == 1
    text = target.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in text
    assert "SUMMARY:Planning\\, review" in text
    assert "DTSTART:" in text and text.split("DTSTART:")[1][:16].endswith("Z")
    assert text.rstrip().endswith("END:VCALENDAR")
