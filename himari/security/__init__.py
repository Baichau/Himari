"""Centralized security used by every tool and the agent.

All tool execution passes through SecurityLayer.authorize(). The layer is
fail-closed: unknown tools are denied, high-risk tools require explicit user
confirmation, and every decision is audited with secrets redacted.
"""

from .audit import audit, redact_value
from .confirmation import ConfirmationRequest, require_confirmation
from .permissions import Decision, PermissionManager, RiskLevel, SecurityContext
from .policies import risk_for, tool_is_known
from .validation import ValidationError, validate_command, validate_path, validate_text


class SecurityLayer:
    def __init__(self, confirm_callback=None, manager=None):
        self.permissions = manager or PermissionManager()
        self.confirm_callback = confirm_callback

    def authorize(self, tool, arguments=None):
        decision = self.permissions.authorize(tool, arguments)
        if not decision.allowed:
            audit(tool, decision.risk, arguments, decision)
            return decision
        if decision.requires_confirmation:
            request = ConfirmationRequest(
                tool=tool,
                risk=decision.risk,
                reason=decision.reason,
                arguments=arguments or {},
            )
            approved = require_confirmation(
                request, self.confirm_callback, self.permissions
            )
            if not approved:
                denied = Decision(
                    False,
                    decision.risk,
                    "User denied the action or confirmation was unavailable.",
                )
                audit(tool, denied.risk, arguments, denied)
                return denied
            decision = Decision(
                True, decision.risk, "Allowed after user confirmation."
            )
        audit(tool, decision.risk, arguments, decision)
        return decision

    def record_result(self, tool, arguments, result):
        decision = Decision(True, risk_for(tool), "Executed.")
        audit(tool, decision.risk, arguments, decision, result=result)

    def wrap_tools(self, tools):
        """Return TOOLS-compatible entries whose handlers pass through security."""
        wrapped = []
        for tool in tools:
            handler = tool["fn"]
            name = tool["name"]

            def guarded(*args, _handler=handler, _name=name, **kwargs):
                decision = self.authorize(_name, kwargs)
                if not decision.allowed:
                    return f"Denied: {decision.reason}"
                try:
                    return _handler(*args, **kwargs)
                except Exception as exc:
                    return f"Tool error: {exc}"

            entry = dict(tool)
            entry["fn"] = guarded
            entry["confirm"] = False
            wrapped.append(entry)
        return wrapped


__all__ = [
    "Decision",
    "PermissionManager",
    "RiskLevel",
    "SecurityContext",
    "SecurityLayer",
    "ValidationError",
    "ConfirmationRequest",
    "audit",
    "redact_value",
    "risk_for",
    "tool_is_known",
    "validate_command",
    "validate_path",
    "validate_text",
]