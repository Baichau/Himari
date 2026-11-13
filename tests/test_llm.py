import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from himari.llm import LLM, LLMCancelled, LLMError, MAX_START_RETRIES, MAX_TOOL_ROUNDS
from himari.security import Decision, RiskLevel


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


def test_stream_chat_can_think_deeply_when_asked():
    client = Mock()
    client.chat.return_value = iter([_chunk("Answer.")])
    llm = LLM()
    with patch.object(llm, "client", return_value=client):
        assert llm.stream_chat([], think=True) == "Answer."
    assert client.chat.call_args.kwargs["think"] is True


def test_stream_chat_falls_back_when_the_model_cannot_think():
    client = Mock()
    client.chat.side_effect = [
        RuntimeError("llama3.2:latest does not support thinking"),
        iter([_chunk("Answer.")]),
    ]
    llm = LLM()
    statuses = []
    with patch.object(llm, "client", return_value=client):
        assert (
            llm.stream_chat([], think=True, on_status=statuses.append)
            == "Answer."
        )
    assert client.chat.call_args.kwargs["think"] is False
    assert any("does not support deep thinking" in status for status in statuses)


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


def test_chat_tool_execution_goes_through_the_security_layer():
    action = Mock(return_value="executed")
    security = Mock()
    security.authorize.return_value = Decision(False, RiskLevel.HIGH, "blocked by policy")
    client = Mock()
    client.chat.side_effect = [
        iter([_chunk(tool_calls=[_tool_call("dangerous")])]),
        iter([_chunk("The action was blocked.")]),
    ]
    llm = LLM([{"name": "dangerous", "fn": action, "spec": {}}], security=security)
    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.db.log_action") as legacy_log:
        assert llm.stream_chat([]) == "The action was blocked."
    action.assert_not_called()
    security.record_result.assert_not_called()
    legacy_log.assert_not_called()


def test_chat_tool_results_are_recorded_by_the_security_layer():
    action = Mock(return_value="Chrome")
    security = Mock()
    security.authorize.return_value = Decision(True, RiskLevel.READ, "allowed")
    client = Mock()
    client.chat.side_effect = [
        iter([_chunk(tool_calls=[_tool_call("find_app", {"name": "chrome"})])]),
        iter([_chunk("Chrome is installed.")]),
    ]
    llm = LLM([{"name": "find_app", "fn": action, "spec": {}}], security=security)
    with patch.object(llm, "client", return_value=client):
        assert llm.stream_chat([]) == "Chrome is installed."
    action.assert_called_once_with(name="chrome")
    security.record_result.assert_called_once_with("find_app", {"name": "chrome"}, "Chrome")


def test_stream_chat_uses_the_long_reply_wait_and_keeps_the_model_loaded():
    client = Mock()
    client.chat.return_value = iter([_chunk("Hi")])
    llm = LLM()
    config = {"ollama": {
        "chat_model": "qwen3:8b",
        "temperature": 0.7,
        "host": "http://127.0.0.1:11434",
        "stream_timeout_seconds": 900,
        "keep_alive": "30m",
    }}
    factory = Mock(return_value=client)
    with patch.object(llm, "client", factory), \
         patch("himari.llm.load", return_value=config):
        assert llm.stream_chat([]) == "Hi"

    factory.assert_called_once_with(timeout=900)
    assert client.chat.call_args.kwargs["keep_alive"] == "30m"


def test_stream_chat_retries_a_transient_connection_failure():
    client = Mock()
    client.chat.side_effect = [
        RuntimeError("connection refused"),
        iter([_chunk("Hi")]),
    ]
    llm = LLM()
    statuses = []

    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.time.sleep") as sleep:
        assert llm.stream_chat([], on_status=statuses.append) == "Hi"

    assert client.chat.call_count == 2
    assert statuses and "retrying" in statuses[0].lower()
    sleep.assert_called_once()


