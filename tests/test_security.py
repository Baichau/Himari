import sys
from unittest.mock import Mock

import pytest

from himari.security import (
    Decision,
    PermissionManager,
    RiskLevel,
    SecurityLayer,
    ValidationError,
    redact_value,
    risk_for,
    tool_is_known,
    validate_command,
    validate_path,
    validate_text,
)
from himari.security import permissions as permissions_module

audit_module = sys.modules["himari.security.audit"]


@pytest.fixture()
def config(monkeypatch):
    state = {"permissions": {
        "allow_open_app": True,
        "allow_read_file": True,
        "allow_screen_capture": True,
        "allow_browser_automation": True,
        "allow_run_command": True,
    }}

    def load():
        return state

    manager = PermissionManager(load_config=load)
    return state, manager


def test_unknown_tools_are_denied_by_default(config):
    _, manager = config

    decision = manager.authorize("delete_everything")

    assert decision.allowed is False
    assert "denied by default" in decision.reason
    assert tool_is_known("delete_everything") is False
    assert risk_for("delete_everything") is RiskLevel.HIGH


def test_read_tools_are_allowed(config):
    _, manager = config

    decision = manager.authorize("list_windows")

    assert decision.allowed is True
    assert decision.risk is RiskLevel.READ
    assert decision.requires_confirmation is False


def test_high_risk_requires_confirmation(config):
    _, manager = config
    layer = SecurityLayer(confirm_callback=None, manager=manager)

    denied = layer.authorize("run_command", {"cmd": "dir"})

    assert denied.allowed is False
    assert "confirmation" in denied.reason

    layer = SecurityLayer(confirm_callback=lambda tool, args, message: False, manager=manager)
    assert layer.authorize("run_command", {}).allowed is False

    layer = SecurityLayer(confirm_callback=lambda tool, args, message: True, manager=manager)
    allowed = layer.authorize("browser_submit", {"selector": "Send"})

    assert allowed.allowed is True
    assert "confirmation" in allowed.reason


def test_confirmation_grants_the_tool_for_the_session(config):
    _, manager = config
    prompts = []
    layer = SecurityLayer(
        confirm_callback=lambda tool, args, message: prompts.append(message) or True,
        manager=manager,
    )

    first = layer.authorize("run_command", {})
    second = layer.authorize("run_command", {})

    assert first.allowed is True
    assert second.allowed is True
    assert len(prompts) == 1
    assert "run_command" in manager.session_grants()


def test_settings_permissions_are_enforced(config):
    state, manager = config
    state["permissions"]["allow_open_app"] = False

    decision = manager.authorize("launch_app", {"name": "Spotify"})

    assert decision.allowed is False
    assert "allow_open_app" in decision.reason


def test_model_arguments_cannot_grant_permissions(config):
    state, manager = config
    state["permissions"]["allow_browser_automation"] = False

    decision = manager.authorize(
        "browser_submit",
        {"allow": True, "risk": "read", "permissions": {"all": True}},
    )

    assert decision.allowed is False


def test_record_result_classifies_outcomes_in_the_audit_trail(monkeypatch):
    logged = []
    monkeypatch.setattr(
        audit_module.db,
        "log_action",
        lambda tool, args, result, approved: logged.append((tool, args, result, approved)),
    )
    security = SecurityLayer()

    security.record_result("find_app", {"name": "chrome"}, "Chrome is installed.")
    security.record_result("open_app", {"name": "Chrome"}, "Denied: not allowed")

    ok_entry = logged[-2][1]
    failed_entry = logged[-1][1]
    assert ok_entry["outcome"] == {"ok": True, "error": ""}
    assert failed_entry["outcome"] == {
        "ok": False,
        "error": "Denied: not allowed",
    }


def test_audit_redacts_secrets(monkeypatch):
    logged = []
    monkeypatch.setattr(
        audit_module.db,
        "log_action",
        lambda tool, args, result, approved: logged.append((tool, args, result, approved)),
    )

    entry = audit_module.audit(
        "run_command",
        RiskLevel.HIGH,
        {
            "cmd": "curl -H 'Authorization: Bearer secret-token-123'",
            "password": "hunter2",
            "nested": {"api_key": "sk-live-abc123", "note": "safe"},
        },
        Decision(True, RiskLevel.HIGH, "ok"),
        result="done",
    )

    assert logged
    tool, logged_entry, result, approved = logged[0]
    serialized = repr(logged_entry)
    assert "hunter2" not in serialized
    assert "secret-token-123" not in serialized
    assert "sk-live-abc123" not in serialized
    assert logged_entry["arguments"]["nested"]["note"] == "safe"
    assert "redacted" in serialized
    assert entry["arguments"]["password"] == "[redacted]"


