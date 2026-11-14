import os
import sys
from unittest.mock import Mock

import pytest

from himari import db
from himari.agent import (
    AgentOrchestrator,
    AgentStatus,
    CancellationToken,
    Executor,
    StepStatus,
    TaskPlan,
    TaskRecord,
    ToolRegistry,
    Verification,
    classify_failure,
    decide,
    verify,
    verify_objective,
)
from himari.agent.plan import STEP_FAILED, STEP_SUCCEEDED
from himari.agent.recovery import (
    ACTION_ALTERNATIVE,
    ACTION_ASK_USER,
    ACTION_RETRY,
    ACTION_STOP,
    PERMISSION,
    TIMEOUT,
    UNAVAILABLE,
    VERIFICATION,
)
from himari.core.intent import Intent
from himari.security import PermissionManager, SecurityLayer

audit_module = sys.modules["himari.security.audit"]


@pytest.fixture(autouse=True)
def quiet_audit(monkeypatch):
    monkeypatch.setattr(audit_module.db, "log_action", lambda *a, **k: None)


@pytest.fixture()
def permissions():
    state = {"permissions": {
        "allow_open_app": True,
        "allow_read_file": True,
        "allow_write_file": True,
        "allow_screen_capture": True,
        "allow_active_window": True,
        "allow_media_control": True,
        "allow_run_command": True,
    }}
    return state, PermissionManager(load_config=lambda: state)


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


class _Snapshot:
    def to_dict(self):
        return {}


class _Environment:
    def snapshot(self, intent=None):
        return _Snapshot()


class FakeIntentEngine:
    def __init__(self, category="calendar"):
        self.category = category

    def understand(self, text, history=(), use_model=False):
        return Intent(objective=text, category=self.category)


class PlanPlanner:
    def __init__(self, plan):
        self.plan = plan
        self.plan_calls = 0

    def make_plan(self, objective, tool_specs, token=None, max_steps=8):
        self.plan_calls += 1
        return self.plan

    def next_action(self, messages, tool_specs, token=None):
        raise AssertionError("Step mode must not run when a plan succeeded.")


def _orchestrator(planner, tools, manager, **kwargs):
    registry = ToolRegistry(tools)
    security = SecurityLayer(manager=manager)
    executor = Executor(security=security, registry=registry, timeout_seconds=5)
    return AgentOrchestrator(
        registry=registry,
        security=security,
        planner=planner,
        executor=executor,
        intent_engine=FakeIntentEngine(),
        environment=_Environment(),
        **kwargs,
    )


# -- plans ----------------------------------------------------------

def test_plan_orders_steps_by_dependency_and_skips_blocked():
    plan = TaskPlan.from_json({
        "objective": "two things",
        "steps": [
            {"id": "b", "objective": "second", "tool": "active_window", "depends_on": ["a"]},
            {"id": "a", "objective": "first", "tool": "find_app"},
        ],
    }, objective="two things")

    ok, errors = plan.validate()
    assert ok, errors
    assert [step.id for step in plan.ready()] == ["a"]

    plan.mark("a", STEP_SUCCEEDED, result="Chrome")
    assert [step.id for step in plan.ready()] == ["b"]

    plan.mark("b", STEP_FAILED, error="boom")
    assert plan.is_complete()
    assert not plan.succeeded
    assert plan.progress()[STEP_FAILED] == 1


def test_plan_rejects_cycles_and_unknown_dependencies():
    plan = TaskPlan.from_json({
        "steps": [
            {"id": "a", "objective": "a", "tool": "x", "depends_on": ["b"]},
            {"id": "b", "objective": "b", "tool": "y", "depends_on": ["a"]},
        ]
    })
    ok, errors = plan.validate()
    assert not ok
    assert "cycle" in " ".join(errors).lower()

    broken = TaskPlan.from_json({
        "steps": [{"id": "a", "objective": "a", "tool": "x", "depends_on": ["ghost"]}]
    })
    ok, errors = broken.validate()
    assert not ok
    assert "ghost" in " ".join(errors)


