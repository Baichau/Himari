import pytest

from himari.core import capabilities
from himari.core.capabilities import (
    CORE_TOOLS,
    CapabilityRegistry,
    wants_himari_browser,
)
from himari.core.intent import rules_intent


class _AllowAllPermissions(dict):
    def get(self, key, default=None):
        return True


def _config():
    return {"permissions": _AllowAllPermissions()}


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _tool(name):
    return {
        "name": name,
        "spec": {
            "type": "function",
            "function": {"name": name, "description": f"{name} description"},
        },
        "fn": lambda: None,
    }


@pytest.fixture
def registry(monkeypatch):
    from himari.applications import spotify

    monkeypatch.setattr(spotify, "installed", lambda: True)
    monkeypatch.setattr(spotify, "running", lambda: True)
    names = (
        "play_music",
        "spotify_search",
        "now_playing",
        "media_control",
        "weather_forecast",
        "calendar_list",
        "calendar_create",
        "calendar_delete",
        "open_app",
        "find_app",
        "active_window",
        "list_windows",
        "research_web",
        "write_desktop_file",
    )
    return CapabilityRegistry(
        tools=[_tool(name) for name in names], config_loader=_config
    )


def test_core_tools_are_always_available(registry):
    names = registry.names()
    assert set(CORE_TOOLS) <= set(names)


def test_music_intent_gets_playback_tools_not_calendar(registry):
    names = registry.names(rules_intent("Play Blinding Lights by The Weeknd"))

    assert "play_music" in names
    assert "now_playing" in names
    assert "calendar_create" not in names
    assert "weather_forecast" not in names


def test_weather_and_calendar_intents_select_their_own_tools(registry):
    weather = registry.names(rules_intent("What's the weather in Paris tomorrow?"))
    assert "weather_forecast" in weather
    assert "play_music" not in weather

    calendar = registry.names(
        rules_intent("Schedule a meeting tomorrow at 12 about the new project")
    )
    assert "calendar_create" in calendar
    assert "calendar_list" in calendar
    assert "weather_forecast" not in calendar


def _browser_registry():
    names = (
        "open_url",
        "search_web",
        "open_first_result",
        "search_youtube",
        "research_web",
        "browser_open",
        "browser_search",
        "browser_open_result",
        "browser_tabs",
        "browser_read",
        "browser_close",
        "open_app",
    )
    return CapabilityRegistry(tools=[_tool(name) for name in names], config_loader=_config)


def test_ordinary_web_requests_use_the_default_browser_only():
    reg = _browser_registry()

    names = reg.names(rules_intent("search the web for space news"))

    assert "open_url" in names
    assert "open_first_result" in names
    assert "search_web" in names
    assert not any(name.startswith("browser_") for name in names)


def test_explicit_himari_browser_requests_keep_browser_tools():
    reg = _browser_registry()
    intent = rules_intent("search for the latest space news in your browser")

    assert wants_himari_browser(intent)
    names = reg.names(intent)
    assert "browser_open" in names
    assert "browser_search" in names


def test_required_browser_capability_survives_the_default_browser_filter():
    from types import SimpleNamespace

    reg = _browser_registry()
    intent = SimpleNamespace(
        category="research", required_capabilities=["browser_tabs"], raw_text=""
    )

    names = reg.names(intent)

    assert "browser_tabs" in names


def test_wants_himari_browser_detects_tab_and_automation_requests():
    assert wants_himari_browser(None) is False
    assert wants_himari_browser(rules_intent("play a song on youtube")) is False
    assert wants_himari_browser(rules_intent("close the tab")) is True
    assert wants_himari_browser(rules_intent("switch to the next tab")) is True
    assert wants_himari_browser(rules_intent("use playwright to open it")) is True


