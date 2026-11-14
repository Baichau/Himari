from types import SimpleNamespace

import pytest

from himari.applications import discovery
from himari.windows.apps import AppInfo
from himari.windows.enumeration import WindowInfo


@pytest.fixture()
def fake_windows(monkeypatch):
    apps = [
        AppInfo("Visual Studio Code", r"C:\Apps\Code.exe", "start_menu"),
        AppInfo("Spotify", "shell:AppsFolder\\Spotify", "store"),
        AppInfo("Notepad", r"C:\Windows\notepad.exe", "start_menu"),
        AppInfo("Notepad++", r"C:\Apps\notepad++.exe", "start_menu"),
    ]

    def installed(refresh=False):
        return apps

    monkeypatch.setattr(discovery.windows, "installed_apps", installed)
    monkeypatch.setattr(
        discovery.windows, "running_processes",
        lambda: [SimpleNamespace(name="Code.exe", pid=10, exe=None)],
    )
    monkeypatch.setattr(
        discovery.windows, "list_windows",
        lambda: [WindowInfo(1, "main.py - Visual Studio Code", 10, "Code.exe")],
    )
    return apps


def test_registry_marks_running_and_inspectable(fake_windows):
    records = discovery.registry()
    code = next(item for item in records if item.name == "Visual Studio Code")
    assert code.running is True
    assert code.windows == ("main.py - Visual Studio Code",)
    assert code.support in {"inspectable", "integrated"}


def test_aliases_resolve_before_fuzzy_matching(fake_windows):
    candidates = discovery.resolve("code editor")
    assert [item.name for item in candidates] == ["Visual Studio Code"]
    assert candidates[0].alias == "code editor"


def test_describe_reports_ambiguity_instead_of_guessing(fake_windows):
    result = discovery.describe("note")
    assert result["ok"] is False
    assert result["ambiguous"] is True
    assert "Notepad" in result["candidates"]
    assert "Notepad++" in result["candidates"]


def test_describe_finds_windows_for_a_renamed_process(fake_windows):
    result = discovery.describe("Visual Studio Code")
    assert result["ok"] is True
    assert result["running"] is True
    assert result["windows"] == ["main.py - Visual Studio Code"]


def test_unknown_apps_return_no_candidates(fake_windows):
    assert discovery.resolve("totally unknown program") == []
    result = discovery.describe("totally unknown program")
    assert result["ok"] is False
    assert "No installed application" in result["error"]


def test_list_apps_puts_running_apps_first(fake_windows):
    result = discovery.list_apps(limit=10)
    assert result["ok"] is True
    assert result["applications"][0]["name"] == "Visual Studio Code"
