"""User confirmation requests for consequential actions."""

import threading
from dataclasses import dataclass

from .permissions import RiskLevel
from .policies import NEVER_SESSION_GRANT

CONFIRMATION_TIMEOUT_SECONDS = 120

_PENDING = []
_PENDING_LOCK = threading.Lock()


@dataclass(frozen=True)
class ConfirmationRequest:
    tool: str
    risk: RiskLevel
    reason: str
    arguments: dict

    def message(self):
        return f"{self.reason} Action: {self.tool}. Allow it?"


def new_decision():
    """Create a fail-closed slot that shutdown can release."""
    result = {"allowed": False, "event": threading.Event()}
    with _PENDING_LOCK:
        _PENDING.append(result)
    return result


def _forget_decision(result):
    with _PENDING_LOCK:
        _PENDING[:] = [item for item in _PENDING if item is not result]


def resolve_decision(result, allowed):
    if not isinstance(result, dict):
        return
    result["allowed"] = bool(allowed)
    event = result.get("event")
    if event is not None:
        event.set()
    _forget_decision(result)


def release_pending_confirmations():
    """Deny every outstanding confirmation; used when Himari shuts down."""
    with _PENDING_LOCK:
        pending = list(_PENDING)
        _PENDING.clear()
    for result in pending:
        result["allowed"] = False
        event = result.get("event")
        if event is not None:
            event.set()
    return len(pending)


def wait_for_decision(result, timeout=CONFIRMATION_TIMEOUT_SECONDS):
    """Wait for a UI answer without blocking forever; anything uncertain is a no."""
    if not isinstance(result, dict):
        return False
    event = result.get("event")
    try:
        if event is None or not event.wait(timeout):
            return False
        return bool(result.get("allowed"))
    finally:
        _forget_decision(result)


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