def test_blocked_steps_are_skipped_not_run():
    plan = TaskPlan.from_json({
        "steps": [
            {"id": "a", "objective": "a", "tool": "x"},
            {"id": "b", "objective": "b", "tool": "y", "depends_on": ["a"]},
            {"id": "c", "objective": "c", "tool": "z", "depends_on": ["b"]},
        ]
    })
    plan.mark("a", STEP_FAILED, error="nope")
    skipped = plan.skip_blocked()
    assert [step.id for step in skipped] == ["b", "c"]
    assert plan.ready() == []


# -- recovery -------------------------------------------------------

def test_permission_denials_are_never_retried():
    recovery = decide("run_command", PERMISSION)
    assert recovery.action == ACTION_STOP
    assert recovery.alternatives == []


def test_mutating_timeout_is_not_repeated():
    recovery = decide("write_file", TIMEOUT)
    assert recovery.action == ACTION_ASK_USER
    assert recovery.retry_allowed is False


def test_read_only_timeout_retries_once():
    recovery = decide("active_window", TIMEOUT, attempts=1)
    assert recovery.action == ACTION_RETRY
    assert recovery.retry_allowed is True
    assert decide("active_window", TIMEOUT, attempts=2).retry_allowed is False


def test_verification_failure_suggests_an_alternative():
    recovery = decide("play_music", VERIFICATION)
    assert recovery.action == ACTION_ALTERNATIVE
    assert "spotify_search" in recovery.alternatives


def test_unavailable_tool_uses_a_filtered_alternative():
    recovery = decide("weather_forecast", UNAVAILABLE, allowed_tools={"research_web"})
    assert recovery.action == ACTION_ALTERNATIVE
    assert recovery.alternatives == ["research_web"]


def test_failure_classification():
    assert classify_failure("Permission allow_open_app is disabled in Settings.", denied=True) == PERMISSION
    assert classify_failure("Timed out after 5 seconds") == TIMEOUT
    assert classify_failure("Spotify is not installed.") == UNAVAILABLE
    assert classify_failure("Outcome missing", verification_failed=True) == VERIFICATION


# -- verification ---------------------------------------------------

def test_media_verification_requires_reported_playback():
    failed = verify("play_music", {}, {"ok": True, "verified": False, "error": "Not playing."})
    assert failed.ok is False
    assert failed.definitive is True

    passed = verify("play_music", {}, {
        "ok": True, "verified": True, "method": "deep_link",
        "now_playing": {"title": "Blinding Lights", "artist": "The Weeknd"},
    })
    assert passed.ok is True
    assert "Blinding Lights" in passed.detail


def test_file_verification_checks_the_disk(tmp_path):
    target = tmp_path / "note.txt"
    missing = verify("write_file", {"path": str(target)}, "wrote note.txt")
    assert missing.ok is False
    target.write_text("hello", encoding="utf-8")
    present = verify("write_file", {"path": str(target)}, "wrote note.txt")
    assert present.ok is True


def test_weather_verification_requires_forecast_data():
    assert verify("weather_forecast", {}, {"ok": False}).ok is False
    good = verify("weather_forecast", {}, {
        "location": "Berlin", "days": [{"summary": "Clear"}],
    })
    assert good.ok is True


def test_weather_verification_names_a_structured_location():
    result = verify("weather_forecast", {}, {
        "location": {"name": "Paris", "country": "France"},
        "daily": [{"condition": "Clear"}],
    })

    assert result.ok is True
    assert "Paris, France" in result.detail


def test_calendar_export_verification_requires_the_file(tmp_path):
    target = tmp_path / "calendar.ics"
    missing = verify("calendar_export", {"path": str(target)}, {"ok": True, "path": str(target)})
    assert missing.ok is False
    assert missing.definitive is True

    target.write_text("BEGIN:VCALENDAR", encoding="utf-8")
    present = verify("calendar_export", {"path": str(target)}, {
        "ok": True, "path": str(target), "events": 3,
    })
    assert present.ok is True
    assert present.evidence["events"] == 3
    assert present.evidence["path"] == os.path.abspath(str(target))