def test_stream_chat_gives_up_after_retries_with_a_clear_message():
    client = Mock()
    client.chat.side_effect = RuntimeError("connection refused")
    llm = LLM()

    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.time.sleep"), \
         pytest.raises(LLMError, match="Make sure Ollama is running"):
        llm.stream_chat([])

    assert client.chat.call_count == MAX_START_RETRIES + 1


def test_stream_chat_explains_a_reply_timeout():
    client = Mock()
    client.chat.side_effect = RuntimeError("timed out")
    llm = LLM()

    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.time.sleep"), \
         pytest.raises(LLMError, match="Reply wait limit"):
        llm.stream_chat([])


def test_stream_chat_recovers_from_an_empty_reply_with_a_shorter_context():
    client = Mock()
    client.chat.side_effect = [
        iter([_chunk("")]),
        iter([_chunk("Recovered answer.")]),
    ]
    llm = LLM()
    statuses = []
    messages = [
        {"role": "system", "content": "System rules."},
        {"role": "user", "content": "Older question"},
        {"role": "assistant", "content": "Older answer"},
        {"role": "user", "content": "Current question"},
    ]

    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.time.sleep"):
        result = llm.stream_chat(messages, on_status=statuses.append)

    assert result == "Recovered answer."
    assert client.chat.call_count == 2
    retry_messages = client.chat.call_args_list[1].kwargs["messages"]
    assert retry_messages[0]["role"] == "system"
    assert retry_messages[1]["content"] == "Current question"
    assert all("Older" not in str(m.get("content")) for m in retry_messages)
    assert any("empty reply" in status.lower() for status in statuses)


def test_empty_reply_retry_keeps_tool_observations():
    action = Mock(return_value="Chrome is installed.")
    client = Mock()
    client.chat.side_effect = [
        iter([_chunk(tool_calls=[_tool_call("find_app", {"name": "chrome"})])]),
        iter([_chunk("")]),
        iter([_chunk("Yes, Chrome is installed.")]),
    ]
    llm = LLM([{"name": "find_app", "fn": action, "spec": {}}])
    messages = [
        {"role": "system", "content": "System rules."},
        {"role": "user", "content": "Older question"},
        {"role": "assistant", "content": "Older answer"},
        {"role": "user", "content": "Is Chrome installed?"},
    ]

    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.time.sleep"), \
         patch("himari.llm.db.log_action"):
        result = llm.stream_chat(messages)

    assert result == "Yes, Chrome is installed."
    retry_messages = client.chat.call_args_list[2].kwargs["messages"]
    assert retry_messages[0] == {"role": "system", "content": "System rules."}
    assert retry_messages[1] == {"role": "user", "content": "Is Chrome installed?"}
    assert any(
        message["role"] == "tool" and message["content"] == "Chrome is installed."
        for message in retry_messages
    )
    assert all("Older" not in str(message.get("content")) for message in retry_messages)


def test_empty_reply_retry_caps_long_tool_observations():
    from himari.llm import _RETRY_TOOL_CHARS, _short_retry_messages

    retry = _short_retry_messages([
        {"role": "system", "content": "System rules."},
        {"role": "user", "content": "Read the file."},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "x" * (_RETRY_TOOL_CHARS + 500), "tool_name": "read"},
    ])

    tool_message = next(message for message in retry if message["role"] == "tool")
    assert len(tool_message["content"]) == _RETRY_TOOL_CHARS + 2
    assert tool_message["content"].endswith(" …")


def test_stream_chat_raises_a_clear_error_when_empty_replies_continue():
    client = Mock()
    client.chat.side_effect = [
        iter([_chunk("")]),
        iter([_chunk("   ")]),
    ]
    llm = LLM()

    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.time.sleep"), \
         pytest.raises(LLMError, match="empty reply"):
        llm.stream_chat([
            {"role": "system", "content": "System rules."},
            {"role": "user", "content": "Question"},
        ])

    assert client.chat.call_count == 2


