"""User confirmation requests for consequential actions."""

from dataclasses import dataclass

from .permissions import RiskLevel
from .policies import NEVER_SESSION_GRANT


@dataclass(frozen=True)
class ConfirmationRequest:
    tool: str
    risk: RiskLevel
    reason: str
    arguments: dict

    def message(self):
        return f"{self.reason} Action: {self.tool}. Allow it?"


def require_confirmation(request, callback, session_permissions=None):
    """Ask the user; fail closed when no callback is available.

    Only high-risk tools may be granted for the rest of the session, and
    submit-like actions always ask again.
    """
    if callback is None:
        return False
    try:
        approved = bool(callback(request.tool, request.arguments, request.message()))
    except Exception:
        return False
    if (
        approved
        and session_permissions is not None
        and request.risk is RiskLevel.HIGH
        and request.tool not in NEVER_SESSION_GRANT
    ):
        session_permissions.grant_session_permission(request.tool)
    return approved