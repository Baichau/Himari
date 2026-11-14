import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from himari.core.capabilities import registry
from himari.core.intent import rules_intent
from himari.memory import CATEGORIES
from himari.skills import coach, continuity, doctor, media, pair, watch
from himari.tools import TOOLS
from himari.security.policies import permission_key_for, tool_is_known
from himari.control.settings import SCHEMA


# ---- watch companion -------------------------------------------------

def test_detect_game_recognises_common_titles():
    assert watch.detect_game("VALORANT-Win64-Shipping.exe", "Valorant") == "Valorant"
    assert watch.detect_game("notepad.exe", "notes.txt") == ""


def test_watch_requires_both_permissions(monkeypatch):
    monkeypatch.setattr(watch, "permission", lambda key: False)
    session = watch.WatchSession()
    with pytest.raises(watch.WatchPermissionError):
        session.start()

    monkeypatch.setattr(watch, "permission", lambda key: key == "allow_watch_mode")
    with pytest.raises(watch.WatchPermissionError):
        session.start()


def test_watch_session_clamps_limits_and_keeps_observations_in_memory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(watch, "permission", lambda key: True)
    monkeypatch.setattr(watch.WatchSession, "_run", lambda self: None)
    scene = {
        "visible_text": ["Wave incoming", "Ultimate ready"],
        "application": "valorant.exe",
        "window_title": "Valorant",
        "ui_elements": [],
    }
    session = watch.WatchSession(scene_reader=lambda: scene, clock=lambda: 1000.0)
    status = session.start(interval_seconds=1, minutes=99)

    assert status["running"] is True
    assert status["interval_seconds"] == watch.MIN_INTERVAL_SECONDS
    assert status["limit_minutes"] == watch.MAX_MINUTES
    observation = session.capture(force=True)
    assert observation.game == "Valorant"
    assert "Wave incoming" in observation.visible_text
    assert session.status()["observations"] == 1
    assert "Wave incoming" in session.digest()

    stopped = session.stop("test")
    assert stopped["was_running"] is True
    assert session.status()["running"] is False
    assert list(tmp_path.iterdir()) == []


def test_watch_session_refuses_a_second_session(monkeypatch):
    monkeypatch.setattr(watch, "permission", lambda key: True)
    monkeypatch.setattr(watch.WatchSession, "_run", lambda self: None)
    session = watch.WatchSession(scene_reader=lambda: {}, clock=lambda: 1000.0)
    session.start()
    with pytest.raises(watch.WatchError):
        session.start()
    session.stop()


# ---- setup coach -----------------------------------------------------

def test_resolve_topic_accepts_aliases_and_defaults_to_spotify():
    assert coach.resolve_topic("how do I setup spotify") == "spotify"
    assert coach.resolve_topic("visual studio code") == "vscode"
    assert coach.resolve_topic("something unknown") == "spotify"


def test_playbook_reports_the_next_unfinished_step(monkeypatch):
    monkeypatch.setattr(coach, "_check", lambda key: (False, "not yet"))
    status = coach.playbook_status("voice", remember=[])
    assert status["topic"] == "voice"
    assert status["done"] == 0
    assert status["complete"] is False
    assert status["next_step"]["id"] == status["steps"][0]["id"]


def test_inspect_settings_masks_every_secret(monkeypatch):
    monkeypatch.setattr(
        coach,
        "_snapshot",
        lambda: {
            "spotify": {"client_id": "client-abc", "client_secret": "secret-xyz"},
            "ui": {"theme": "dark"},
        },
    )
    output = coach.inspect_settings()
    assert "client-abc" not in output
    assert "secret-xyz" not in output
    assert "configured" in output
    assert "dark" in output


def test_setup_guide_lists_steps_without_secrets(monkeypatch):
    monkeypatch.setattr(coach, "_check", lambda key: (True, "ready"))
    guide = coach.setup_guide("spotify")
    assert "Spotify" in guide
    assert "Client ID" in guide
    assert "secret-xyz" not in guide