def test_stream_chat_keeps_a_partial_reply_when_the_stream_breaks():
    def chunks():
        yield _chunk("Hel")
        raise RuntimeError("connection reset by peer")

    client = Mock()
    client.chat.return_value = chunks()
    llm = LLM()

    with patch.object(llm, "client", return_value=client), \
         pytest.raises(LLMError, match="partial reply"):
        llm.stream_chat([])


def test_preload_loads_the_configured_model_without_streaming():
    client = Mock()
    llm = LLM()
    config = {"ollama": {
        "chat_model": "qwen3:8b",
        "stream_timeout_seconds": 900,
        "keep_alive": "30m",
        "host": "http://127.0.0.1:11434",
    }}
    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.load", return_value=config):
        llm.preload()

    kwargs = client.chat.call_args.kwargs
    assert kwargs["model"] == "qwen3:8b"
    assert kwargs["stream"] is False
    assert kwargs["keep_alive"] == "30m"


def test_stream_chat_does_not_call_ollama_when_already_cancelled():
    client = Mock()
    llm = LLM()
    cancel = threading.Event()
    cancel.set()

    with patch.object(llm, "client", return_value=client), \
         pytest.raises(LLMCancelled):
        llm.stream_chat([], cancel_event=cancel)

    client.chat.assert_not_called()


def test_stream_chat_keeps_partial_content_when_cancelled_mid_stream():
    cancel = threading.Event()

    def chunks():
        yield _chunk("Hel")
        cancel.set()
        yield _chunk("lo")

    client = Mock()
    client.chat.return_value = chunks()
    tokens = []
    llm = LLM()

    with patch.object(llm, "client", return_value=client), \
         pytest.raises(LLMCancelled) as error:
        llm.stream_chat([], on_token=tokens.append, cancel_event=cancel)

    assert error.value.partial == "Hel"
    assert tokens == ["Hel"]


def _config_with_context(value):
    import copy

    from himari.config import DEFAULT

    config = copy.deepcopy(DEFAULT)
    config["ollama"]["context_window"] = value
    return config


def test_stream_chat_sends_the_configured_context_window(monkeypatch):
    client = Mock()
    client.chat.return_value = iter([_chunk("Hello.")])
    monkeypatch.setattr("himari.llm.load", lambda: _config_with_context(8192))
    llm = LLM()
    with patch.object(llm, "client", return_value=client):
        assert llm.stream_chat([]) == "Hello."
    assert client.chat.call_args.kwargs["options"]["num_ctx"] == 8192


def test_preload_uses_the_same_context_window(monkeypatch):
    client = Mock()
    client.chat.return_value = _chunk("Hi")
    monkeypatch.setattr("himari.llm.load", lambda: _config_with_context(8192))
    llm = LLM()
    with patch.object(llm, "client", return_value=client):
        llm.preload()
    assert client.chat.call_args.kwargs["options"]["num_ctx"] == 8192


def test_context_window_is_clamped_to_safe_bounds(monkeypatch):
    llm = LLM()
    for value, expected in ((100, 2048), (999999, 32768), ("not a number", 8192)):
        monkeypatch.setattr(
            "himari.llm.load", lambda value=value: _config_with_context(value)
        )
        assert llm._context_window() == expected


