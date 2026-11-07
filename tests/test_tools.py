from unittest.mock import patch

from unittest.mock import MagicMock, Mock, patch
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


def test_open_minecraft_launcher_uses_start_menu_shortcut(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(tools, "_start_menu_shortcut", lambda name: name == "Minecraft Launcher")
    monkeypatch.setattr(tools, "_start_menu_app_id", lambda app_id: pytest.fail("store fallback should not run"))

    assert tools.open_app("Minecraft Launcher") == "Opened Minecraft Launcher."


def test_open_minecraft_launcher_uses_store_app_when_shortcut_is_missing(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(tools, "_start_menu_shortcut", lambda name: False)
    monkeypatch.setattr(
        tools,
        "_start_menu_app_id",
        lambda app_id: app_id == "Microsoft.4297127D64EC_8wekyb3d8bbwe!Minecraft",
    )

    assert tools.open_app("Minecraft Launcher") == "Opened Minecraft Launcher."


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


def test_background_research_returns_sources_without_opening_a_browser(monkeypatch):
    document = (
        '<a class="result-link" href="https://duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fexample.com%2Fnews">Latest &amp; trusted story</a>'
        '<td class="result-snippet">Current <b>details</b> from today.</td>'
    ).encode()
    response = MagicMock()
    response.status = 200
    response.headers.get_content_charset.return_value = "utf-8"
    response.read.return_value = document
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    monkeypatch.setattr(tools, "_perm", lambda name: name == "allow_web_research")
    open_search = Mock(return_value=response)
    monkeypatch.setattr(tools, "urlopen", open_search)
    monkeypatch.setattr(tools.webbrowser, "open", Mock(side_effect=AssertionError("browser must stay closed")))

    result = tools.research_web("today's news")

    assert "Latest & trusted story" in result
    assert "Current details from today." in result
    assert "https://example.com/news" in result
    open_search.assert_called_once()
    assert open_search.call_args.kwargs["timeout"] == tools.WEB_RESEARCH_TIMEOUT_SECONDS
    assert "q=today%27s+news" in open_search.call_args.args[0].full_url


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
