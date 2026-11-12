import os

from himari import db, persona, config, logging_setup, paths, bootstrap


def test_bootstrap_normalizes_bracketed_ipv6_no_proxy_entries(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,[::1]")

    bootstrap._normalize_proxy_environment()

    assert os.environ["NO_PROXY"] == "localhost,127.0.0.1,::1"

def test_memory_roundtrip():
    db.add_memory("unique_test_fact_123","test")
    assert any("unique_test_fact_123" in m["text"] for m in db.memories())
def test_persona():
    msgs=persona.build([{"role":"user","content":"hi"}],[])
    assert msgs[0]["role"]=="system"
def test_config():
    cfg=config.load(); assert "ollama" in cfg


def test_config_errors_do_not_silently_replace_user_settings(tmp_path, monkeypatch):
    settings = tmp_path / "config.json"
    settings.write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CFG", settings)

    try:
        config.load()
    except config.ConfigError as error:
        assert str(settings) in str(error)
    else:
        raise AssertionError("Invalid user settings should be reported.")
    assert settings.read_text(encoding="utf-8") == "{invalid"


def test_config_save_replaces_settings_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CFG", tmp_path / "config.json")

    config.save({"ollama": {"chat_model": "qwen3:8b"}})

    assert config.load()["ollama"]["chat_model"] == "qwen3:8b"
    assert not (tmp_path / "config.json.tmp").exists()


def test_user_data_dir_can_be_relocated_outside_the_application(monkeypatch, tmp_path):
    data_dir = tmp_path / "portable-data"
    monkeypatch.setenv("HIMARI_HOME", str(data_dir))

    assert paths.user_data_dir() == data_dir.resolve()
    assert paths.resource_dir() != data_dir


def test_logging_uses_rotating_logs_under_the_user_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_setup, "user_data_dir", lambda: tmp_path)
    root_logger = logging_setup.logging.getLogger()
    existing_handlers = root_logger.handlers[:]
    original_level = root_logger.level

    try:
        log_path = logging_setup.configure_logging()
        logging_setup.logging.getLogger("test.release").warning("release log test")

        assert log_path == tmp_path / "logs" / "himari.log"
        assert "release log test" in log_path.read_text(encoding="utf-8")
    finally:
        for handler in root_logger.handlers[:]:
            if handler not in existing_handlers:
                root_logger.removeHandler(handler)
                handler.close()
        for handler in existing_handlers:
            if handler not in root_logger.handlers:
                root_logger.addHandler(handler)
        root_logger.setLevel(original_level)

def test_clear_session_removes_messages_and_summaries(tmp_path):
    original_dir = db.APP_DIR
    original_db = db.DB
    try:
        db.APP_DIR = tmp_path
        db.DB = tmp_path / "himari.db"
        db.add_message("demo", "user", "old conversation")
        db.save_summary("demo", "old summary")

        db.clear_session("demo")

        assert db.history("demo") == []
        assert db.summary_for_session("demo") == ""
    finally:
        db.APP_DIR = original_dir
        db.DB = original_db


def test_clear_all_sessions_removes_chats_but_keeps_memories(tmp_path):
    original_dir = db.APP_DIR
    original_db = db.DB
    try:
        db.APP_DIR = tmp_path
        db.DB = tmp_path / "himari.db"
        db.add_message("first", "user", "hello from the first chat")
        db.add_message("second", "user", "hello from the second chat")
        db.save_summary("first", "first summary")
        db.add_memory("I prefer tea", "test")

        db.clear_all_sessions()

        assert db.sessions() == []
        assert db.history("first") == []
        assert db.summary_for_session("first") == ""
        assert [memory["text"] for memory in db.memories()] == ["I prefer tea"]
    finally:
        db.APP_DIR = original_dir
        db.DB = original_db


