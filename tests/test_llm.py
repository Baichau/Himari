from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from himari.llm import LLM, LLMError, MAX_TOOL_ROUNDS


def _chunk(content="", tool_calls=None):
    return SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))


def _tool_call(name, arguments=None):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments or {}))


def test_stream_chat_disables_hidden_qwen_thinking_output():
    client = Mock()
    client.chat.return_value = iter([
        SimpleNamespace(message=SimpleNamespace(content="Hello.", tool_calls=None)),
    ])
    llm = LLM()
    with patch.object(llm, "client", return_value=client):
        assert llm.stream_chat([]) == "Hello."
    assert client.chat.call_args.kwargs["think"] is False


def test_model_status_uses_a_short_timeout_and_returns_installed_tags(monkeypatch):
    client = Mock()
    client.list.return_value = {
        "models": [{"name": "qwen3:8b"}, {"name": "llama3.2:3b"}],
    }
    llm = LLM()
    client_factory = Mock(return_value=client)
    monkeypatch.setattr(llm, "client", client_factory)

    models, error = llm.model_status()

    assert models == ["qwen3:8b", "llama3.2:3b"]
    assert error is None
    client_factory.assert_called_once_with(timeout=5)


def test_model_status_reports_unreachable_ollama(monkeypatch):
    llm = LLM()
    monkeypatch.setattr(
        llm,
        "client",
        Mock(side_effect=RuntimeError("connection refused")),
    )

    models, error = llm.model_status()

    assert models == []
    assert error == "connection refused"


def test_missing_ollama_model_error_includes_manual_install_command():
    client = Mock()
    client.chat.side_effect = RuntimeError("model 'qwen3:8b' not found")
    llm = LLM()
    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.load", return_value={"ollama": {
             "chat_model": "qwen3:8b",
             "temperature": 0.7,
             "timeout_seconds": 180,
             "host": "http://localhost:11434",
         }}), \
         pytest.raises(LLMError, match=r"ollama pull qwen3:8b"):
        llm.stream_chat([])


def test_confirmation_required_tools_fail_closed_without_callback():
    action = Mock(return_value="executed")
    client = Mock()
    client.chat.side_effect = [
        iter([_chunk(tool_calls=[_tool_call("dangerous")])]),
        iter([_chunk("The action was not approved.")]),
    ]
    llm = LLM([{"name": "dangerous", "confirm": True, "fn": action, "spec": {}}])
    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.db.log_action"):
        llm.stream_chat([])
    action.assert_not_called()
    assert client.chat.call_count == 2


def test_silent_tool_results_are_not_sent_to_the_visible_tool_callback():
    action = Mock(return_value="Web sources.")
    client = Mock()
    client.chat.side_effect = [
        iter([_chunk(tool_calls=[_tool_call("research_web", {"query": "latest news"})])]),
        iter([_chunk("Here is a sourced summary.")]),
    ]
    llm = LLM([{
        "name": "research_web",
        "silent": True,
        "fn": action,
        "spec": {},
    }])
    visible_tools = []
    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.db.log_action"):
        response = llm.stream_chat([], on_tool=lambda *args: visible_tools.append(args))

    assert response == "Here is a sourced summary."
    assert visible_tools == []
    action.assert_called_once_with(query="latest news")


def test_tool_rounds_are_bounded():
    action = Mock(return_value="done")
    client = Mock()
    client.chat.side_effect = lambda **kwargs: iter([
        _chunk(tool_calls=[_tool_call("repeat")]),
    ])
    llm = LLM([{"name": "repeat", "fn": action, "spec": {}}])
    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.db.log_action"), \
         pytest.raises(LLMError, match="prevent an unbounded action loop"):
        llm.stream_chat([])
    assert client.chat.call_count == MAX_TOOL_ROUNDS + 1
    assert action.call_count == MAX_TOOL_ROUNDS