# ---- system doctor ---------------------------------------------------

def test_doctor_is_blocked_without_the_permission(monkeypatch):
    monkeypatch.setattr(doctor, "permission", lambda key: False)
    assert "Permission denied" in doctor.inspect_system()
    assert "Permission denied" in doctor.diagnose_program("chrome")


def test_doctor_redacts_secret_looking_values():
    assert "super-secret" not in doctor._redact("token=super-secret")
    assert "<redacted>" in doctor._redact("password: hunter2")


def test_doctor_sums_up_recent_events():
    text = (
        "Log Name: System\n"
        "Source: AppModel-Runtime\n"
        "Level: Error\n"
        "Date: 2026-11-14 10:00:00\n"
        "Message: The app failed to start.\n\n"
        "Log Name: System\n"
        "Source: Disk\n"
        "Level: Warning\n"
        "Message: Disk is busy.\n\n"
    )
    summary = doctor._summarize_events(text, limit=5)
    assert summary[0]["source"] == "AppModel-Runtime"
    assert summary[1]["source"] == "Disk"


# ---- VS Code pair programmer -----------------------------------------

def test_uri_to_path_decodes_windows_editor_uris():
    path = pair._uri_to_path("file:///C:/Users/Ana%20Silva/app.py")
    assert path is not None
    assert path.name == "app.py"
    assert "Ana Silva" in str(path)


def test_title_parts_drops_the_editor_suffix():
    file_name, folder = pair._title_parts("app.py - webapp - Visual Studio Code")
    assert file_name == "app.py"
    assert folder == "webapp"


def test_propose_and_apply_change_write_only_after_a_diff(monkeypatch, tmp_path):
    target = tmp_path / "note.py"
    target.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(pair, "_editable_path", lambda value: Path(value))
    monkeypatch.setattr(
        pair, "_read_text", lambda value: {"path": target, "encoding": "utf-8", "content": target.read_text(encoding="utf-8")}
    )

    change = pair.propose_change(target, "value = 2\n")
    assert change["changed"] is True
    assert "-value = 1" in change["diff"]
    assert "+value = 2" in change["diff"]
    assert target.read_text(encoding="utf-8") == "value = 1\n"

    result = pair.apply_change(target, "value = 2\n")
    assert result["applied"] is True
    assert target.read_text(encoding="utf-8") == "value = 2\n"


# ---- media companion -------------------------------------------------

def test_video_id_reads_urls_and_ids():
    assert media.video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert media.video_id("https://youtu.be/dQw4w9WgXcQ?t=1") == "dQw4w9WgXcQ"
    assert media.video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert media.video_id("not a video") == ""


def test_media_parses_caption_tracks_and_cues():
    document = (
        '{"videoDetails":{"videoId":"dQw4w9WgXcQ","title":"A talk"},'
        '"captions":{"playerCaptionsTracklistRenderer":{"captionTracks":['
        '{"baseUrl":"https://captions.test/en","languageCode":"en"}]}}}'
    )
    assert media.page_title(document) == "A talk"
    assert media.caption_url(document) == "https://captions.test/en"
    cues = media.parse_timedtext(
        '<transcript><text start="1.2" dur="2">Hello &amp; welcome</text>'
        '<text start="65" dur="2">Second line</text></transcript>'
    )
    assert cues == ["[00:01] Hello & welcome", "[01:05] Second line"]


def test_youtube_transcript_reads_public_captions(monkeypatch):
    monkeypatch.setattr(media, "permission", lambda key: True)

    def fake_get(url, timeout=0):
        if "watch" in url:
            return (
                '{"videoDetails":{"videoId":"dQw4w9WgXcQ","title":"A talk"},'
                '"captions":{"playerCaptionsTracklistRenderer":{"captionTracks":['
                '{"baseUrl":"https://captions.test/en","languageCode":"en"}]}}}'
            )
        return '<transcript><text start="0">Welcome to the talk</text></transcript>'

    monkeypatch.setattr(media, "_http_get", fake_get)
    output = media.youtube_transcript("https://youtu.be/dQw4w9WgXcQ")
    assert "A talk" in output
    assert "Welcome to the talk" in output
    assert "Nothing was downloaded" in output


