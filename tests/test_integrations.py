from unittest.mock import Mock

import pytest

from himari.integrations import (
    ChromeIntegration,
    DiscordIntegration,
    SpotifyIntegration,
    SteamIntegration,
    VSCodeIntegration,
    all_integrations,
    get_integration,
    integration_status,
)
from himari.integrations import base, chrome, spotify, steam, vscode
from himari.windows import AmbiguousAppError, AppInfo, ProcessInfo


@pytest.fixture(autouse=True)
def _allow_app_control(monkeypatch):
    monkeypatch.setattr(base, "integration_allowed", lambda: True)


def test_registry_exposes_the_common_interface():
    names = {integration.name for integration in all_integrations()}

    assert names == {"chrome", "spotify", "steam", "vscode", "discord"}
    assert get_integration("CHROME") is get_integration("chrome")
    assert get_integration("missing") is None
    for integration in all_integrations():
        assert callable(integration.is_available)
        assert callable(integration.is_running)
        assert {"open", "close"} <= set(integration.supported_actions())


def test_is_available_uses_windows_discovery(monkeypatch):
    monkeypatch.setattr(
        "himari.windows.find_app",
        lambda name: [AppInfo("Spotify", "spotify.lnk", "start_menu")] if name == "Spotify" else [],
    )

    assert SpotifyIntegration().is_available() is True
    assert DiscordIntegration().is_available() is False


def test_is_running_matches_process_names(monkeypatch):
    monkeypatch.setattr(
        "himari.windows.running_processes",
        lambda: [ProcessInfo(1, "Spotify.exe", None)],
    )

    assert SpotifyIntegration().is_running() is True
    assert ChromeIntegration().is_running() is False


def test_unsupported_actions_are_reported_honestly(monkeypatch):
    protocol = Mock(side_effect=AssertionError("must not act"))
    monkeypatch.setattr(spotify, "_open_protocol", protocol)

    result = SpotifyIntegration().execute("play", {"query": "a song"})

    assert result["ok"] is False
    assert "Unsupported action 'play'" in result["error"]
    protocol.assert_not_called()


def test_execute_respects_permissions(monkeypatch):
    monkeypatch.setattr(base, "integration_allowed", lambda: False)
    launch = Mock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr("himari.windows.launch_app", launch)

    result = ChromeIntegration().execute("open")

    assert result["ok"] is False
    assert "Permission denied" in result["error"]
    launch.assert_not_called()


def test_chrome_open_delegates_to_windows_module(monkeypatch):
    launch = Mock(return_value={"ok": True, "app": "Google Chrome", "message": "Opened Google Chrome."})
    monkeypatch.setattr("himari.windows.launch_app", launch)

    result = ChromeIntegration().execute("open")

    assert result["ok"] is True
    launch.assert_called_once_with("Google Chrome")


def test_chrome_open_url_validates_and_passes_arguments(tmp_path, monkeypatch):
    executable = tmp_path / "chrome.exe"
    executable.write_bytes(b"exe")
    monkeypatch.setattr(
        "himari.windows.find_app",
        lambda name: [AppInfo("chrome", str(executable), "registry")],
    )
    popen = Mock()
    monkeypatch.setattr(chrome.subprocess, "Popen", popen)

    result = ChromeIntegration().execute("open_url", {"url": "example.com"})

    assert result["ok"] is True
    popen.assert_called_once_with([str(executable), "https://example.com"])

    bad = ChromeIntegration().execute("open_url", {"url": "ftp://example.com"})
    assert bad["ok"] is False
    assert popen.call_count == 1


def test_spotify_open_prefers_the_protocol(monkeypatch):
    monkeypatch.setattr(spotify, "_open_protocol", Mock(return_value=True))
    launch = Mock(side_effect=AssertionError("protocol should win"))
    monkeypatch.setattr("himari.windows.launch_app", launch)

    assert SpotifyIntegration().execute("open")["ok"] is True
    launch.assert_not_called()