def test_objective_verification_counts_failed_steps():
    ok_step = Mock(succeeded=True, verification={"ok": True}, status="succeeded")
    bad_step = Mock(succeeded=False, verification={}, status="failed")
    intent = Intent(objective="x", category="calendar")
    assert verify_objective(intent, [ok_step, bad_step]).ok is False
    assert verify_objective(intent, [ok_step]).ok is True


def test_answer_only_intent_has_no_action_outcome():
    result = verify_objective(Intent(objective="hello", category="chat"), [])
    assert isinstance(result, Verification)
    assert result.ok is True


# -- task records ---------------------------------------------------

def test_terminal_task_states_are_locked():
    record = TaskRecord("do work")
    record.transition(AgentStatus.UNDERSTANDING)
    record.transition(AgentStatus.PLANNING)
    record.transition(AgentStatus.COMPLETED)
    with pytest.raises(ValueError):
        record.transition(AgentStatus.EXECUTING)


def test_task_record_round_trip(monkeypatch):
    stored = {}

    def fake_save(task_id, objective, profile, status, payload):
        stored.update(payload)

    monkeypatch.setattr(db, "save_task", fake_save)
    monkeypatch.setattr(db, "load_task", lambda task_id: {"payload": stored})

    record = TaskRecord("prepare a plan", profile="guided")
    record.transition(AgentStatus.PLANNING)
    record.report = "done"
    assert record.save() is True
    loaded = TaskRecord.load(record.task_id)
    assert loaded is not None
    assert loaded.objective == "prepare a plan"
    assert loaded.status is AgentStatus.PLANNING
    assert loaded.report == "done"


# -- plan-mode execution -------------------------------------------

def test_orchestrator_executes_a_plan_and_reports_verified(permissions):
    _, manager = permissions
    plan = TaskPlan.from_json({
        "objective": "inspect the editor",
        "steps": [
            {"id": "s1", "objective": "Find the editor", "tool": "find_app",
             "arguments": {"name": "code"}},
            {"id": "s2", "objective": "Read the active window", "tool": "active_window",
             "depends_on": ["s1"]},
        ],
    }, objective="inspect the editor")
    tools = [
        _tool("find_app", Mock(return_value="Visual Studio Code"),
              {"name": {"type": "string"}}, ["name"]),
        _tool("active_window", Mock(return_value="main.py — Code")),
    ]
    planner = PlanPlanner(plan)
    events = []

    state = _orchestrator(planner, tools, manager, on_status=events.append).run(
        "inspect the editor"
    )

    assert state.status is AgentStatus.COMPLETED
    assert state.verified is True
    assert [step.tool for step in state.steps] == ["find_app", "active_window"]
    assert "Completed" in state.final_answer
    assert planner.plan_calls == 1
    statuses = [event["status"] for event in events]
    assert statuses[0] == "understanding"
    assert statuses[-1] == "completed"
    assert any(event.get("plan") for event in events)


def test_orchestrator_reports_partial_plan_failure(permissions):
    _, manager = permissions
    plan = TaskPlan.from_json({
        "steps": [
            {"id": "s1", "objective": "Read the window", "tool": "active_window"},
            {"id": "s2", "objective": "Find an app", "tool": "find_app",
             "arguments": {}},
        ],
    }, objective="mixed task")
    tools = [
        _tool("active_window", Mock(return_value="Editor")),
        _tool("find_app", Mock(return_value="Chrome"),
              {"name": {"type": "string"}}, ["name"]),
    ]

    state = _orchestrator(PlanPlanner(plan), tools, manager).run("mixed task")

    assert state.status is AgentStatus.PARTIALLY_COMPLETED
    assert state.verified is False
    assert "Partly completed" in state.final_answer
    assert state.steps[1].status is StepStatus.INVALID


def test_cancelled_plan_does_not_run_tools(permissions):
    _, manager = permissions
    plan = TaskPlan.from_json({
        "steps": [{"id": "s1", "objective": "x", "tool": "active_window"}],
    })
    handler = Mock(return_value="unused")
    token = CancellationToken()
    token.cancel()

    state = _orchestrator(
        PlanPlanner(plan), [_tool("active_window", handler)], manager,
    ).run("x", token=token)

    handler.assert_not_called()
    assert state.status is AgentStatus.CANCELLED