def test_youtube_transcript_is_blocked_without_web_research(monkeypatch):
    monkeypatch.setattr(media, "permission", lambda key: False)
    assert "Permission denied" in media.youtube_transcript("anything")


# ---- continuity ------------------------------------------------------

def test_remember_activity_uses_the_activity_category(monkeypatch):
    calls = []

    class FakeManager:
        def enabled(self):
            return True

        def add(self, text, category=None, project=None, source=None):
            calls.append((text, category, project, source))
            return "memory-id"

    monkeypatch.setattr(continuity, "_memory_manager", lambda: FakeManager())
    output = continuity.remember_activity("Was playing Minecraft", kind="gaming", project="Survival")
    assert "Remembered" in output
    assert calls[0][1] == "activity"
    assert calls[0][2] == "Survival"
    assert "Minecraft" in calls[0][0]


def test_remember_activity_reports_when_nothing_is_saved(monkeypatch):
    class FakeManager:
        def enabled(self):
            return True

        def add(self, *args, **kwargs):
            return None

    monkeypatch.setattr(continuity, "_memory_manager", lambda: FakeManager())
    assert "Nothing new was saved" in continuity.remember_activity("Repeated note")


def test_project_context_combines_project_editor_and_watch(monkeypatch, tmp_path):
    monkeypatch.setattr(continuity, "active_project", lambda: tmp_path)
    monkeypatch.setattr(continuity, "discover_workspaces", lambda: [tmp_path])
    monkeypatch.setattr(continuity, "_vscode_lines", lambda: ["VS Code active file: app.py"])
    monkeypatch.setattr(continuity, "_watch_lines", lambda: ["Watch session: not running."])
    monkeypatch.setattr(continuity, "_memory_lines", lambda: [])
    output = continuity.project_context()
    assert str(tmp_path) in output
    assert "VS Code active file: app.py" in output
    assert "read-only" in output


def test_activity_is_a_memory_category():
    assert "activity" in CATEGORIES


# ---- routing and registration ---------------------------------------

def test_new_intents_route_to_their_skills():
    cases = {
        "watch me play valorant and coach me": ("watch", "watch_start"),
        "stop watching": ("watch", "watch_stop"),
        "help me set up my spotify credentials": ("coach", "setup_guide"),
        "why is chrome so slow and crashing": ("diagnostics", "diagnose_program"),
        "read the file open in vs code and review my code": ("development", "vscode_read"),
        "summarize this youtube video https://youtu.be/dQw4w9WgXcQ": ("media", "youtube_transcript"),
        "remember that i was playing minecraft today": ("continuity", "remember_activity"),
        "what was i working on": ("continuity", "project_context"),
    }
    for text, (category, tool) in cases.items():
        intent = rules_intent(text)
        assert intent.category == category, text
        names = {entry["name"] for entry in registry().select(intent)}
        assert tool in names, (text, names)


def test_every_builtin_tool_is_known_and_has_a_valid_permission():
    permission_keys = set(SCHEMA["permissions"])
    for tool in TOOLS:
        name = tool["name"]
        assert tool_is_known(name), name
        key = permission_key_for(name)
        if key:
            assert key in permission_keys, (name, key)
        assert "spec" in tool and tool["spec"]["function"]["name"] == name


def test_new_permissions_and_watch_settings_are_in_the_schema():
    for key in (
        "allow_watch_mode",
        "allow_system_diagnostics",
        "allow_vscode_state",
        "allow_run_tests",
    ):
        assert key in SCHEMA["permissions"]
    assert "watch_interval_seconds" in SCHEMA["screen"]
    assert "watch_max_minutes" in SCHEMA["screen"]