def test_explicit_memory_requests_support_common_phrasings(tmp_path):
    original_dir = db.APP_DIR
    original_db = db.DB
    try:
        db.APP_DIR = tmp_path
        db.DB = tmp_path / "himari.db"

        assert db.suggest_memory("Keep in mind that I use Windows 11.")
        assert db.suggest_memory("Don't forget that I prefer short answers.")
        assert db.suggest_memory("Note that my project is Himari.")
        assert db.suggest_memory("Запомни, что я предпочитаю русский язык.")

        texts = {item["text"] for item in db.memory_suggestions()}
        assert "I use Windows 11." in texts
        assert "I prefer short answers." in texts
        assert "my project is Himari." in texts
        assert "я предпочитаю русский язык." in texts
        assert db.memory_is_sensitive("Call me at 555-123-4567") is True
        assert db.memory_is_sensitive("I prefer short answers.") is False
    finally:
        db.APP_DIR = original_dir
        db.DB = original_db


def test_memory_search_matches_cyrillic_terms(tmp_path):
    original_dir = db.APP_DIR
    original_db = db.DB
    try:
        db.APP_DIR = tmp_path
        db.DB = tmp_path / "himari.db"
        db.add_memory("Пользователь предпочитает русский язык", "test")
        db.add_memory("Пользователь любит кошек", "test")

        results = db.relevant_memories("РУССКИЙ язык")

        assert results[0]["text"] == "Пользователь предпочитает русский язык"
        assert len(results) == 1
    finally:
        db.APP_DIR = original_dir
        db.DB = original_db


def test_add_memory_deduplicates_casefolded_text(tmp_path):
    original_dir = db.APP_DIR
    original_db = db.DB
    try:
        db.APP_DIR = tmp_path
        db.DB = tmp_path / "himari.db"

        first_id = db.add_memory("User prefers tea", "test")
        duplicate_id = db.add_memory("  USER PREFERS TEA  ", "test")

        assert duplicate_id == first_id
        assert len(db.memories()) == 1
    finally:
        db.APP_DIR = original_dir
        db.DB = original_db


def test_memory_suggestions_need_approval_and_reject_sensitive_or_temporary_facts(tmp_path):
    original_dir = db.APP_DIR
    original_db = db.DB
    try:
        db.APP_DIR = tmp_path
        db.DB = tmp_path / "himari.db"

        suggestion_id = db.suggest_memory(
            "Please remember that I prefer Russian replies."
        )

        assert suggestion_id
        assert db.memories() == []
        assert db.memory_suggestions()[0]["text"] == "I prefer Russian replies."
        assert db.suggest_memory("Remember that my password is hunter2") is None
        assert db.suggest_memory("Remember that my email address is me@example.com") is None
        assert db.suggest_memory("Remember that I need this today") is None
        assert db.suggest_memory("I prefer Russian replies") is None

        db.add_memory("I prefer Russian replies.", source="user", approved=1)

        assert db.memory_suggestions() == []
        assert db.memories()[0]["text"] == "I prefer Russian replies."
    finally:
        db.APP_DIR = original_dir
        db.DB = original_db


def test_sessions_are_grouped_and_titled_from_the_first_user_message(tmp_path):
    original_dir = db.APP_DIR
    original_db = db.DB
    try:
        db.APP_DIR = tmp_path
        db.DB = tmp_path / "himari.db"
        db.add_message("first-chat", "user", "How do I fix this build?")
        db.add_message("first-chat", "assistant", "Let us check the failing step.")
        db.add_message("second-chat", "user", "Open Spotify")

        rows = db.sessions()
        by_session = {row["session"]: row for row in rows}

        assert set(by_session) == {"first-chat", "second-chat"}
        assert by_session["first-chat"]["title"] == "How do I fix this build?"
        assert by_session["first-chat"]["messages"] == 2
        assert by_session["second-chat"]["messages"] == 1

        detailed = db.messages_detailed("first-chat")
        assert [message["role"] for message in detailed] == ["user", "assistant"]
        assert all("ts" in message for message in detailed)
    finally:
        db.APP_DIR = original_dir
        db.DB = original_db
