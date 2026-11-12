from types import SimpleNamespace

import pytest

from himari import research, ui


@pytest.fixture(autouse=True)
def clear_query_cache():
    research._cache.clear()
    yield
    research._cache.clear()


@pytest.mark.parametrize(
    "text",
    [
        "who's elder titan in dota",
        "what is Nabeghlavi water?",
        "can you search who is Elder Titan in Dota 2",
        "latest news about Dota 2",
        "explain quantum computing",
        "tell me about Elder Titan in Dota 2",
        "who is the president of Georgia",
    ],
)
def test_factual_questions_are_researched(text):
    assert research.should_research(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "open Spotify",
        "play last Christmas",
        "what can you do",
        "hello",
        "who are you",
        "what's my name",
        "do you remember my birthday",
        "read what is on my screen",
        "how do I open Spotify",
        "is Spotify open",
        "what time is it",
        "remember that I like tea",
        "what is my password",
        "???",
        "",
    ],
)
def test_local_conversation_and_actions_are_not_researched(text):
    assert research.should_research(text) is False


def test_query_cleaning_removes_request_wrappers():
    assert research._clean_query(
        "Can you search what is Nabeghlavi water in Georgia? It's about..."
    ) == "what is Nabeghlavi water in Georgia"
    assert research._clean_query(
        "tell me about Elder Titan in Dota 2"
    ) == "Elder Titan in Dota 2"
    assert research._clean_query("who's elder titan in dota") == "who's elder titan in dota"


def test_research_results_are_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(
        research,
        "load",
        lambda: {"permissions": {"allow_web_research": True}},
    )
    monkeypatch.setattr(
        research,
        "research_web",
        lambda query: calls.append(query) or "Web results for: x\nSource: https://example.com",
    )

    assert research.research_for_prompt("who's elder titan in dota")
    assert research.research_for_prompt("who's elder titan in dota")
    assert calls == ["who's elder titan in dota"]


def test_research_is_skipped_when_permission_is_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(
        research,
        "load",
        lambda: {"permissions": {"allow_web_research": False}},
    )
    monkeypatch.setattr(research, "research_web", lambda query: calls.append(query))

    assert research.research_for_prompt("who's elder titan in dota") is None
    assert calls == []


def test_failed_research_is_not_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(
        research,
        "load",
        lambda: {"permissions": {"allow_web_research": True}},
    )
    monkeypatch.setattr(
        research,
        "research_web",
        lambda query: calls.append(query) or "Web research failed: problem",
    )

    assert research.research_for_prompt("who's elder titan in dota").startswith("Web research failed")
    assert research.research_for_prompt("who's elder titan in dota").startswith("Web research failed")
    assert len(calls) == 2


def _run_prepare(monkeypatch, *, deep_reasoning=True):
    monkeypatch.setattr(ui, "should_research", lambda text: True)
    monkeypatch.setattr(
        ui,
        "research_for_prompt",
        lambda text: "Web results for: x\nSource: https://example.com",
    )
    monkeypatch.setattr(ui.db, "relevant_memories", lambda *args, **kwargs: [])
    monkeypatch.setattr(ui.db, "summary_for_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui.db, "history", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        ui,
        "MemoryManager",
        lambda: SimpleNamespace(enabled=lambda: False),
    )
    monkeypatch.setattr(
        ui,
        "load",
        lambda: {
            "personality": None,
            "ollama": {"deep_reasoning": deep_reasoning},
        },
    )
    built = {}
    monkeypatch.setattr(
        ui.persona,
        "build",
        lambda *args, **kwargs: built.update(kwargs) or ["messages"],
    )
    statuses = []
    ran = []
    window = SimpleNamespace(
        session="session-1",
        status=SimpleNamespace(emit=statuses.append),
        cancelled=SimpleNamespace(emit=lambda *args: None),
        failed=SimpleNamespace(emit=lambda *args: None),
        _waiting_label="Waiting for Ollama…",
        _run=lambda messages, cancel_event, think=False: ran.append(
            (messages, think)
        ),
    )

    import threading

    ui.UI._prepare_and_run(
        window, "who's elder titan in dota", None, [], threading.Event()
    )
    return built, statuses, ran, window


def test_research_is_injected_before_the_model_call(monkeypatch):
    built, statuses, ran, window = _run_prepare(monkeypatch)

    assert built["research"].startswith("Web results for:")
    assert ran == [(["messages"], True)]
    assert any("Checking the web" in status for status in statuses)
    assert window._waiting_label == "Thinking deeply about your question…"


def test_deep_reasoning_can_be_turned_off_in_settings(monkeypatch):
    _, _, ran, window = _run_prepare(monkeypatch, deep_reasoning=False)

    assert ran == [(["messages"], False)]
    assert window._waiting_label == "Thinking through your question…"
