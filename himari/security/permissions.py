"""Central permission checks.

The model never grants permissions: authorization only consults tool policy,
Settings permissions, and an explicit user confirmation callback.
"""

from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(Enum):
    READ = "read"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    def __str__(self):
        return self.value


@dataclass
class Decision:
    allowed: bool
    risk: RiskLevel
    reason: str
    requires_confirmation: bool = False

    def to_dict(self):
        return {
            "allowed": self.allowed,
            "risk": str(self.risk),
            "reason": self.reason,
            "requires_confirmation": self.requires_confirmation,
        }


class PermissionManager:
    def __init__(self, load_config=None):
        self._session_grants = set()
        self._load_config = load_config
        if self._load_config is None:
            from ..config import load as load_config

            self._load_config = load_config

    def _permissions(self):
        config = self._load_config()
        return config.get("permissions", {}) if isinstance(config, dict) else {}

    def session_grants(self):
        return set(self._session_grants)

    def grant_session_permission(self, tool):
        self._session_grants.add(tool)

    def revoke_session_permission(self, tool):
        self._session_grants.discard(tool)

    def authorize(self, tool, arguments=None):
        from .policies import (
            confirmation_required_for,
            permission_key_for,
            risk_for,
            tool_is_known,
        )

        if not tool_is_known(tool):
            return Decision(False, RiskLevel.HIGH, f"Unknown tool '{tool}' is denied by default.")
        risk = risk_for(tool)
        permission_key = permission_key_for(tool)
        if permission_key and not self._permissions().get(permission_key, False):
            return Decision(
                False,
                risk,
                f"Permission denied: '{permission_key}' is disabled in Settings.",
            )
        if (
            risk is RiskLevel.HIGH or confirmation_required_for(tool)
        ) and tool not in self._session_grants:
            return Decision(True, risk, "High-risk action requires confirmation.", True)
        if tool in self._session_grants:
            return Decision(True, risk, "Allowed by the current session grant.")
        return Decision(True, risk, "Allowed by policy.")


@dataclass
class SecurityContext:
    """Optional per-call context future modules can extend."""

    session: str = "default"
    metadata: dict = field(default_factory=dict)