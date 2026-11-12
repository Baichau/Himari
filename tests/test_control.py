from unittest.mock import Mock

import pytest

from himari import db
from himari.control import (
    SettingsError,
    SettingsService,
    activity_rows,
    build_dashboard,
    diagnostics_summary,
    format_activity,
    format_dashboard,
    format_diagnostics,
    memory_rows,
    permission_rows,
    run_diagnostics,
    set_permission,
)
from himari.control import memory_view


BASE_CONFIG = {
    "ollama": {"host": "http://127.0.0.1:11434", "chat_model": "qwen3:8b"},
    "voice": {
        "stt_model": "large-v3-turbo",
        "tts_voice": "en_US-amy-medium",
        "push_to_talk_key": "f9",
        "wake_word_enabled": False,
        "recognition_language": "en",
    },
    "privacy": {"store_conversations": True, "auto_memory": True, "memory_enabled": True},
    "permissions": {
        "allow_open_app": True,
        "allow_open_url": False,
        "allow_read_file": True,
        "allow_write_file": False,
        "allow_screen_capture": False,
        "allow_browser_automation": False,
        "allow_run_command": False,
        "allowed_folders": ["C:/Users/me/Documents"],
    },
    "ui": {"theme": "dark", "font_size": 14},
}


def test_settings_update_preserves_unrelated_sections():
    saved = {}
    service = SettingsService(load_config=lambda: dict(BASE_CONFIG), save_config=saved.update)

    updated = service.update({
        "ollama": {"chat_model": "llama3.2:3b"},
        "permissions": {"allow_open_url": True},
    })

    assert updated["ollama"]["chat_model"] == "llama3.2:3b"
    assert updated["ollama"]["host"] == "http://127.0.0.1:11434"
    assert updated["permissions"]["allow_open_url"] is True
    assert updated["permissions"]["allowed_folders"] == ["C:/Users/me/Documents"]
    assert saved == updated


def test_settings_reject_unknown_and_invalid_values():
    service = SettingsService(load_config=lambda: dict(BASE_CONFIG), save_config=Mock())

    with pytest.raises(SettingsError):
        service.update({"unknown": {"x": 1}})
    with pytest.raises(SettingsError):
        service.update({"permissions": {"allow_open_url": "yes"}})
    with pytest.raises(SettingsError):
        service.update({"permissions": {"not_a_key": True}})
    with pytest.raises(SettingsError):
        service.update({"ollama": {"host": "localhost:11434"}})
    with pytest.raises(SettingsError):
        service.update({"voice": {"volume": 2}})

    service._save.assert_not_called()


def test_settings_do_not_weaken_run_command():
    service = SettingsService(load_config=lambda: dict(BASE_CONFIG), save_config=Mock())

    with pytest.raises(ValueError):
        set_permission("allow_run_command", True, service=service)


def test_permission_rows_report_current_state():
    config = {"permissions": {
        "allow_open_app": True,
        "allow_open_url": True,
        "allowed_folders": ["C:/Docs"],
    }}

    rows = permission_rows(config)
    by_key = {row["key"]: row for row in rows}

    assert by_key["allow_open_app"]["enabled"] is True
    assert by_key["allow_open_url"]["enabled"] is True
    assert by_key["allow_screen_capture"]["enabled"] is False
    assert by_key["allow_run_command"]["editable"] is False
    assert by_key["allowed_folders"]["enabled"] is True


def test_permission_rows_cover_vision_and_image_generation():
    rows = permission_rows({"permissions": {"allow_vision": True}})
    by_key = {row["key"]: row for row in rows}

    assert by_key["allow_vision"]["enabled"] is True
    assert "vision" in by_key["allow_vision"]["description"].lower()
    assert by_key["allow_image_generation"]["enabled"] is False
    assert "stable diffusion" in by_key["allow_image_generation"]["description"].lower()


def test_settings_accept_the_new_vision_and_image_keys():
    saved = {}
    service = SettingsService(load_config=lambda: dict(BASE_CONFIG), save_config=saved.update)

    service.update({
        "ollama": {"vision_model": "qwen2.5vl:3b", "vision_timeout_seconds": 300},
        "imagegen": {
            "base_url": "http://127.0.0.1:8080",
            "steps": 28,
            "width": 768,
            "height": 768,
        },
        "permissions": {"allow_vision": True, "allow_image_generation": True},
        "ui": {"chat_engine": "web"},
    })

    assert saved["ollama"]["vision_model"] == "qwen2.5vl:3b"
    assert saved["imagegen"]["base_url"] == "http://127.0.0.1:8080"
    assert saved["permissions"]["allow_image_generation"] is True
    assert saved["ui"]["chat_engine"] == "web"


def test_settings_reject_unknown_chat_engines_and_bad_image_urls():
    service = SettingsService(load_config=lambda: dict(BASE_CONFIG), save_config=Mock())

    with pytest.raises(SettingsError):
        service.update({"ui": {"chat_engine": "native"}})
    with pytest.raises(SettingsError):
        service.update({"imagegen": {"base_url": "127.0.0.1:8080"}})