def test_ui_tool_list_keeps_the_isolated_browser_opt_in():
    from himari import ui

    ordinary = [tool["name"] for tool in ui.tools_for_intent(rules_intent("watch a video about python"))]
    assert "open_url" in ordinary
    assert not any(name.startswith("browser_") for name in ordinary)

    explicit = [
        tool["name"]
        for tool in ui.tools_for_intent(rules_intent("show me search results in your browser"))
    ]
    assert "browser_search" in explicit


def test_required_capability_survives_an_unavailable_probe(monkeypatch):
    from himari.applications import spotify

    monkeypatch.setattr(spotify, "installed", lambda: False)
    monkeypatch.setattr(spotify, "running", lambda: False)
    tools = [_tool(name) for name in ("play_music", "now_playing", "open_app")]
    reg = CapabilityRegistry(tools=tools, config_loader=_config)

    names = reg.names(rules_intent("Play Blinding Lights by The Weeknd"))

    assert "play_music" in names
    assert reg.capability("play_music").availability == "unavailable"


def test_unavailable_optional_tools_are_hidden(monkeypatch):
    from himari.applications import spotify

    monkeypatch.setattr(spotify, "installed", lambda: False)
    monkeypatch.setattr(spotify, "running", lambda: False)
    tools = [
        _tool(name)
        for name in ("play_music", "now_playing", "spotify_search", "open_app")
    ]
    reg = CapabilityRegistry(tools=tools, config_loader=_config)

    names = reg.names(rules_intent("Play Blinding Lights by The Weeknd"))

    assert "play_music" in names
    assert "now_playing" in names
    assert "spotify_search" not in names


def test_availability_probes_are_cached_and_refreshed(monkeypatch, registry):
    clock = _Clock()
    calls = []
    original = registry._probe

    def counting_probe(tool, config):
        calls.append(tool)
        return original(tool, config)

    registry._clock = clock
    registry._probe = counting_probe

    first = registry.refresh_availability()
    registry.refresh_availability()
    assert len(calls) == len(first)

    clock.advance(capabilities.AVAILABILITY_TTL_SECONDS + 1)
    registry.refresh_availability()
    assert len(calls) == len(first) * 2


def test_environment_notes_explain_missing_playback_support(monkeypatch):
    from himari.applications import spotify

    monkeypatch.setattr(spotify, "installed", lambda: False)
    monkeypatch.setattr(spotify, "running", lambda: False)
    tools = [_tool(name) for name in ("play_music", "weather_forecast")]
    reg = CapabilityRegistry(tools=tools, config_loader=_config)
    reg.refresh_availability(force=True)

    notes = reg.environment_notes()

    assert any("play_music" in note for note in notes)
    assert not any("weather_forecast" in note for note in notes)


def test_prompt_block_renders_real_capabilities(registry):
    block = registry.prompt_block(rules_intent("What's the weather in Paris?"))

    assert "weather_forecast: weather_forecast description" in block
    assert "play_music" not in block


def test_disabled_permission_hides_an_optional_tool():
    class _DenyWrite(dict):
        def get(self, key, default=None):
            return key != "allow_write_file"

    tools = [_tool("open_app"), _tool("write_desktop_file")]
    reg = CapabilityRegistry(
        tools=tools, config_loader=lambda: {"permissions": _DenyWrite()}
    )

    names = reg.names(rules_intent("Save a note to a file on my desktop"))

    assert "write_desktop_file" not in names
    assert reg.capability("write_desktop_file").availability == "unavailable"


def test_information_requests_include_link_and_video_openers():
    from types import SimpleNamespace

    names = (
        "open_app",
        "find_app",
        "active_window",
        "list_windows",
        "media_control",
        "research_web",
        "open_url",
        "open_first_result",
        "open_video",
        "find_video",
    )
    reg = CapabilityRegistry(
        tools=[_tool(name) for name in names], config_loader=_config
    )
    intent = SimpleNamespace(
        category="information",
        required_capabilities=[],
        raw_text="can you play the first video",
    )

    selected = set(reg.names(intent))

    assert {"open_video", "open_first_result", "open_url", "find_video"} <= selected
