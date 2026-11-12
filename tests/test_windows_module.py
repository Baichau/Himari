import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from himari.windows import (
    AmbiguousAppError,
    AppInfo,
    AppNotFoundError,
    WindowInfo,
    close_app,
    find_app,
    installed_apps,
    launch_app,
    list_windows,
    request_window_close,
    running_processes,
)
from himari.windows import apps, enumeration, launch, processes

ALLOWED = {"permissions": {"allow_open_app": True}}
DENIED = {"permissions": {"allow_open_app": False}}


@pytest.fixture(autouse=True)
def _clear_discovery_cache():
    apps._CACHE = None
    yield
    apps._CACHE = None


def _isolate_discovery(monkeypatch, start_menu=(), registry=(), store=()):
    monkeypatch.setattr(apps, "_start_menu_apps", lambda: list(start_menu))
    monkeypatch.setattr(apps, "_registry_apps", lambda: list(registry))
    monkeypatch.setattr(apps, "_store_apps", lambda: list(store))


def test_installed_apps_collects_start_menu_shortcuts(tmp_path, monkeypatch):
    programs = tmp_path / "Programs"
    (programs / "Tools").mkdir(parents=True)
    chrome = programs / "Google Chrome.lnk"
    nested = programs / "Tools" / "Utility.lnk"
    chrome.write_bytes(b"shortcut")
    nested.write_bytes(b"shortcut")
    monkeypatch.setattr(apps, "_start_menu_roots", lambda: [programs, tmp_path / "missing"])
    _isolate_discovery(monkeypatch, start_menu=[
        AppInfo("Google Chrome", str(chrome), "start_menu"),
        AppInfo("Utility", str(nested), "start_menu"),
    ])

    result = installed_apps()

    assert AppInfo("Google Chrome", str(chrome), "start_menu") in result
    assert AppInfo("Utility", str(nested), "start_menu") in result


def test_start_menu_scan_reads_lnk_files_recursively(tmp_path, monkeypatch):
    programs = tmp_path / "Programs"
    (programs / "Folder").mkdir(parents=True)
    (programs / "Spotify.lnk").write_bytes(b"lnk")
    (programs / "Folder" / "Deep App.lnk").write_bytes(b"lnk")
    (programs / "ignore.txt").write_text("not a shortcut", encoding="utf-8")
    monkeypatch.setattr(apps, "_start_menu_roots", lambda: [programs])

    result = apps._start_menu_apps()

    assert {app.name for app in result} == {"Spotify", "Deep App"}
    assert all(app.source == "start_menu" for app in result)
    assert all(app.target.endswith(".lnk") for app in result)


def test_installed_apps_deduplicates_identical_entries(monkeypatch):
    duplicate = AppInfo("Spotify", "spotify:", "store")
    _isolate_discovery(
        monkeypatch,
        start_menu=[duplicate, duplicate],
        registry=[AppInfo("Spotify", "spotify:", "registry")],
        store=[AppInfo("Spotify", "other-target", "store")],
    )

    result = installed_apps()

    assert len(result) == 2
    assert sum(app.name == "Spotify" for app in result) == 2


