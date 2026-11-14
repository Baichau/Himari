import json

import pytest

from himari.core.intent import (
    Intent,
    IntentEngine,
    brief,
    merge_model_intent,
    parse_intent_json,
    rules_intent,
)


def test_music_request_extracts_song_and_artist():
    intent = rules_intent("Play the song Blinding Lights by The Weeknd")
    assert intent.category == "music"
    assert intent.entities["query"] == "Blinding Lights"
    assert intent.entities["artist"] == "The Weeknd"
    assert intent.required_capabilities == ["play_music", "now_playing"]
    assert intent.requires_action is True


def test_music_control_commands_need_no_song():
    assert rules_intent("pause").entities.get("action") == "pause"
    assert rules_intent("skip this track").category == "music"
    assert rules_intent("what's playing right now?").required_capabilities == ["now_playing"]


def test_pronoun_song_requests_are_marked_for_context():
    intent = rules_intent("Play that song I was listening to yesterday")
    assert intent.category == "music"
    assert intent.ambiguity
    assert intent.context_references


def test_weather_requests_keep_the_day_and_place():
    intent = rules_intent("What's the weather in Paris tomorrow?")
    assert intent.category == "weather"
    assert intent.entities["day_focus"] == "tomorrow"
    assert intent.entities.get("location") == "Paris"
    assert intent.required_capabilities == ["weather_forecast"]


def test_calendar_request_gets_title_and_when():
    intent = rules_intent("Schedule a meeting tomorrow at 12 about the new project")
    assert intent.category == "calendar"
    assert intent.entities["when"] == "tomorrow at 12"
    assert intent.entities["action"] == "create"
    assert "project" in intent.entities["title"].casefold()
    assert intent.requires_action is True


def test_calendar_delete_and_list_are_distinguished():
    assert rules_intent("delete my 3pm event").entities["action"] == "delete"
    assert rules_intent("what's on my calendar tomorrow?").entities["action"] == "list"


def test_app_control_and_aliases_are_recognized():
    intent = rules_intent("Open the code editor")
    assert intent.category == "app_control"
    assert intent.entities["application"] == "code editor"

    qoder = rules_intent("Open Qoder")
    assert qoder.category == "app_control"
    assert qoder.target_application == "Qoder"


def test_opening_a_presentation_is_not_deep_work():
    assert rules_intent("open my presentation").category == "app_control"
    assert (
        rules_intent("build a business plan for a small software company").category
        == "deep_work"
    )


def test_development_work_is_detected_but_a_simple_open_is_not():
    assert rules_intent("inspect my project and fix the bug").category in {
        "development", "deep_work",
    }
    assert rules_intent("open VS Code").category == "app_control"


def test_reading_the_open_project_gets_the_project_tools():
    intent = rules_intent("read the files in my open VS Code project")

    assert intent.category == "development"
    for tool in ("list_project_files", "search_code", "read_file", "open_project"):
        assert tool in intent.required_capabilities


def test_plain_questions_stay_information_requests():
    intent = rules_intent("What is the capital of France?")
    assert intent.category == "information"
    assert intent.requires_action is False


def test_intent_validation_coerces_bad_values():
    intent = Intent(objective="x", category="nonsense", risk_level="extreme", confidence=9)
    intent.validate()
    assert intent.category == "chat"
    assert intent.risk_level == "medium"
    assert intent.confidence == 1.0


def test_parse_intent_json_tolerates_fences_and_leading_prose():
    payload = {"objective": "play", "category": "music", "steps": [{"id": 1}]}
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    assert parse_intent_json(fenced) == payload
    assert parse_intent_json("Sure: " + json.dumps(payload)) == payload
    with pytest.raises(ValueError):
        parse_intent_json("no json here")


def test_model_intent_merges_without_losing_rules():
    base = rules_intent("Play Blinding Lights by The Weeknd")
    merged = merge_model_intent(base, {
        "objective": "Play Blinding Lights",
        "category": "music",
        "entities": {"query": "Ignored duplicate", "album": "After Hours"},
        "ambiguity": ["which version"],
        "confidence": 0.95,
    })
    assert merged.entities["query"] == "Blinding Lights"
    assert merged.entities["album"] == "After Hours"
    assert "which version" in merged.ambiguity
    assert merged.source == "hybrid"
    assert merged.confidence == 0.95


def test_engine_uses_the_model_only_when_asked():
    calls = []
    engine = IntentEngine(model_call=lambda prompt: calls.append(prompt) or '{"category":"weather"}')

    direct = engine.understand("What's the weather?", use_model=False)
    assert calls == []
    assert direct.category == "weather"

    refined = engine.understand("What's the weather?", use_model=True)
    assert calls
    assert refined.source == "hybrid"


def test_brief_is_a_short_human_line():
    text = brief(rules_intent("Play Blinding Lights by The Weeknd"))
    assert "music" in text
    assert "Blinding Lights" in text
