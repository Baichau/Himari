import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from himari.agent import (
    AgentOrchestrator,
    AgentStatus,
    CancellationToken,
    ExecutionResult,
    Executor,
    Planner,
    StepStatus,
    ToolArgumentError,
    ToolRegistry,
    classify_result,
)
from himari.security import PermissionManager, SecurityLayer

audit_module = sys.modules["himari.security.audit"]


@pytest.fixture(autouse=True)
def quiet_audit(monkeypatch):
    monkeypatch.setattr(audit_module.db, "log_action", lambda *args, **kwargs: None)


@pytest.fixture()
def permissions():
    state = {"permissions": {
        "allow_open_app": True,
        "allow_read_file": True,
        "allow_screen_capture": True,
        "allow_browser_automation": True,
        "allow_run_command": True,
    }}
    manager = PermissionManager(load_config=lambda: state)
    return state, manager


def _spec(name, properties=None, required=None):
    return {"type": "function", "function": {
        "name": name,
        "parameters": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        },
    }}


def _tool(name, fn, properties=None, required=None):
    return {"name": name, "fn": fn, "confirm": False,
            "spec": _spec(name, properties, required)}


class FakePlanner:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = []

    def next_action(self, messages, tool_specs, token=None):
        if token is not None:
            token.check()
        self.calls.append([dict(message) for message in messages])
        if self.actions:
            return self.actions.pop(0)
        return {"type": "final", "content": "All done."}


def _orchestrator(planner, tools, manager, confirm=None, max_rounds=5, on_status=None):
    registry = ToolRegistry(tools)
    security = SecurityLayer(confirm_callback=confirm, manager=manager)
    executor = Executor(security=security, registry=registry, timeout_seconds=5)
    return AgentOrchestrator(
        registry=registry,
        security=security,
        planner=planner,
        executor=executor,
        max_rounds=max_rounds,
        on_status=on_status,
    )


def test_agent_answers_without_tools(permissions):
    _, manager = permissions
    planner = FakePlanner([{"type": "final", "content": "The weather is unknown."}])

    state = _orchestrator(planner, [], manager).run("What is the weather?")

    assert state.status is AgentStatus.COMPLETED
    assert state.final_answer == "The weather is unknown."
    assert state.steps == []
    assert state.verified is True


def test_agent_executes_a_tool_and_feeds_the_observation_back(permissions):
    _, manager = permissions
    handler = Mock(return_value="Google Chrome")
    tools = [_tool("find_app", handler, {"name": {"type": "string"}}, ["name"])]
    planner = FakePlanner([
        {"type": "tool", "name": "find_app", "arguments": {"name": "chrome"}},
        {"type": "final", "content": "Chrome is installed."},
    ])

    state = _orchestrator(planner, tools, manager).run("Is Chrome installed?")

    assert state.status is AgentStatus.COMPLETED
    handler.assert_called_once_with(name="chrome")
    assert len(state.steps) == 1
    assert state.steps[0].status is StepStatus.SUCCEEDED
    assert state.verified is True
    second_prompt = planner.calls[1]
    assert any(message["role"] == "tool" and "Google Chrome" in message["content"]
               for message in second_prompt)


def test_invalid_arguments_are_rejected_before_execution(permissions):
    _, manager = permissions
    handler = Mock(return_value="wrote")
    tools = [_tool("write_file", handler, {
        "path": {"type": "string"},
        "content": {"type": "string"},
    }, ["path", "content"])]
    planner = FakePlanner([
        {"type": "tool", "name": "write_file", "arguments": {"path": "a.txt"}},
        {"type": "final", "content": "I could not write the file."},
    ])

    state = _orchestrator(planner, tools, manager).run("Write a file.")

    handler.assert_not_called()
    assert state.steps[0].status is StepStatus.INVALID
    assert "content" in state.steps[0].error
    assert state.status is AgentStatus.COMPLETED