def test_chat_rejects_malformed_tool_arguments_before_the_handler_runs():
    action = Mock(return_value="should not run")
    client = Mock()
    client.chat.side_effect = [
        iter([_chunk(tool_calls=[_tool_call("open_app", {"wrong": "value"})])]),
        iter([_chunk("I will correct that.")]),
    ]
    spec = {
        "type": "function",
        "function": {
            "name": "open_app",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    }
    llm = LLM([{"name": "open_app", "fn": action, "spec": spec}])
    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.db.log_action"):
        assert llm.stream_chat([]) == "I will correct that."

    action.assert_not_called()
    second_messages = client.chat.call_args_list[1].kwargs["messages"]
    observation = next(m["content"] for m in second_messages if m["role"] == "tool")
    assert "Invalid arguments" in observation
    assert "Missing required argument" in observation


def test_chat_accepts_valid_tool_arguments():
    action = Mock(return_value="Opened Chrome.")
    client = Mock()
    client.chat.side_effect = [
        iter([_chunk(tool_calls=[_tool_call("open_app", {"name": "Chrome"})])]),
        iter([_chunk("Chrome is open.")]),
    ]
    spec = {
        "type": "function",
        "function": {
            "name": "open_app",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    }
    llm = LLM([{"name": "open_app", "fn": action, "spec": spec}])
    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.db.log_action"):
        assert llm.stream_chat([]) == "Chrome is open."

    action.assert_called_once_with(name="Chrome")


def test_chat_reports_a_timed_out_tool_without_hanging():
    import time

    action = Mock(side_effect=lambda **kwargs: time.sleep(0.3) or "late")
    client = Mock()
    client.chat.side_effect = [
        iter([_chunk(tool_calls=[_tool_call("slow_tool", {})])]),
        iter([_chunk("That took too long.")]),
    ]
    spec = {
        "type": "function",
        "function": {"name": "slow_tool", "parameters": {"type": "object", "properties": {}}},
    }
    llm = LLM([
        {"name": "slow_tool", "fn": action, "spec": spec, "timeout_seconds": 0.05}
    ])
    with patch.object(llm, "client", return_value=client), \
         patch("himari.llm.db.log_action"):
        assert llm.stream_chat([]) == "That took too long."

    observation = next(
        message["content"]
        for message in client.chat.call_args_list[1].kwargs["messages"]
        if message["role"] == "tool"
    )
    assert observation.startswith("Timed out:")
    assert "may still be running" in observation


def test_tool_timeout_helper_uses_per_tool_metadata():
    from himari.tool_exec import DEFAULT_TOOL_TIMEOUT_SECONDS, timeout_for

    assert timeout_for({}) == DEFAULT_TOOL_TIMEOUT_SECONDS
    assert timeout_for({"timeout_seconds": 5}) == 5.0
    assert timeout_for({"timeout_seconds": "bad"}) == DEFAULT_TOOL_TIMEOUT_SECONDS


def test_failed_tool_outcomes_are_logged_with_the_shared_classifier(caplog):
    from himari.llm import _log_tool_outcome

    with caplog.at_level("INFO", logger="himari.llm"):
        _log_tool_outcome("open_app", "Denied: not allowed")
        _log_tool_outcome("find_app", "Chrome is installed.")

    assert "open_app" in caplog.text
    assert "Denied: not allowed" in caplog.text
    assert "find_app" not in caplog.text


def test_think_is_not_sent_to_models_without_thinking_support():
    client = Mock()
    client.chat.return_value = iter([_chunk("Direct answer.")])
    llm = LLM()
    llm.capabilities = frozenset({"completion"})
    statuses = []
    with patch.object(llm, "client", return_value=client):
        assert llm.stream_chat([], think=True, on_status=statuses.append) == "Direct answer."

    assert client.chat.call_args.kwargs["think"] is False
    assert any("does not support deep thinking" in status for status in statuses)


def test_tools_are_not_advertised_to_models_without_tool_support():
    action = Mock(return_value="unused")
    client = Mock()
    client.chat.return_value = iter([_chunk("Plain answer.")])
    llm = LLM([{"name": "open_app", "fn": action, "spec": {}}])
    llm.capabilities = frozenset({"completion"})
    statuses = []
    with patch.object(llm, "client", return_value=client):
        assert llm.stream_chat([], on_status=statuses.append) == "Plain answer."

    assert "tools" not in client.chat.call_args.kwargs
    assert any("does not support tool calls" in status for status in statuses)


def test_unknown_capabilities_keep_the_previous_behaviour():
    action = Mock(return_value="unused")
    client = Mock()
    client.chat.return_value = iter([_chunk("Answer.")])
    llm = LLM([{"name": "open_app", "fn": action, "spec": {}}])

    with patch.object(llm, "client", return_value=client):
        assert llm.stream_chat([], think=True) == "Answer."

    assert client.chat.call_args.kwargs["think"] is True
    assert client.chat.call_args.kwargs["tools"] == [{}]