def test_path_validation_blocks_traversal_and_sensitive_files(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    (allowed / ".env").write_text("x", encoding="utf-8")
    (allowed / "server.pem").write_text("x", encoding="utf-8")

    assert validate_path(allowed / "ok.txt", [allowed])

    with pytest.raises(ValidationError):
        validate_path(outside, [allowed])
    with pytest.raises(ValidationError):
        validate_path(allowed / ".env", [allowed])
    with pytest.raises(ValidationError):
        validate_path(allowed / "server.pem", [allowed])
    with pytest.raises(ValidationError):
        validate_path(r"C:\Windows\System32\config\SAM")
    with pytest.raises(ValidationError):
        validate_path("", [allowed])


def test_command_and_text_validation():
    assert validate_command(["python", "-m", "pytest"]) == ["python", "-m", "pytest"]

    with pytest.raises(ValidationError):
        validate_command("python -m pytest")
    with pytest.raises(ValidationError):
        validate_command(["powershell", "-Command", "dir"])

    assert validate_text("hello") == "hello"
    with pytest.raises(ValidationError):
        validate_text(123)
    with pytest.raises(ValidationError):
        validate_text("line\x00break")
    with pytest.raises(ValidationError):
        validate_text("x" * 10, max_length=5)


def test_wrap_tools_enforces_security(config):
    _, manager = config
    layer = SecurityLayer(confirm_callback=lambda *args: True, manager=manager)
    handler = Mock(return_value="executed")
    tools = [
        {"name": "installed_apps", "fn": handler, "confirm": False, "spec": {}},
        {"name": "run_command", "fn": Mock(return_value="should not run"), "confirm": True, "spec": {}},
    ]

    wrapped = layer.wrap_tools(tools)

    assert wrapped[0]["fn"]() == "executed"
    assert wrapped[1]["fn"](cmd="dir") == "should not run"
    handler.assert_called_once()

    denied_layer = SecurityLayer(confirm_callback=None, manager=PermissionManager(
        load_config=manager._load_config
    ))
    denied = denied_layer.wrap_tools([{"name": "run_command", "fn": handler, "spec": {}}])
    assert denied[0]["fn"](cmd="dir").startswith("Denied:")
    assert handler.call_count == 1


def test_redact_value_handles_collections():
    redacted = redact_value({
        "items": [{"token": "abc", "safe": "value"}],
        "cookie": "sessionid=123",
    })

    assert redacted["cookie"] == "[redacted]"
    assert redacted["items"][0]["token"] == "[redacted]"
    assert redacted["items"][0]["safe"] == "value"


def test_screen_control_tools_are_known_and_permission_gated():
    from himari.security.policies import (
        NEVER_SESSION_GRANT,
        confirmation_required_for,
        permission_key_for,
    )

    assert tool_is_known("generate_image") is False
    for tool in (
        "list_controls",
        "click_control",
        "set_control_text",
        "type_text",
        "press_keys",
        "click_at",
        "scroll_screen",
    ):
        assert tool_is_known(tool) is True
        assert permission_key_for(tool) == "allow_screen_control"

    assert risk_for("list_controls") is RiskLevel.READ
    assert risk_for("click_control") is RiskLevel.HIGH
    assert confirmation_required_for("click_control") is True
    assert confirmation_required_for("press_keys") is True
    assert "press_keys" in NEVER_SESSION_GRANT

def test_wait_for_decision_requires_an_explicit_yes():
    import threading

    from himari.security import wait_for_decision

    unanswered = {"allowed": True, "event": threading.Event()}
    assert wait_for_decision(unanswered, timeout=0.01) is False

    approved = {"allowed": True, "event": threading.Event()}
    approved["event"].set()
    assert wait_for_decision(approved, timeout=0.01) is True

    denied = {"allowed": False, "event": threading.Event()}
    denied["event"].set()
    assert wait_for_decision(denied, timeout=0.01) is False

    assert wait_for_decision(None, timeout=0.01) is False


def test_shutdown_releases_pending_confirmations_fail_closed():
    import threading

    from himari.security import (
        new_decision,
        release_pending_confirmations,
        wait_for_decision,
    )

    result = new_decision()
    answers = []
    waiter = threading.Thread(
        target=lambda: answers.append(wait_for_decision(result, timeout=5))
    )
    waiter.start()

    assert release_pending_confirmations() >= 1
    waiter.join(timeout=5)

    assert not waiter.is_alive()
    assert answers == [False]
    assert result["allowed"] is False


def test_resolved_decisions_are_not_released_again():
    from himari.security import (
        new_decision,
        release_pending_confirmations,
        resolve_decision,
        wait_for_decision,
    )

    result = new_decision()
    resolve_decision(result, True)

    assert wait_for_decision(result, timeout=0.01) is True
    release_pending_confirmations()
    assert result["allowed"] is True


def test_security_layer_reports_pending_confirmation(config):
    _, manager = config
    seen = []
    layer = SecurityLayer(
        confirm_callback=lambda *args: True,
        manager=manager,
        on_confirmation=lambda tool, risk, reason: seen.append((tool, str(risk))),
    )

    decision = layer.authorize("run_command", {"cmd": "dir"})

    assert decision.allowed is True
    assert seen == [("run_command", "high")]
