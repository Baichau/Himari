import logging

import pytest

from himari import db
from himari.memory import (
    CATEGORIES,
    MemoryManager,
    embeddings,
    extract_candidate,
    normalize,
    retrieve,
    summarize_session,
)
from himari.memory import manager as memory_manager
from himari.memory import summarizer
from himari.memory.scoring import score


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


def test_near_duplicate_memories_are_merged(memory_db):
    manager = MemoryManager()

    first = manager.add("User prefers English")
    second = manager.add("User prefers English language")

    assert first == second
    assert len(manager.list_memories()) == 1
    assert manager.get(first).text == "User prefers English language"


def test_merged_memory_adopts_a_more_specific_category(memory_db):
    manager = MemoryManager()

    first = manager.add("Building the Himari dashboard")
    second = manager.add(
        "Building the Himari dashboard", category="projects", project="himari"
    )

    assert first == second
    memory = manager.get(first)
    assert memory.category == "projects"
    assert memory.project == "himari"


def test_distinct_memories_stay_separate(memory_db):
    manager = MemoryManager()

    manager.add("User likes tea")
    manager.add("User likes coffee")

    assert len(manager.list_memories()) == 2


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


def test_retrieval_explains_each_match(memory_db):
    manager = MemoryManager()
    manager.add("User prefers Russian language", category="preferences")

    results = retrieve("Russian language")

    assert results
    assert results[0].score > 0
    assert "matched 2/2 terms" in results[0].reason


def test_retrieval_collapses_near_duplicate_rows(memory_db):
    db.add_memory("User prefers Russian language", "user")
    db.add_memory("User prefers Russian language chat", "user")

    results = retrieve("Russian language")

    assert len(results) == 1


def test_recency_and_project_increase_the_score():
    now = 1_000_000_000.0
    fresh, _ = score("deploy", "Himari deploy steps", created=now - 3600, now=now)
    stale, _ = score(
        "deploy", "Himari deploy steps", created=now - 86400 * 365, now=now
    )
    assert fresh > stale

    plain, _ = score("deploy", "Himari deploy steps", created=now, now=now)
    boosted, _ = score(
        "deploy",
        "Himari deploy steps",
        project="himari",
        row_project="Himari",
        created=now,
        now=now,
    )
    assert boosted > plain


def test_scores_are_zero_without_token_overlap():
    assert score("weather", "User prefers tea", created=0) == (0.0, "")


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


def test_summary_prompt_asks_for_decisions_and_open_tasks(memory_db):
    assert "decisions" in summarizer.SUMMARY_PROMPT
    assert "still open" in summarizer.SUMMARY_PROMPT
    assert "promises" in summarizer.SUMMARY_PROMPT
    assert "never invent" in summarizer.SUMMARY_PROMPT


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
        "activity",
    )

def test_summarize_older_covers_everything_but_recent_turns(memory_db):
    for index in range(40):
        role = "user" if index % 2 == 0 else "assistant"
        db.add_message("long", role, f"turn {index}")

    prompts = []

    def fake_chat(messages):
        prompts.append(messages)
        return "The user worked through turns 0 to 7."

    summary = summarizer.summarize_older("long", keep_recent=32, chat=fake_chat)

    assert summary == "The user worked through turns 0 to 7."
    assert db.summary_for_session("long") == summary
    transcript = prompts[0][0]["content"]
    assert "turn 7" in transcript
    assert "turn 32" not in transcript


def test_summarize_older_skips_short_conversations(memory_db):
    for index in range(20):
        db.add_message("short", "user", f"turn {index}")

    assert summarizer.summarize_older("short", keep_recent=32, chat=lambda m: "x") is None


def test_old_summaries_are_pruned(memory_db):
    for index in range(15):
        db.save_summary("demo", f"summary {index}")

    assert db.summary_for_session("demo") == "summary 14"
    with db.conn() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM summaries WHERE session='demo'"
        ).fetchone()[0]
    assert count == 10


def test_overlapping_summaries_merge_into_one(memory_db):
    db.save_summary("merge", "The user prefers dark mode. The project is Himari.")
    merged = db.save_summary(
        "merge",
        "The user prefers dark mode. The project is Himari. The app targets Windows.",
    )

    assert "targets Windows" in merged
    assert db.summary_for_session("merge") == merged
    with db.conn() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM summaries WHERE session='merge'"
        ).fetchone()[0]
    assert count == 1


def test_distinct_summaries_stay_separate(memory_db):
    db.save_summary("topics", "The user prefers dark mode and Russian replies.")
    db.save_summary("topics", "The team deploys nightly builds to staging servers.")

    with db.conn() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM summaries WHERE session='topics'"
        ).fetchone()[0]
    assert count == 2


def test_conflict_detection_flags_negated_memories():
    from himari.memory.conflicts import find_conflicts

    memories = [
        {"id": "1", "text": "The user likes dark mode."},
        {"id": "2", "text": "The user does not like dark mode."},
        {"id": "3", "text": "The user likes tea."},
    ]

    conflicts = find_conflicts(memories)

    assert len(conflicts) == 1
    assert {conflicts[0]["first_id"], conflicts[0]["second_id"]} == {"1", "2"}


def test_conflict_detection_flags_antonyms():
    from himari.memory.conflicts import find_conflicts

    conflicts = find_conflicts(
        [
            {"id": "1", "text": "User loves rainy weather."},
            {"id": "2", "text": "User hates rainy weather."},
        ]
    )

    assert len(conflicts) == 1
    assert "love" in conflicts[0]["reason"]


def test_manager_reports_contradictory_memories(memory_db):
    manager = MemoryManager()
    manager.add("The user likes cold weather.")
    manager.add("The user does not like cold weather.")

    conflicts = manager.conflicts()

    assert len(conflicts) == 1
    assert any(
        "not like" in text
        for text in (conflicts[0]["first"], conflicts[0]["second"])
    )


def test_semantic_score_retrieves_without_token_overlap():
    value, reason = score(
        "what pet do I have", "User owns a cat named Mochi", semantic=0.8
    )

    assert value > 0
    assert "semantic" in reason


def test_retrieval_uses_a_configured_local_embedding_model(memory_db, monkeypatch):
    manager = MemoryManager()
    manager.add("User owns a cat named Mochi")
    monkeypatch.setattr(embeddings, "configured_model", lambda: "nomic-embed-text")
    monkeypatch.setattr(
        embeddings,
        "embed",
        lambda texts, model: [[1.0, 0.0] for _ in texts],
    )

    memories = retrieve("what pet do I have", limit=3)

    assert memories
    assert "semantic" in memories[0].reason


def test_retrieval_falls_back_to_keywords_when_embeddings_fail(
    memory_db, monkeypatch, caplog
):
    manager = MemoryManager()
    manager.add("User owns a cat named Mochi")

    def unavailable(texts, model):
        raise RuntimeError("embedding model is not installed")

    monkeypatch.setattr(embeddings, "configured_model", lambda: "missing-model")
    monkeypatch.setattr(embeddings, "embed", unavailable)

    with caplog.at_level(logging.WARNING, logger="himari.memory"):
        memories = retrieve("cat Mochi", limit=3)

    assert memories
    assert "keyword ranking" in caplog.text


def test_editing_a_memory_invalidates_its_cached_vector(memory_db):
    manager = MemoryManager()
    memory_id = manager.add("User likes tea")
    db.store_memory_vectors("nomic-embed-text", {memory_id: [1.0, 0.0]})

    manager.update(memory_id, text="User likes coffee")

    assert memory_id not in db.memory_vectors("nomic-embed-text")
    assert db.memory_vectors("nomic-embed-text") == {}