def test_registry_apps_reads_app_paths(monkeypatch):
    class FakeKey:
        def __init__(self, subkeys=(), value=None):
            self.subkeys = list(subkeys)
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    root = FakeKey(subkeys=["chrome.exe", "missing.exe"])
    chrome = FakeKey(value=r"%ProgramFiles%\Google\Chrome\Application\chrome.exe")
    missing = FakeKey(value=None)

    def open_key(hive, key, reserved=0, access=0):
        if isinstance(hive, int):
            return root
        return chrome if key == "chrome.exe" else missing

    def enum_key(key, index):
        if index < len(key.subkeys):
            return key.subkeys[index]
        raise OSError("no more subkeys")

    def query_value(key, name):
        if key.value is None:
            raise OSError("no default value")
        return key.value, 1

    fake_winreg = SimpleNamespace(
        HKEY_LOCAL_MACHINE=1,
        HKEY_CURRENT_USER=2,
        KEY_READ=0x20019,
        KEY_WOW64_64KEY=0x0100,
        KEY_WOW64_32KEY=0x0200,
        OpenKey=open_key,
        EnumKey=enum_key,
        QueryValueEx=query_value,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(apps, "os", SimpleNamespace(
        name="nt", environ=os.environ, path=os.path,
    ))

    result = apps._registry_apps()

    assert result, "registry discovery should return the chrome entry"
    assert all(app.name == "chrome" and app.source == "registry" for app in result)
    assert all("missing" not in app.name for app in result)
    assert all("%ProgramFiles%" not in app.target for app in result)


def test_store_apps_parses_get_startapps_json(monkeypatch):
    monkeypatch.setattr(apps, "os", SimpleNamespace(name="nt"))
    run = Mock(return_value=SimpleNamespace(
        returncode=0,
        stdout='[{"Name":"Spotify","AppID":"SpotifyAB.SpotifyMusic_zpdnekdrzrea0!App"}]',
    ))
    monkeypatch.setattr(apps.subprocess, "run", run)

    result = apps._store_apps()

    assert result == [AppInfo("Spotify", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!App", "store")]
    assert run.call_args.kwargs["timeout"] == apps.STORE_LOOKUP_TIMEOUT_SECONDS


def test_store_apps_handles_single_object_output(monkeypatch):
    monkeypatch.setattr(apps, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(apps.subprocess, "run", Mock(return_value=SimpleNamespace(
        returncode=0, stdout='{"Name":"Calculator","AppID":"Microsoft.Calc_8wekyb3d8bbwe!App"}',
    )))

    assert apps._store_apps() == [AppInfo("Calculator", "Microsoft.Calc_8wekyb3d8bbwe!App", "store")]


def test_store_apps_fails_soft_on_errors(monkeypatch):
    monkeypatch.setattr(apps, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(apps.subprocess, "run", Mock(return_value=SimpleNamespace(
        returncode=0, stdout="not json",
    )))
    assert apps._store_apps() == []
    monkeypatch.setattr(apps.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("cmd", 15)))
    assert apps._store_apps() == []
    monkeypatch.setattr(apps.subprocess, "run", Mock(side_effect=OSError("no powershell")))
    assert apps._store_apps() == []


def test_find_app_prefers_exact_matches(monkeypatch):
    chrome = AppInfo("Google Chrome", "chrome.lnk", "start_menu")
    canary = AppInfo("Chrome Canary", "canary.lnk", "start_menu")
    monkeypatch.setattr(apps, "installed_apps", lambda: [chrome, canary])

    assert find_app("google chrome") == [chrome]
    assert find_app("GOOGLE CHROME") == [chrome]
    assert find_app("chrome") == [chrome, canary]
    assert find_app("   ") == []
    assert find_app("nonexistent") == []


def test_find_app_returns_every_duplicate_name(monkeypatch):
    first = AppInfo("Spotify", "spotify.lnk", "start_menu")
    second = AppInfo("Spotify", "SpotifyAB!App", "store")
    monkeypatch.setattr(apps, "installed_apps", lambda: [first, second])

    assert find_app("Spotify") == [first, second]


def test_running_processes_maps_psutil_info(monkeypatch):
    class FakePsutil:
        NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        AccessDenied = type("AccessDenied", (Exception,), {})
        ZombieProcess = type("ZombieProcess", (Exception,), {})

        @staticmethod
        def process_iter(attrs):
            return [
                SimpleNamespace(info={"pid": 10, "name": "spotify.exe", "exe": "C:\\Spotify\\spotify.exe"}),
                SimpleNamespace(info={"pid": 20, "name": "protected.exe", "exe": None}),
            ]

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)

    result = running_processes()

    assert result[0] == processes.ProcessInfo(10, "spotify.exe", "C:\\Spotify\\spotify.exe")
    assert result[1] == processes.ProcessInfo(20, "protected.exe", None)


def test_running_processes_skips_inaccessible_processes(monkeypatch):
    class FakePsutil:
        NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        AccessDenied = type("AccessDenied", (Exception,), {})
        ZombieProcess = type("ZombieProcess", (Exception,), {})

        @staticmethod
        def process_iter(attrs):
            denied = Mock()
            type(denied).info = property(lambda self: (_ for _ in ()).throw(FakePsutil.AccessDenied()))
            return [denied, SimpleNamespace(info={"pid": 5, "name": "ok.exe", "exe": None})]

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)

    result = running_processes()

    assert [item.pid for item in result] == [5]


def test_list_windows_builds_structured_entries(monkeypatch):
    monkeypatch.setattr(enumeration, "_enum_raw_windows", lambda: [(11, "Spotify", 123)])
    monkeypatch.setattr(enumeration, "_process_name", lambda pid: "spotify.exe" if pid == 123 else "")

    assert list_windows() == [WindowInfo(hwnd=11, title="Spotify", pid=123, process_name="spotify.exe")]
    monkeypatch.setattr(enumeration, "_enum_raw_windows", lambda: [])
    assert list_windows() == []


@pytest.mark.skipif(os.name != "nt", reason="Windows-native enumeration")
def test_raw_enumeration_filters_invisible_and_untitled_windows(monkeypatch):
    import ctypes

    def enum_windows(callback, _lparam):
        for hwnd in (1, 2, 3):
            callback(hwnd, None)
        return True

    def get_text(hwnd, buffer, size):
        buffer.value = "Visible App"
        return len(buffer.value)

    def get_pid(hwnd, ref):
        ref._obj.value = 42
        return 1

    fake_user32 = SimpleNamespace(
        EnumWindows=enum_windows,
        IsWindowVisible=lambda hwnd: hwnd != 2,
        GetWindowTextLengthW=lambda hwnd: 11 if hwnd == 1 else 0,
        GetWindowTextW=get_text,
        GetWindowThreadProcessId=get_pid,
    )
    monkeypatch.setattr(enumeration, "_get_user32", lambda: fake_user32)

    assert enumeration._enum_raw_windows() == [(1, "Visible App", 42)]


def test_launch_requires_permission(monkeypatch):
    monkeypatch.setattr(launch, "load_config", lambda: DENIED)
    monkeypatch.setattr(launch, "find_app", Mock(side_effect=AssertionError("must not search")))

    with pytest.raises(PermissionError):
        launch_app("Spotify")


def test_launch_reports_unknown_application(monkeypatch):
    monkeypatch.setattr(launch, "load_config", lambda: ALLOWED)
    monkeypatch.setattr(launch, "find_app", lambda name: [])

    with pytest.raises(AppNotFoundError, match="matching 'MissingApp'"):
        launch_app("MissingApp")
    with pytest.raises(AppNotFoundError):
        launch_app("  ")


def test_launch_refuses_ambiguous_matches(monkeypatch):
    monkeypatch.setattr(launch, "load_config", lambda: ALLOWED)
    monkeypatch.setattr(launch, "find_app", lambda name: [
        AppInfo("Spotify", "spotify.lnk", "start_menu"),
        AppInfo("Spotify", "SpotifyAB!App", "store"),
    ])
    startfile = Mock()
    monkeypatch.setattr(launch.os, "startfile", startfile, raising=False)

    with pytest.raises(AmbiguousAppError) as excinfo:
        launch_app("Spotify")

    assert len(excinfo.value.candidates) == 2
    startfile.assert_not_called()


def test_launch_opens_a_start_menu_shortcut(tmp_path, monkeypatch):
    shortcut = tmp_path / "Google Chrome.lnk"
    shortcut.write_bytes(b"lnk")
    monkeypatch.setattr(launch, "load_config", lambda: ALLOWED)
    monkeypatch.setattr(launch, "find_app", lambda name: [AppInfo("Google Chrome", str(shortcut), "start_menu")])
    startfile = Mock()
    monkeypatch.setattr(launch.os, "startfile", startfile, raising=False)

    result = launch_app("Google Chrome")

    assert result["ok"] is True
    startfile.assert_called_once_with(str(shortcut))


def test_launch_store_app_uses_apps_folder_uri(monkeypatch):
    monkeypatch.setattr(launch, "load_config", lambda: ALLOWED)
    monkeypatch.setattr(launch, "find_app", lambda name: [AppInfo("Calculator", "Microsoft.Calc!App", "store")])
    startfile = Mock()
    monkeypatch.setattr(launch.os, "startfile", startfile, raising=False)

    result = launch_app("Calculator")

    assert result["ok"] is True
    startfile.assert_called_once_with("shell:AppsFolder\\Microsoft.Calc!App")


def test_launch_reports_uninstalled_registered_app(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "load_config", lambda: ALLOWED)
    monkeypatch.setattr(launch, "find_app", lambda name: [
        AppInfo("OldApp", str(tmp_path / "gone.exe"), "registry"),
    ])
    startfile = Mock()
    monkeypatch.setattr(launch.os, "startfile", startfile, raising=False)

    result = launch_app("OldApp")

    assert result["ok"] is False
    assert "missing" in result["message"]
    startfile.assert_not_called()


def test_launch_reports_os_errors(tmp_path, monkeypatch):
    shortcut = tmp_path / "App.lnk"
    shortcut.write_bytes(b"lnk")
    monkeypatch.setattr(launch, "load_config", lambda: ALLOWED)
    monkeypatch.setattr(launch, "find_app", lambda name: [AppInfo("App", str(shortcut), "start_menu")])
    monkeypatch.setattr(launch.os, "startfile", Mock(side_effect=OSError("access denied")), raising=False)

    result = launch_app("App")

    assert result["ok"] is False
    assert "access denied" in result["message"]


def test_close_requires_permission(monkeypatch):
    monkeypatch.setattr(launch, "load_config", lambda: DENIED)
    monkeypatch.setattr(launch, "list_windows", Mock(side_effect=AssertionError("must not enumerate")))

    with pytest.raises(PermissionError):
        close_app("Spotify")


def test_close_reports_no_matching_window(monkeypatch):
    monkeypatch.setattr(launch, "load_config", lambda: ALLOWED)
    monkeypatch.setattr(launch, "list_windows", lambda: [WindowInfo(1, "Editor", 5, "editor.exe")])

    with pytest.raises(AppNotFoundError, match="No open window"):
        close_app("Spotify")


def test_close_refuses_ambiguous_windows(monkeypatch):
    monkeypatch.setattr(launch, "load_config", lambda: ALLOWED)
    monkeypatch.setattr(launch, "list_windows", lambda: [
        WindowInfo(1, "Chrome - Tab One", 5, "chrome.exe"),
        WindowInfo(2, "Chrome - Tab Two", 5, "chrome.exe"),
    ])
    close_request = Mock()
    monkeypatch.setattr(launch, "request_window_close", close_request)

    with pytest.raises(AmbiguousAppError):
        close_app("chrome")

    close_request.assert_not_called()


def test_close_sends_one_graceful_close_request(monkeypatch):
    monkeypatch.setattr(launch, "load_config", lambda: ALLOWED)
    monkeypatch.setattr(launch, "list_windows", lambda: [WindowInfo(77, "Spotify", 5, "spotify.exe")])
    close_request = Mock()
    monkeypatch.setattr(launch, "request_window_close", close_request)

    result = close_app("Spotify")

    assert result["ok"] is True
    assert "save changes" in result["message"]
    close_request.assert_called_once_with(77)


def test_close_matches_by_process_name(monkeypatch):
    monkeypatch.setattr(launch, "load_config", lambda: ALLOWED)
    monkeypatch.setattr(launch, "list_windows", lambda: [
        WindowInfo(9, "Untitled - Document", 5, "editor.exe"),
    ])
    close_request = Mock()
    monkeypatch.setattr(launch, "request_window_close", close_request)

    result = close_app("editor")

    assert result["ok"] is True
    close_request.assert_called_once_with(9)


def test_close_reports_failed_close_request(monkeypatch):
    monkeypatch.setattr(launch, "load_config", lambda: ALLOWED)
    monkeypatch.setattr(launch, "list_windows", lambda: [WindowInfo(9, "App", 5, "app.exe")])
    monkeypatch.setattr(launch, "request_window_close", Mock(side_effect=OSError("window gone")))

    result = close_app("App")

    assert result["ok"] is False
    assert "window gone" in result["message"]


@pytest.mark.skipif(os.name != "nt", reason="Windows-native close request")
def test_request_window_close_posts_wm_close_only(monkeypatch):
    posted = []
    fake_user32 = SimpleNamespace(PostMessageW=lambda *args: posted.append(args) or 1)
    monkeypatch.setattr(enumeration, "_get_user32", lambda: fake_user32)

    assert request_window_close(99) is True
    assert posted == [(99, enumeration.WM_CLOSE, 0, 0)]

    monkeypatch.setattr(enumeration, "_get_user32", lambda: SimpleNamespace(PostMessageW=lambda *args: 0))
    with pytest.raises(OSError):
        request_window_close(99)