import pytest

from himari import db
from himari.memory import (
    CATEGORIES,
    MemoryManager,
    extract_candidate,
    normalize,
    retrieve,
    summarize_session,
)
from himari.memory import manager as memory_manager
from himari.memory import summarizer


@pytest.fixture()
def memory_db(tmp_path, monkeypatch):
    original_dir, original_db = db.APP_DIR, db.DB
    db.APP_DIR = tmp_path
    db.DB = tmp_path / "himari.db"
    monkeypatch.setattr(
        memory_manager, "load_config", lambda: {"privacy": {"memory_enabled": True}}
    )
    yield tmp_path
    db.APP_DIR, db.DB = original_dir, original_db


def test_migration_preserves_existing_rows(memory_db):
    db.add_memory("User prefers dark mode", "user")

    manager = MemoryManager()

    memories = manager.list_memories()
    assert len(memories) == 1
    assert memories[0].text == "User prefers dark mode"
    assert memories[0].category == "personal_context"
    assert memories[0].approved is True


def test_add_stores_category_and_project(memory_db):
    manager = MemoryManager()

    memory_id = manager.add("Building Himari 4", category="projects", project="himari")

    memory = manager.get(memory_id)
    assert memory.category == "projects"
    assert memory.project == "himari"
    assert manager.list_memories(category="projects")[0].id == memory_id
    assert manager.list_memories(project="himari")[0].id == memory_id
    assert manager.list_memories(category="preferences") == []
    with pytest.raises(ValueError):
        manager.add("text", category="unknown")


def test_duplicate_memories_are_merged_case_insensitively(memory_db):
    manager = MemoryManager()

    first = manager.add("User prefers English")
    second = manager.add("  user   PREFERS english ")

    assert first == second
    assert len(manager.list_memories()) == 1


def test_sensitive_and_temporary_memories_are_rejected(memory_db):
    manager = MemoryManager()

    assert manager.add("my password is hunter2") is None
    assert manager.add("I am tired today") is None
    assert normalize("  A   b ") == "a b"


def test_suggestions_can_be_approved(memory_db):
    manager = MemoryManager()
    memory_id = manager.add("User likes tea", approved=False)

    assert manager.list_memories() == []
    assert manager.list_memories(include_suggestions=True)[0].id == memory_id
    manager.approve(memory_id)
    assert manager.list_memories()[0].id == memory_id


def test_update_and_delete(memory_db):
    manager = MemoryManager()
    memory_id = manager.add("Old text", category="preferences")

    assert manager.update(memory_id, text="New text", category="decisions", project="p1") is True
    memory = manager.get(memory_id)
    assert (memory.text, memory.category, memory.project) == ("New text", "decisions", "p1")
    assert manager.update(memory_id, text="api key sk-123") is False

    manager.delete(memory_id)
    assert manager.get(memory_id) is None
    assert manager.update("missing", text="x") is False


def test_retrieval_ranks_and_bounds_results(memory_db):
    manager = MemoryManager()
    manager.add("User prefers Russian language in chat", category="preferences")
    manager.add("User likes cats and tea", category="preferences")
    manager.add("Project uses PySide6 and Ollama for Russian localization", category="projects")

    results = retrieve("Russian language")

    assert results
    assert "Russian" in results[0].text
    assert all(isinstance(item.text, str) for item in results)

    tiny = retrieve("Russian language", token_budget=1)
    assert tiny == []


def test_disabled_memory_stops_storage_and_retrieval(memory_db, monkeypatch):
    manager = MemoryManager()
    manager.add("User prefers tea")

    monkeypatch.setattr(
        memory_manager, "load_config", lambda: {"privacy": {"memory_enabled": False}}
    )

    assert manager.add("User prefers coffee") is None
    assert retrieve("tea") == []
    assert len(manager.list_memories()) == 1  # existing data stays manageable


def test_extract_candidate_categorizes_requests():
    assert extract_candidate("remember that I prefer dark mode") == {
        "text": "I prefer dark mode", "category": "preferences",
    }
    assert extract_candidate("Remember that I am working on the Himari project")["category"] == "projects"
    assert extract_candidate("remember that we decided to use SQLite")["category"] == "decisions"
    assert extract_candidate("remember that my password is abc123") is None
    assert extract_candidate("remember that I am tired today") is None
    assert extract_candidate("hello there") is None


def test_summarizer_uses_local_client_and_saves(memory_db):
    db.add_message("session", "user", "I prefer Russian")
    db.add_message("session", "assistant", "Understood")
    prompts = []

    def fake_chat(messages):
        prompts.append(messages)
        return "The user prefers Russian."

    summary = summarize_session("session", chat=fake_chat)

    assert summary == "The user prefers Russian."
    assert "I prefer Russian" in prompts[0][0]["content"]
    assert db.summary_for_session("session") == "The user prefers Russian."


def test_summarizer_fails_soft_without_fabricating(memory_db):
    db.add_message("session", "user", "hello")
    db.add_message("session", "assistant", "hi")

    def broken_chat(messages):
        raise RuntimeError("ollama unavailable")

    assert summarize_session("session", chat=broken_chat) is None
    assert summarize_session("empty-session", chat=broken_chat) is None
    assert summarize_session("session", chat=lambda messages: "   ") is None


def test_categories_are_stable():
    assert CATEGORIES == (
        "preferences",
        "personal_context",
        "projects",
        "decisions",
        "workflows",
        "conversation_summaries",
    )