def test_wrong_argument_types_are_rejected(permissions):
    _, manager = permissions
    handler = Mock(return_value="ok")
    tools = [_tool("set_volume", handler, {"percent": {"type": "integer"}}, ["percent"])]
    planner = FakePlanner([
        {"type": "tool", "name": "set_volume", "arguments": {"percent": "loud"}},
        {"type": "final", "content": "Volume was not changed."},
    ])

    state = _orchestrator(planner, tools, manager).run("Set volume.")

    handler.assert_not_called()
    assert state.steps[0].status is StepStatus.INVALID


def test_settings_permission_denies_the_action(permissions):
    state_config, manager = permissions
    state_config["permissions"]["allow_open_app"] = False
    handler = Mock(return_value="opened")
    tools = [_tool("launch_app", handler, {"name": {"type": "string"}}, ["name"])]
    planner = FakePlanner([
        {"type": "tool", "name": "launch_app", "arguments": {"name": "Spotify"}},
        {"type": "final", "content": "App control is disabled in Settings."},
    ])

    state = _orchestrator(planner, tools, manager).run("Open Spotify.")

    handler.assert_not_called()
    assert state.steps[0].status is StepStatus.DENIED
    assert "allow_open_app" in state.steps[0].error


def test_denied_actions_are_not_retried(permissions):
    _, manager = permissions
    handler = Mock(return_value="should not run")
    tools = [_tool("run_command", handler, {"cmd": {"type": "string"}}, ["cmd"])]
    planner = FakePlanner([
        {"type": "tool", "name": "run_command", "arguments": {"cmd": "dir"}},
        {"type": "tool", "name": "run_command", "arguments": {"cmd": "dir"}},
        {"type": "final", "content": "I did not run the command."},
    ])
    prompts = []

    state = _orchestrator(
        planner, tools, manager,
        confirm=lambda tool, args, message: prompts.append(tool) or False,
    ).run("Run dir.")

    assert len(prompts) == 1
    handler.assert_not_called()
    assert [step.status for step in state.steps] == [
        StepStatus.DENIED, StepStatus.DENIED,
    ]
    assert "not be retried" in state.steps[1].error


def test_failed_high_risk_tools_are_not_retried(permissions):
    _, manager = permissions
    handler = Mock(side_effect=RuntimeError("boom"))
    tools = [_tool("run_command", handler, {"cmd": {"type": "string"}}, ["cmd"])]
    planner = FakePlanner([
        {"type": "tool", "name": "run_command", "arguments": {"cmd": "dir"}},
        {"type": "tool", "name": "run_command", "arguments": {"cmd": "dir"}},
        {"type": "final", "content": "The command failed."},
    ])

    state = _orchestrator(
        planner, tools, manager, confirm=lambda *args: True,
    ).run("Run dir.")

    handler.assert_called_once()
    assert state.steps[0].status is StepStatus.FAILED
    assert state.steps[1].status is StepStatus.DENIED
    assert state.verified is False


def test_cancellation_before_planning(permissions):
    _, manager = permissions
    planner = FakePlanner([{"type": "final", "content": "unused"}])
    token = CancellationToken()
    token.cancel()

    state = _orchestrator(planner, [], manager).run("Do work.", token=token)

    assert state.status is AgentStatus.CANCELLED
    assert planner.calls == []


def test_cancellation_during_execution(permissions):
    _, manager = permissions
    token = CancellationToken()

    def handler():
        token.cancel()
        return "finished anyway"

    tools = [_tool("installed_apps", handler)]
    planner = FakePlanner([{"type": "tool", "name": "installed_apps", "arguments": {}}])

    state = _orchestrator(planner, tools, manager).run("List apps.", token=token)

    assert state.status is AgentStatus.CANCELLED
    assert state.error


