from unittest.mock import patch

from unittest.mock import MagicMock, Mock, patch
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from himari import db, tools


def test_read_file_rejects_path_outside_allowed_folders(tmp_path):
    allowed = tmp_path / "allowed"
    denied = tmp_path / "private.txt"
    allowed.mkdir()
    denied.write_text("private", encoding="utf-8")
    config = {"permissions": {
        "allow_read_file": True,
        "allowed_folders": [str(allowed)],
    }}
    with patch.object(tools, "load", return_value=config):
        assert "outside the configured allowed folders" in tools.read_file(str(denied))


def test_read_file_allows_configured_folder(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    text_file = allowed / "note.txt"
    text_file.write_text("hello", encoding="utf-8")
    config = {"permissions": {
        "allow_read_file": True,
        "allowed_folders": [str(allowed)],
    }}
    with patch.object(tools, "load", return_value=config):
        assert tools.read_file(str(text_file)) == "hello"


def test_read_file_rejects_symlink_escape(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    inside_link = allowed / "escape"
    target = outside / "secret.txt"
    target.write_text("secret", encoding="utf-8")

    try:
        inside_link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this system")

    config = {"permissions": {
        "allow_read_file": True,
        "allowed_folders": [str(allowed)],
    }}
    with patch.object(tools, "load", return_value=config):
        assert "outside the configured allowed folders" in tools.read_file(str(inside_link / "secret.txt"))


def test_write_file_stays_inside_allowed_folders(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    config = {"permissions": {
        "allow_write_file": True,
        "allowed_folders": [str(allowed)],
    }}
    with patch.object(tools, "load", return_value=config):
        result = tools.write_file(str(allowed / "note.txt"), "hello")
        denied = tools.write_file(str(tmp_path / "outside.txt"), "no")
    assert result.startswith("Wrote 5 chars")
    assert (allowed / "note.txt").read_text(encoding="utf-8") == "hello"
    assert "outside the configured allowed folders" in denied
    assert not (tmp_path / "outside.txt").exists()


def test_open_app_respects_permission():
    with patch.object(tools, "load", return_value={"permissions": {"allow_open_app": False}}):
        assert tools.open_app("Spotify") == "Permission denied: open_app"


def _skip_launch_checks(monkeypatch):
    monkeypatch.setattr(tools, "_focus_existing_app", lambda name: None)
    monkeypatch.setattr(tools, "_running_process_snapshot", lambda: None)


def test_open_app_focuses_an_existing_window(monkeypatch):
    from himari import windows

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(
        windows,
        "list_windows",
        lambda: [
            SimpleNamespace(
                hwnd=7, title="New Tab - Google Chrome", process_name="chrome.exe"
            )
        ],
    )
    focused = []
    monkeypatch.setattr(
        windows, "focus_window", lambda hwnd: focused.append(hwnd) or True
    )

    message = tools.open_app("chrome")

    assert message.startswith("Focused the existing window 'New Tab - Google Chrome'")
    assert focused == [7]


def test_open_app_prefers_the_process_over_a_title_lookalike(monkeypatch):
    from himari import windows

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(
        windows,
        "list_windows",
        lambda: [
            SimpleNamespace(hwnd=5, title="Chrome notes", process_name="notepad.exe"),
            SimpleNamespace(hwnd=6, title="New Tab", process_name="chrome.exe"),
        ],
    )
    focused = []
    monkeypatch.setattr(
        windows, "focus_window", lambda hwnd: focused.append(hwnd) or True
    )

    message = tools.open_app("chrome")

    assert "Chrome notes" not in message
    assert focused == [6]


def test_open_app_confirms_a_new_process_when_the_window_is_still_loading(monkeypatch):
    from himari import windows

    snapshots = iter(
        [{10: "explorer.exe"}, {10: "explorer.exe", 11: "chrome.exe"}]
    )
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(tools, "_focus_existing_app", lambda name: None)
    monkeypatch.setattr(tools, "_window_handles", lambda: {1})
    monkeypatch.setattr(tools, "_running_process_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(tools, "_LAUNCH_VERIFY_SECONDS", 0)
    monkeypatch.setattr(tools, "_open_app_request", lambda name: "Opened Chrome.")
    monkeypatch.setattr(
        windows,
        "list_windows",
        lambda: [SimpleNamespace(hwnd=1, title="Desktop", process_name="explorer.exe")],
    )

    message = tools.open_app("chrome")

    assert message.startswith("Started Chrome.")
    assert "chrome.exe process is running" in message


def test_open_minecraft_launcher_uses_start_menu_shortcut(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    _skip_launch_checks(monkeypatch)
    monkeypatch.setattr(tools, "_window_handles", lambda: None)
    monkeypatch.setattr(tools, "_start_menu_shortcut", lambda name: name == "Minecraft Launcher")
    monkeypatch.setattr(tools, "_start_menu_app_id", lambda app_id: pytest.fail("store fallback should not run"))

    assert tools.open_app("Minecraft Launcher") == "Opened Minecraft Launcher."


def test_open_minecraft_launcher_uses_store_app_when_shortcut_is_missing(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    _skip_launch_checks(monkeypatch)
    monkeypatch.setattr(tools, "_window_handles", lambda: None)
    monkeypatch.setattr(tools, "_start_menu_shortcut", lambda name: False)
    monkeypatch.setattr(tools, "_find_start_menu_app_id", lambda name: None)
    monkeypatch.setattr(
        tools,
        "_start_menu_app_id",
        lambda app_id: app_id == "Microsoft.4297127D64EC6_8wekyb3d8bbwe!Minecraft",
    )

    assert tools.open_app("Minecraft Launcher") == "Opened Minecraft Launcher."


def test_open_store_apps_by_the_registered_start_app_id(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    _skip_launch_checks(monkeypatch)
    monkeypatch.setattr(tools, "_window_handles", lambda: None)
    monkeypatch.setattr(tools, "_start_menu_shortcut", lambda name: False)
    monkeypatch.setattr(tools, "_find_start_menu_app_id", lambda name: "Store.App!Application")
    open_store_app = Mock(return_value=True)
    monkeypatch.setattr(tools, "_start_menu_app_id", open_store_app)

    assert tools.open_app("Minecraft Launcher") == "Opened Minecraft Launcher."
    open_store_app.assert_called_once_with("Store.App!Application")


def test_open_app_falls_back_to_the_installed_app_index(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    _skip_launch_checks(monkeypatch)
    monkeypatch.setattr(tools, "_window_handles", lambda: None)
    monkeypatch.setattr(tools, "_start_menu_shortcut", lambda name: False)
    monkeypatch.setattr(tools, "_find_start_menu_app_id", lambda name: None)
    monkeypatch.setattr(
        tools, "_discovered_app_message", lambda name: "Opened Visual Studio Code."
    )

    assert tools.open_app("Visual Studio") == "Opened Visual Studio Code."


def test_open_app_offers_candidates_when_the_name_is_ambiguous(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    _skip_launch_checks(monkeypatch)
    monkeypatch.setattr(tools, "_window_handles", lambda: None)
    monkeypatch.setattr(tools, "_start_menu_shortcut", lambda name: False)
    monkeypatch.setattr(tools, "_find_start_menu_app_id", lambda name: None)
    monkeypatch.setattr(
        tools,
        "_discovered_app_message",
        lambda name: "More than one installed app matches 'Visual Studio': Ask the user which one they mean.",
    )

    message = tools.open_app("Visual Studio")

    assert "More than one installed app matches" in message


def test_open_app_confirms_the_launch_when_a_new_window_appears(monkeypatch):
    from himari import windows

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    _skip_launch_checks(monkeypatch)
    monkeypatch.setattr(tools, "_window_handles", lambda: {1})
    monkeypatch.setattr(
        tools,
        "_open_app_request",
        lambda name: "Opened Minecraft Launcher.",
    )
    monkeypatch.setattr(
        windows,
        "list_windows",
        lambda: [
            SimpleNamespace(hwnd=1, title="Desktop", process_name="explorer.exe"),
            SimpleNamespace(hwnd=2, title="Minecraft Launcher", process_name="MinecraftLauncher.exe"),
        ],
    )

    message = tools.open_app("Minecraft Launcher")

    assert message.startswith("Opened Minecraft Launcher.")
    assert "Confirmed: the window 'Minecraft Launcher' is visible." in message


def test_open_app_reports_honestly_when_no_window_appears(monkeypatch):
    from himari import windows

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    _skip_launch_checks(monkeypatch)
    monkeypatch.setattr(tools, "_window_handles", lambda: {1})
    monkeypatch.setattr(tools, "_LAUNCH_VERIFY_SECONDS", 0)
    monkeypatch.setattr(
        tools,
        "_open_app_request",
        lambda name: "Opened Minecraft Launcher.",
    )
    monkeypatch.setattr(
        windows,
        "list_windows",
        lambda: [SimpleNamespace(hwnd=1, title="Desktop", process_name="explorer.exe")],
    )

    message = tools.open_app("Minecraft Launcher")

    assert message.startswith("Asked Windows to open Minecraft Launcher,")
    assert "no matching window or process appeared" in message


def test_open_app_skips_verification_for_browsers(monkeypatch):
    from himari import windows

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    _skip_launch_checks(monkeypatch)
    monkeypatch.setattr(tools, "_window_handles", lambda: {1})
    monkeypatch.setattr(
        tools,
        "_open_app_request",
        lambda name: "Opened the default browser.",
    )
    monkeypatch.setattr(
        windows,
        "list_windows",
        lambda: pytest.fail("browser launches should not be window-verified"),
    )

    assert tools.open_app("default browser") == "Opened the default browser."


def test_write_desktop_file_is_confined_to_a_text_filename(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(tools, "_desktop_directory", lambda: desktop)

    result = tools.write_desktop_file("notes", "Please remember this.")

    assert result == "Wrote 21 characters to the Desktop file notes.txt."
    assert (desktop / "notes.txt").read_text(encoding="utf-8") == "Please remember this."
    assert "without a folder path" in tools.write_desktop_file("..\\outside.txt", "no")
    assert not (tmp_path / "outside.txt").exists()


def test_write_desktop_file_is_registered_with_user_confirmation():
    handler = next(item for item in tools.TOOLS if item["name"] == "write_desktop_file")

    assert handler["confirm"] is True
    assert handler["fn"] is tools.write_desktop_file


def test_screen_capture_tool_requires_confirmation():
    handler = next(item for item in tools.TOOLS if item["name"] == "capture_screen_text")

    assert handler["confirm"] is True
    assert "discarded immediately" in handler["confirm_message"]


def test_launch_game_uses_exact_steam_title():
    with patch.object(tools, "_perm", return_value=True), \
         patch.object(tools, "_steam_games", return_value=[("stardew valley", "413150")]), \
         patch.object(tools, "_open_protocol", return_value=True) as open_protocol:
        assert tools.launch_game("Stardew Valley") == "Asked Steam to launch 'Stardew Valley'."
    open_protocol.assert_called_once_with("steam://rungameid/413150")


def test_spotify_search_does_not_claim_playback():
    with patch.object(tools, "_perm", return_value=True), \
         patch.object(tools, "_open_protocol", return_value=False), \
         patch.object(tools.webbrowser, "open", return_value=True) as open_browser:
        result = tools.play_music("A song & artist")
    assert "select a result" in result.lower()
    open_browser.assert_called_once_with("https://open.spotify.com/search/A%20song%20%26%20artist")


def test_web_search_encodes_query():
    with patch.object(tools, "open_url") as open_url:
        tools.search_web("song & artist")
    open_url.assert_called_once_with("https://www.google.com/search?q=song+%26+artist")


def _html_response(document, url="https://example.com/page", content_type="text/html"):
    response = MagicMock()
    response.status = 200
    response.headers.get_content_charset.return_value = "utf-8"
    response.headers.get_content_type.return_value = content_type
    response.read.return_value = document
    response.geturl.return_value = url
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_background_research_returns_sources_without_opening_a_browser(monkeypatch):
    document = (
        '<a class="result-link" href="https://duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fexample.com%2Fnews">Latest &amp; trusted story</a>'
        '<td class="result-snippet">Current <b>details</b> from today.</td>'
    ).encode()
    monkeypatch.setattr(tools, "_perm", lambda name: name == "allow_web_research")
    monkeypatch.setattr(tools, "load", lambda: {})
    monkeypatch.setattr(tools.webbrowser, "open", Mock(side_effect=AssertionError("browser must stay closed")))

    open_search = Mock(side_effect=lambda request, timeout: _html_response(document))
    monkeypatch.setattr(tools, "urlopen", open_search)

    result = tools.research_web("example topic")

    assert "Latest & trusted story" in result
    assert "Current details from today." in result
    assert "https://example.com/news" in result
    assert "Snippet (page could not be read)" in result
    search_calls = [
        call for call in open_search.call_args_list
        if "lite.duckduckgo.com" in call.args[0].full_url
    ]
    assert len(search_calls) == 1
    assert search_calls[0].kwargs["timeout"] == tools.WEB_RESEARCH_TIMEOUT_SECONDS


def test_background_research_reads_pages_and_cites_them(monkeypatch):
    search_document = (
        '<a class="result-link" href="https://duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fexample.com%2Fstory">Story headline</a>'
        '<td class="result-snippet">Short snippet only.</td>'
    ).encode()
    page_document = """
    <html><head>
      <title>Full story title</title>
      <meta name="description" content="A detailed description.">
      <meta property="article:published_time" content="2026-11-01T09:30:00Z">
      <script>window.secret = "never include";</script>
    </head><body>
      <nav>Navigation junk should vanish.</nav>
      <article>
        <h1>Full story title</h1>
        <p>This article explains the topic in far more detail than the search
        snippet ever could, including figures and background.</p>
        <p>Second paragraph with additional verified context.</p>
      </article>
    </body></html>
    """.encode()

    def open_page(request, timeout):
        if "lite.duckduckgo.com" in request.full_url:
            return _html_response(search_document)
        return _html_response(page_document, url="https://example.com/story")

    monkeypatch.setattr(tools, "_perm", lambda name: name == "allow_web_research")
    monkeypatch.setattr(tools, "load", lambda: {})
    monkeypatch.setattr(tools, "urlopen", Mock(side_effect=open_page))

    result = tools.research_web("example topic")

    assert "Full story title" in result
    assert "far more detail" in result
    assert "Published: 2026-11-01" in result
    assert "Source: https://example.com/story" in result
    assert "untrusted data" in result
    assert "never include" not in result
    assert "Navigation junk" not in result


def test_research_parser_skips_scripts_and_captures_metadata():
    parser = tools._ReadablePageParser()
    parser.feed(
        "<html><head><title> Page  Title </title>"
        '<meta name="description" content="Description here.">'
        '<meta property="article:published_time" content="2026-10-05T10:00:00Z">'
        "</head><body><style>.x{}</style><p>First line.</p>"
        "<script>ignore()</script><p>Second line.</p></body></html>"
    )
    parser.close()
    text = parser.text()

    assert parser.title == "Page Title"
    assert parser.published == "2026-10-05"
    assert "Description here." in text
    assert "First line." in text
    assert "Second line." in text
    assert "ignore()" not in text


def test_research_parser_collapses_duplicate_lines():
    parser = tools._ReadablePageParser()
    parser.feed("<p>Same line.</p><p>Same line.</p><p>Other.</p>")
    parser.close()

    assert parser.text().count("Same line.") == 1


def test_is_public_url_blocks_local_and_private_addresses():
    assert tools._is_public_url("https://example.com/page")
    assert not tools._is_public_url("http://localhost:8080/admin")
    assert not tools._is_public_url("http://127.0.0.1/")
    assert not tools._is_public_url("http://10.0.0.5/")
    assert not tools._is_public_url("http://192.168.1.1/")
    assert not tools._is_public_url("http://169.254.1.1/")
    assert not tools._is_public_url("http://[::1]/")
    assert not tools._is_public_url("file:///C:/Windows/win.ini")
    assert not tools._is_public_url("")
    assert not tools._is_public_url(None)
    assert not tools._is_public_url("http://printer.local/")


def test_fetch_page_refuses_private_url_without_network(monkeypatch):
    network = Mock(side_effect=AssertionError("private URL must not be fetched"))
    monkeypatch.setattr(tools, "urlopen", network)

    assert tools._fetch_page("http://127.0.0.1:11434/api/tags") is None
    network.assert_not_called()


def test_fetch_page_rejects_non_html_content(monkeypatch):
    monkeypatch.setattr(
        tools,
        "urlopen",
        Mock(side_effect=lambda request, timeout: _html_response(
            b"binary", content_type="application/pdf",
        )),
    )

    assert tools._fetch_page("https://example.com/file.pdf") is None


def test_research_queries_expand_for_fresh_and_comparison_intents():
    assert tools._research_queries("plain topic") == ["plain topic"]
    fresh = tools._research_queries("latest Windows release")
    assert len(fresh) == 2
    assert fresh[1].startswith("latest Windows release")
    compare = tools._research_queries("Ryzen vs Intel")
    assert len(compare) == 2
    assert compare[1].endswith("comparison")


def test_background_research_fails_closed_when_disabled(monkeypatch):
    open_search = Mock(side_effect=AssertionError("must not make a request"))
    monkeypatch.setattr(tools, "_perm", lambda name: False)
    monkeypatch.setattr(tools, "urlopen", open_search)

    assert "disabled in Settings" in tools.research_web("latest news")
    open_search.assert_not_called()


def test_background_research_reports_unavailable_internet(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(tools, "urlopen", Mock(side_effect=URLError(TimeoutError())))

    assert "internet may be unavailable" in tools.research_web("latest news")


def test_background_research_rejects_empty_or_oversized_queries(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    open_search = Mock(side_effect=AssertionError("invalid query must not make a request"))
    monkeypatch.setattr(tools, "urlopen", open_search)

    assert "Tell me what topic" in tools.research_web(" ")
    assert "too long" in tools.research_web("x" * (tools.WEB_RESEARCH_MAX_QUERY_LENGTH + 1))
    open_search.assert_not_called()


def test_youtube_search_uses_youtube_url():
    with patch.object(tools, "open_url") as open_url:
        tools.search_youtube("cat videos")
    open_url.assert_called_once_with("https://www.youtube.com/results?search_query=cat+videos")


def test_close_app_uses_window_title_match():
    with patch.object(tools, "_perm", return_value=True), \
         patch("pygetwindow.getAllTitles", return_value=["Spotify", "VS Code"]), \
         patch("pygetwindow.getWindowsWithTitle", return_value=[type("W", (), {"close": lambda self: None})()]):
        result = tools.close_app("spotify")
    assert "Closed 'Spotify'" in result


def test_close_app_requests_a_graceful_close(monkeypatch):
    class Window:
        def close(self):
            return None

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(tools, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(
        __import__("sys").modules,
        "pygetwindow",
        SimpleNamespace(
            getAllTitles=lambda: ["Spotify"],
            getWindowsWithTitle=lambda title: [Window()],
        ),
    )

    result = tools.close_app("Spotify")

    assert "normal close request" in result
    assert "save changes" in result


def test_media_control_is_permission_gated(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: False)

    assert "disabled in Settings" in tools.media_control("play_pause")


def test_media_control_rejects_unrecognized_actions(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)

    assert "Unsupported media action" in tools.media_control("launch_process")


def test_media_control_sends_a_windows_media_key(monkeypatch):
    sent = []
    user32 = SimpleNamespace(keybd_event=lambda *args: sent.append(args))
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(tools, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(__import__("sys").modules, "ctypes", SimpleNamespace(
        windll=SimpleNamespace(user32=user32),
    ))

    result = tools.media_control("next")

    assert sent == [(0xB0, 0, 0, 0), (0xB0, 0, 0x0002, 0)]
    assert "cannot confirm which app handled it" in result


def test_screen_capture_tool_respects_settings_permission(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: False)

    assert "disabled in Settings" in tools.capture_screen_text()


def test_active_window_detection_is_disabled_without_permission(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: False)

    assert "disabled in Settings" in tools.active_window()


def test_list_project_files_ignores_build_dirs(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("print('hi')", encoding="utf-8")
    (project / "dist").mkdir()
    (project / "dist" / "bundle.exe").write_text("binary", encoding="utf-8")
    config = {"permissions": {"allow_read_file": True, "allowed_folders": [str(project)]}}
    with patch.object(tools, "load", return_value=config):
        files = tools.list_project_files(str(project))
    assert "src/main.py" in files
    assert not any("dist/bundle.exe" == item for item in files)


def test_relevant_memories_prefers_matching_topics(tmp_path):
    original_dir = db.APP_DIR
    original_db = db.DB
    try:
        db.APP_DIR = tmp_path
        db.DB = tmp_path / "himari.db"
        db.add_memory("User prefers Russian language", "user")
        db.add_memory("User likes cats and tea", "user")
        results = db.relevant_memories("Russian language settings")
        assert any("Russian" in item["text"] for item in results)
        assert results[0]["text"] == "User prefers Russian language"
    finally:
        db.APP_DIR = original_dir
        db.DB = original_db


def test_summary_for_session_uses_recent_context(tmp_path):
    original_dir = db.APP_DIR
    original_db = db.DB
    try:
        db.APP_DIR = tmp_path
        db.DB = tmp_path / "himari.db"
        db.add_message("demo", "user", "I prefer Russian")
        db.add_message("demo", "assistant", "I will speak Russian")
        summary = db.summary_for_session("demo")
        assert "Russian" in summary or "I prefer Russian" in summary
    finally:
        db.APP_DIR = original_dir
        db.DB = original_db


def test_capture_screen_text_can_target_the_active_window(monkeypatch):
    import himari.screen as screen_module

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    analyze = Mock(return_value="visible text")
    monkeypatch.setattr(screen_module, "analyze", analyze)

    result = tools.capture_screen_text("active_window")

    assert "active window" in result
    assert "visible text" in result
    analyze.assert_called_once_with(monitor="primary", active_window=True)


def test_capture_screen_text_uses_a_requested_monitor(monkeypatch):
    import himari.screen as screen_module

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    analyze = Mock(return_value="visible text")
    monkeypatch.setattr(screen_module, "analyze", analyze)

    result = tools.capture_screen_text("configured", monitor=2)

    assert "monitor 2" in result
    analyze.assert_called_once_with(monitor="2", active_window=False)


def test_capture_screen_text_rejects_bad_targets_and_permissions(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: name == "allow_screen_capture")

    assert "Unknown capture target" in tools.capture_screen_text("everything")
    assert "active-window awareness" in tools.capture_screen_text("active_window")
    assert "whole number" in tools.capture_screen_text("configured", monitor="two")


def test_screen_scene_formats_structured_output(monkeypatch):
    import himari.perception.scene as scene_module

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(scene_module, "build_scene", Mock(return_value={
        "application": "editor.exe",
        "window_title": "Document - Editor",
        "visible_text": ["hello", "world"],
        "ui_elements": [{"type": "window", "title": "Editor", "process": "editor.exe"}],
        "timestamp": "2026-11-12T00:00:00+00:00",
    }))

    result = tools.screen_scene("active_window")

    assert "the active window" in result
    assert "Application: editor.exe" in result
    assert "Active window: Document - Editor" in result
    assert "hello" in result
    assert "Editor (editor.exe)" in result


def test_screen_scene_rejects_a_bad_region(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)

    assert "four integers" in tools.screen_scene(region=[1, 2, 3])


def test_screen_scene_is_registered_with_confirmation():
    entry = next(tool for tool in tools.TOOLS if tool["name"] == "screen_scene")

    assert entry["confirm"] is True
    assert entry["spec"]["function"]["parameters"]["properties"]["region"]["type"] == "array"


def test_installed_apps_tool_deduplicates_and_formats(monkeypatch):
    import himari.windows as windows_module

    app = lambda name: SimpleNamespace(name=name)
    monkeypatch.setattr(
        windows_module, "installed_apps",
        lambda: [app("Chrome"), app("chrome"), app("Notepad")],
    )

    result = tools.installed_apps_tool()

    assert "- Chrome" in result
    assert "- Notepad" in result
    assert result.count("Chrome") == 1


def test_list_windows_and_process_tools_respect_output_caps(monkeypatch):
    import himari.windows as windows_module

    monkeypatch.setattr(
        windows_module, "list_windows",
        lambda: [SimpleNamespace(title=f"Window {i}", process_name="app.exe") for i in range(70)],
    )
    monkeypatch.setattr(
        windows_module, "running_processes",
        lambda: [SimpleNamespace(name=f"proc{i}.exe", pid=i) for i in range(90)],
    )

    windows_output = tools.list_windows_tool()
    process_output = tools.running_processes_tool()

    assert "showing 60 of 70" in windows_output
    assert "showing 80 of 90" in process_output
    assert "proc89.exe" not in process_output


def test_list_windows_tool_filters_by_title_or_process(monkeypatch):
    import himari.windows as windows_module

    monkeypatch.setattr(
        windows_module, "list_windows",
        lambda: [
            SimpleNamespace(title="Spotify Premium", process_name="Spotify.exe"),
            SimpleNamespace(title="Notepad", process_name="notepad.exe"),
        ],
    )

    result = tools.list_windows_tool(name_filter="spotify")

    assert "Spotify Premium (Spotify.exe)" in result
    assert "Notepad" not in result
    assert tools.list_windows_tool(window="notepad").count("Notepad") == 1
    assert "No visible windows match" in tools.list_windows_tool(name_filter="chrome")


def test_list_windows_accepts_the_filter_aliases():
    from himari.tool_schema import validate_arguments

    entry = next(tool for tool in tools.TOOLS if tool["name"] == "list_windows")
    spec = entry["spec"]["function"]["parameters"]

    assert validate_arguments(spec, {"name_filter": "chrome"}) == {"name_filter": "chrome"}
    assert validate_arguments(spec, {"window": "chrome"}) == {"window": "chrome"}


def test_find_app_tool_never_launches_and_reports_misses(monkeypatch):
    import himari.windows as windows_module

    launched = []
    monkeypatch.setattr(
        windows_module, "find_app",
        lambda name: [SimpleNamespace(name="Visual Studio Code", source="start_menu")],
    )
    monkeypatch.setattr(windows_module, "launch_app", lambda *a, **k: launched.append(a))

    assert "Visual Studio Code" in tools.find_app_tool("code")
    assert launched == []

    monkeypatch.setattr(windows_module, "find_app", lambda name: [])
    assert "No installed application" in tools.find_app_tool("missing-app")


def test_read_only_environment_tools_are_registered_without_confirmation():
    for name in ("installed_apps", "list_windows", "running_processes", "find_app"):
        entry = next(tool for tool in tools.TOOLS if tool["name"] == name)
        assert entry["confirm"] is False


def test_focus_window_tool_reports_verified_success(monkeypatch):
    import himari.windows as windows_module

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(windows_module, "list_windows", lambda: [
        SimpleNamespace(hwnd=5, title="Document - Editor", process_name="editor.exe"),
    ])
    focus = Mock(return_value=True)
    monkeypatch.setattr(windows_module, "focus_window", focus)

    result = tools.focus_window_tool("editor")

    assert result.startswith("Focused")
    assert "Document - Editor" in result
    focus.assert_called_once_with(5)


def test_focus_window_tool_is_honest_when_focus_fails(monkeypatch):
    import himari.windows as windows_module

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(windows_module, "list_windows", lambda: [
        SimpleNamespace(hwnd=5, title="Editor", process_name="editor.exe"),
    ])
    monkeypatch.setattr(windows_module, "focus_window", Mock(return_value=False))

    result = tools.focus_window_tool("Editor")

    assert "kept another window in front" in result
    assert not result.startswith("Focused")


def test_focus_window_tool_asks_when_matches_are_ambiguous(monkeypatch):
    import himari.windows as windows_module

    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(windows_module, "list_windows", lambda: [
        SimpleNamespace(hwnd=1, title="Chrome - Home", process_name="chrome.exe"),
        SimpleNamespace(hwnd=2, title="Chrome - Docs", process_name="chrome.exe"),
    ])
    focus = Mock()
    monkeypatch.setattr(windows_module, "focus_window", focus)

    result = tools.focus_window_tool("chrome")

    assert "2 windows matched" in result
    assert "Chrome - Home" in result
    focus.assert_not_called()


def test_focus_window_tool_requires_app_control_permission(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: False)

    assert "Permission denied" in tools.focus_window_tool("editor")


def test_open_project_reports_a_missing_editor(tmp_path, monkeypatch):
    from himari.development import launcher, workspace

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "webapp").mkdir()
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(workspace, "load_config", lambda: {"development": {"workspaces": [str(root)]}})
    monkeypatch.setattr(launcher, "editor_executable", lambda: None)

    message = tools.open_project("webapp")

    assert "Visual Studio Code was not found" in message


def test_open_project_respects_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: False)

    assert tools.open_project("webapp") == "Permission denied: app control is disabled in Settings."


def test_open_project_creation_requires_write_permission(tmp_path, monkeypatch):
    from himari.development import workspace

    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(tools, "_perm", lambda name: name != "allow_write_file")
    monkeypatch.setattr(workspace, "load_config", lambda: {"development": {"workspaces": [str(root)]}})

    message = tools.open_project("new-app", create=True)

    assert message.startswith("Permission denied")
    assert not (root / "new-app").exists()


def test_open_project_opens_the_folder_and_confirms_the_window(tmp_path, monkeypatch):
    from himari import windows
    from himari.development import launcher, workspace

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "webapp").mkdir()
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(workspace, "load_config", lambda: {"development": {"workspaces": [str(root)]}})
    monkeypatch.setattr(launcher, "editor_executable", lambda: "C:/Code/Code.exe")
    popen = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    monkeypatch.setattr(tools, "_window_handles", lambda: {1})
    monkeypatch.setattr(tools, "_running_process_snapshot", lambda: None)
    monkeypatch.setattr(
        windows,
        "list_windows",
        lambda: [SimpleNamespace(hwnd=2, title="webapp - Visual Studio Code", process_name="Code.exe")],
    )

    message = tools.open_project("webapp")

    assert message.startswith("Opened webapp in Visual Studio Code.")
    assert "Confirmed: the window 'webapp - Visual Studio Code' is visible." in message
    popen.assert_called_once_with(["C:/Code/Code.exe", str((root / "webapp").resolve())])


def test_open_project_can_create_a_new_folder(tmp_path, monkeypatch):
    from himari.development import launcher, workspace

    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(workspace, "load_config", lambda: {"development": {"workspaces": [str(root)]}})
    monkeypatch.setattr(launcher, "editor_executable", lambda: "C:/Code/Code.exe")
    monkeypatch.setattr(launcher.subprocess, "Popen", Mock())
    monkeypatch.setattr(tools, "_window_handles", lambda: None)
    monkeypatch.setattr(tools, "_running_process_snapshot", lambda: None)

    assert tools.open_project("new-app", create=True) == "Opened new-app in Visual Studio Code."
    assert (root / "new-app").is_dir()


def test_research_stops_before_touching_the_network_when_cancelled(monkeypatch):
    import threading

    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    fetch = Mock(side_effect=AssertionError("cancelled research must not search"))
    monkeypatch.setattr(tools, "_fetch_web_results", fetch)
    messages = []

    result = tools.research_web("latest news", cancel=cancel, progress=messages.append)

    assert result == tools.RESEARCH_CANCELLED
    assert messages == []
    fetch.assert_not_called()


def test_research_emits_progress_events(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(tools, "_research_queries", lambda query: ["one", "two"])
    monkeypatch.setattr(
        tools,
        "_fetch_web_results",
        lambda query: ([{"url": "https://example.com/x", "title": "X", "snippet": "s"}], None),
    )
    monkeypatch.setattr(tools, "_read_pages", lambda urls, cancel=None: {})
    messages = []

    result = tools.research_web("example topic", progress=messages.append)

    assert messages == [
        "Searching: one",
        "Searching: two",
        "Found 1 source(s); reading the key pages…",
        "Read 0 page(s); composing sourced answer…",
    ]
    assert "Source: https://example.com/x" in result


def test_research_stops_after_page_reading_when_cancelled(monkeypatch):
    import threading

    cancel = threading.Event()
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(tools, "_research_queries", lambda query: ["one"])
    monkeypatch.setattr(
        tools,
        "_fetch_web_results",
        lambda query: ([{"url": "https://example.com/x", "title": "X", "snippet": "s"}], None),
    )

    def read(urls, cancel_token=None):
        cancel.set()
        return {}

    monkeypatch.setattr(tools, "_read_pages", read)

    assert tools.research_web("example topic", cancel=cancel) == tools.RESEARCH_CANCELLED


def test_page_reader_discards_results_after_cancellation(monkeypatch):
    import threading

    cancel = threading.Event()
    fetched = []

    def fetch(url):
        fetched.append(url)
        cancel.set()
        return {"title": "t", "text": "body", "published": None}

    monkeypatch.setattr(tools, "_fetch_page", fetch)

    result = tools._read_pages([f"https://example.com/{index}" for index in range(5)], cancel)

    assert result == {}
    assert fetched


def _json_response(payload, status=200):
    response = MagicMock()
    response.status = status
    response.headers.get_content_charset.return_value = "utf-8"
    response.read.return_value = payload
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_research_can_use_a_configured_searxng_instance(monkeypatch):
    import json

    payload = json.dumps({"results": [
        {"title": "Trusted story", "url": "https://example.com/a", "content": "Useful snippet."},
        {"title": "Internal", "url": "http://127.0.0.1/admin", "content": "Never expose."},
    ]}).encode()
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(tools, "load", lambda: {"research": {"searx_url": "http://127.0.0.1:8888/"}})
    fetch = Mock(return_value=_json_response(payload))
    monkeypatch.setattr(tools, "urlopen", fetch)
    monkeypatch.setattr(tools, "_read_pages", lambda urls, cancel=None: {})

    result = tools.research_web("example topic")

    request = fetch.call_args.args[0]
    assert request.full_url.startswith("http://127.0.0.1:8888/search?")
    assert "format=json" in request.full_url
    assert "Trusted story" in result
    assert "Useful snippet." in result
    assert "127.0.0.1/admin" not in result


def test_searxng_invalid_json_is_reported_honestly(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(tools, "load", lambda: {"research": {"searx_url": "http://127.0.0.1:8888"}})
    monkeypatch.setattr(tools, "urlopen", Mock(return_value=_json_response(b"<html>not json</html>")))

    result = tools.research_web("example topic")

    assert "did not return valid JSON" in result


def test_searxng_unreachable_is_reported_honestly(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(tools, "load", lambda: {"research": {"searx_url": "http://127.0.0.1:8888"}})
    monkeypatch.setattr(tools, "urlopen", Mock(side_effect=URLError("offline")))

    result = tools.research_web("example topic")

    assert "couldn't reach the configured SearXNG instance" in result