def test_activity_rows_parse_arguments_and_format(monkeypatch):
    monkeypatch.setattr(db, "recent_actions", lambda limit=50: [{
        "id": "1",
        "tool": "read_file",
        "args": '{"path": "notes.txt"}',
        "result": "hello",
        "ts": 1_700_000_000,
        "approved": 1,
    }])

    rows = activity_rows()

    assert rows[0]["arguments"] == {"path": "notes.txt"}
    assert "read_file" in format_activity(rows[0])
    assert "allowed" in format_activity(rows[0])


def test_dashboard_snapshot_is_complete():
    snapshot = build_dashboard(
        config=BASE_CONFIG,
        model_status=lambda: (["qwen3:8b", "llama3.2:3b"], None),
        interactions={"state": "busy", "busy": True, "current_task": "open Spotify"},
        integration_loader=lambda: [{
            "name": "Spotify", "available": True, "running": False, "actions": ["open"],
        }],
        activity_limit=2,
    )

    assert snapshot["ollama"]["connected"] is True
    assert snapshot["ollama"]["model_installed"] is True
    assert snapshot["interaction"]["current_task"] == "open Spotify"
    assert "Open apps and games" in snapshot["enabled_capabilities"]
    assert snapshot["integrations"][0]["name"] == "Spotify"
    assert snapshot["memory"]["approved"] >= 0
    assert isinstance(snapshot["avatar"]["installed"], bool)

    text = format_dashboard(snapshot)
    assert "connected; qwen3:8b installed" in text
    assert "Interaction: busy" in text


def test_dashboard_reports_missing_model_and_unreachable_ollama():
    missing = build_dashboard(
        config=BASE_CONFIG,
        model_status=lambda: ([], None),
        integration_loader=lambda: [],
    )
    assert missing["ollama"]["model_installed"] is False
    assert "NOT installed" in format_dashboard(missing)

    error = build_dashboard(
        config=BASE_CONFIG,
        model_status=lambda: ([], "connection refused"),
        integration_loader=lambda: [],
    )
    assert error["ollama"]["connected"] is False
    assert "unreachable" in format_dashboard(error)


def test_memory_rows_filter_and_stats(monkeypatch, tmp_path):
    original_dir, original_db = db.APP_DIR, db.DB
    try:
        db.APP_DIR = tmp_path
        db.DB = tmp_path / "himari.db"
        db.add_memory("User prefers Russian", "user")
        db.add_memory("User likes tea", "user")
        db.add_memory("User uses VS Code", source="suggestion", approved=0)

        rows = memory_rows("russian")
        assert len(rows) == 1
        assert rows[0]["text"] == "User prefers Russian"
        assert memory_view.stats() == {"approved": 2, "suggestions": 1}
    finally:
        db.APP_DIR, db.DB = original_dir, original_db


def test_memory_approval_and_rejection(monkeypatch):
    suggestions = [{"id": "s1", "text": "Likes cats"}]
    added = []
    deleted = []

    monkeypatch.setattr(memory_view.db, "memory_suggestions", lambda limit=200: list(suggestions))
    def fake_add(text, source="user", approved=1):
        added.append((text, source, approved))
        suggestions.clear()
    monkeypatch.setattr(memory_view.db, "add_memory", fake_add)
    monkeypatch.setattr(memory_view.db, "delete_memory", deleted.append)

    assert memory_view.approve("s1") is True
    assert added == [("Likes cats", "user", 1)]
    assert deleted == []
    assert memory_view.approve("missing") is False

    memory_view.reject("s1")
    assert deleted == ["s1"]


def test_diagnostics_checks_are_fail_soft():
    checks = run_diagnostics(
        config=BASE_CONFIG,
        model_status=Mock(side_effect=RuntimeError("ollama down")),
        include_windows=False,
    )

    by_name = {item["name"]: item for item in checks}
    assert by_name["Python"]["ok"] is True
    assert by_name["Configuration"]["ok"] is True
    assert by_name["Ollama"]["ok"] is False
    assert "ollama down" in by_name["Ollama"]["detail"]
    assert diagnostics_summary(checks)["failed"] >= 1
    assert "[FAIL]" in format_diagnostics(checks)


def test_diagnostics_report_missing_model():
    checks = run_diagnostics(
        config=BASE_CONFIG,
        model_status=lambda: (["other"], None),
        include_windows=False,
    )

    ollama = next(item for item in checks if item["name"] == "Ollama")
    assert ollama["ok"] is False
    assert "ollama pull qwen3:8b" in ollama["detail"]


def test_diagnostics_report_the_vision_model_and_image_server():
    config = {
        **BASE_CONFIG,
        "ollama": {
            **BASE_CONFIG["ollama"],
            "vision_model": "qwen2.5vl:3b",
        },
        "imagegen": {"base_url": "http://127.0.0.1:8080"},
    }
    checks = run_diagnostics(
        config=config,
        model_status=lambda: (["qwen3:8b", "qwen2.5vl:3b"], None),
        image_probe=lambda url: (False, "No local image server answered."),
        include_windows=False,
    )

    by_name = {item["name"]: item for item in checks}
    assert by_name["Vision"]["ok"] is True
    assert "qwen2.5vl:3b" in by_name["Vision"]["detail"]
    assert by_name["Image generation"]["ok"] is False
    assert "No local image server" in by_name["Image generation"]["detail"]
    assert by_name["Chat rendering"]["ok"] is True