def test_tool_rounds_are_bounded(permissions):
    _, manager = permissions
    handler = Mock(return_value="ok")
    tools = [_tool("installed_apps", handler)]
    planner = FakePlanner(
        [{"type": "tool", "name": "installed_apps", "arguments": {}}] * 10
    )

    state = _orchestrator(planner, tools, manager, max_rounds=5).run("Loop.")

    assert state.status is AgentStatus.FAILED
    assert state.rounds == 5
    assert handler.call_count == 5
    assert "tool rounds" in state.error


def test_empty_final_answer_is_not_success(permissions):
    _, manager = permissions
    planner = FakePlanner([{"type": "final", "content": "   "}])

    state = _orchestrator(planner, [], manager).run("Do something.")

    assert state.status is AgentStatus.FAILED
    assert state.final_answer == ""


def test_tool_error_strings_are_treated_as_failures(permissions):
    _, manager = permissions
    handler = Mock(return_value="Tool error: access denied")
    tools = [_tool("installed_apps", handler)]
    planner = FakePlanner([
        {"type": "tool", "name": "installed_apps", "arguments": {}},
        {"type": "final", "content": "It failed."},
    ])

    state = _orchestrator(planner, tools, manager).run("List apps.")

    assert state.steps[0].status is StepStatus.FAILED
    assert state.verified is False


def test_status_callback_reports_progress(permissions):
    _, manager = permissions
    events = []
    planner = FakePlanner([{"type": "final", "content": "Done."}])

    _orchestrator(
        planner, [], manager, on_status=events.append,
    ).run("Do it.")

    statuses = {event["status"] for event in events}
    assert {"planning", "verifying", "completed"} <= statuses
    assert all("detail" in event for event in events)


def test_planner_parses_native_tool_calls():
    response = SimpleNamespace(message=SimpleNamespace(
        content="",
        tool_calls=[SimpleNamespace(function=SimpleNamespace(
            name="open_app", arguments='{"name": "Spotify"}',
        ))],
    ))
    planner = Planner(chat=Mock(return_value=response))

    action = planner.next_action([{"role": "user", "content": "open spotify"}], [{}])

    assert action["type"] == "tool"
    assert action["name"] == "open_app"
    assert action["arguments"] == {"name": "Spotify"}


def test_planner_treats_malformed_arguments_as_invalid():
    response = SimpleNamespace(message=SimpleNamespace(
        content="",
        tool_calls=[SimpleNamespace(function=SimpleNamespace(
            name="open_app", arguments="{not json",
        ))],
    ))
    planner = Planner(chat=Mock(return_value=response))

    action = planner.next_action([], [{}])

    assert action["arguments"] is None


def test_planner_returns_final_content():
    response = SimpleNamespace(message=SimpleNamespace(content="Everything is fine.", tool_calls=None))
    planner = Planner(chat=Mock(return_value=response))

    action = planner.next_action([], [])

    assert action == {"type": "final", "content": "Everything is fine."}


def test_registry_rejects_unknown_tools_and_arguments():
    registry = ToolRegistry([_tool("open_app", Mock(), {"name": {"type": "string"}}, ["name"])])

    with pytest.raises(ToolArgumentError):
        registry.validate_arguments("open_app", {})
    with pytest.raises(ToolArgumentError):
        registry.validate_arguments("open_app", {"name": "x", "admin": True})
    with pytest.raises(ToolArgumentError):
        registry.validate_arguments("open_app", ["x"])
    with pytest.raises(KeyError):
        registry.get("missing_tool")


def test_classify_result_detects_failures():
    assert classify_result("ok") == (True, "")
    assert classify_result("")[0] is False
    assert classify_result(None)[0] is False
    assert classify_result({"ok": False, "error": "nope"}) == (False, "nope")
    assert classify_result("Denied: no")[0] is False


def test_executor_unknown_tool_is_denied(permissions):
    _, manager = permissions
    security = SecurityLayer(manager=manager)
    executor = Executor(security=security, registry=ToolRegistry([]))

    result = executor.execute("rm_rf", {})

    assert isinstance(result, ExecutionResult)
    assert result.status is StepStatus.DENIED
    assert "Unknown tool" in result.error