def test_spotify_search_does_not_claim_playback(monkeypatch):
    protocol = Mock(return_value=True)
    monkeypatch.setattr(spotify, "_open_protocol", protocol)

    result = SpotifyIntegration().execute("search", {"query": "song & artist"})

    assert result["ok"] is True
    assert "Select a result" in result["message"]
    protocol.assert_called_once_with("spotify:search:song%20%26%20artist")
    assert SpotifyIntegration().execute("search", {"query": " "})["ok"] is False
    monkeypatch.setattr(spotify, "_open_protocol", Mock(return_value=False))
    assert SpotifyIntegration().execute("search", {"query": "song"})["ok"] is False


def test_steam_launches_exact_installed_titles(monkeypatch):
    monkeypatch.setattr(steam, "_steam_games", lambda: [("stardew valley", "413150")])
    protocol = Mock(return_value=True)
    monkeypatch.setattr(steam, "_open_protocol", protocol)

    result = SteamIntegration().execute("launch_game", {"name": "Stardew Valley"})

    assert result["ok"] is True
    protocol.assert_called_once_with("steam://rungameid/413150")
    assert SteamIntegration().execute("launch_game", {"name": "Unknown Game"})["ok"] is False
    assert SteamIntegration().execute("launch_game", {})["ok"] is False


def test_steam_rejects_duplicate_titles(monkeypatch):
    monkeypatch.setattr(steam, "_steam_games", lambda: [("game", "1"), ("game", "2")])
    protocol = Mock()
    monkeypatch.setattr(steam, "_open_protocol", protocol)

    result = SteamIntegration().execute("launch_game", {"name": "Game"})

    assert result["ok"] is False
    protocol.assert_not_called()


def test_steam_lists_installed_games(monkeypatch):
    monkeypatch.setattr(steam, "_steam_games", lambda: [("b game", "2"), ("a game", "1"), ("b game", "3")])

    result = SteamIntegration().execute("list_games")

    assert result["ok"] is True
    assert result["games"] == ["a game", "b game"]


def test_vscode_opens_existing_project_folders(tmp_path, monkeypatch):
    executable = tmp_path / "Code.exe"
    executable.write_bytes(b"exe")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(
        "himari.windows.find_app",
        lambda name: [AppInfo("Visual Studio Code", str(executable), "registry")],
    )
    popen = Mock()
    monkeypatch.setattr(vscode.subprocess, "Popen", popen)

    result = VSCodeIntegration().execute("open_project", {"path": str(project)})

    assert result["ok"] is True
    popen.assert_called_once_with([str(executable), str(project)])
    assert VSCodeIntegration().execute("open_project", {"path": str(tmp_path / "missing")})["ok"] is False
    assert VSCodeIntegration().execute("open_project", {})["ok"] is False


def test_discord_reports_unimplemented_sends(monkeypatch):
    launch = Mock(return_value={"ok": True, "message": "Opened Discord."})
    monkeypatch.setattr("himari.windows.launch_app", launch)
    integration = DiscordIntegration()

    send = integration.execute("send_message", {"text": "hello"})
    opened = integration.execute("open")

    assert send["ok"] is False
    assert "Unsupported action" in send["error"]
    assert opened["ok"] is True


def test_ambiguous_launches_return_structured_errors(monkeypatch):
    monkeypatch.setattr(spotify, "_open_protocol", Mock(return_value=False))
    monkeypatch.setattr(
        "himari.windows.launch_app",
        Mock(side_effect=AmbiguousAppError("Spotify", ["Spotify (store)", "Spotify (start_menu)"])),
    )

    result = SpotifyIntegration().execute("open")

    assert result["ok"] is False
    assert "More than one application" in result["error"]


def test_integration_status_is_structured(monkeypatch):
    monkeypatch.setattr("himari.windows.find_app", lambda name: [])
    monkeypatch.setattr("himari.windows.running_processes", lambda: [])

    status = integration_status()

    assert len(status) == 5
    for entry in status:
        assert set(entry) == {"name", "available", "running", "actions"}
        assert entry["available"] is False
        assert entry["running"] is False
        assert "open" in entry["actions"]