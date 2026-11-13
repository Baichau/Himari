"""Audit logging with secret redaction.

Audit rows never contain passwords, tokens, API keys or other credential
material: sensitive keys are redacted and obvious secret values are masked.
"""

import re

from .. import db
from .permissions import RiskLevel

_SENSITIVE_KEYS = re.compile(
    r"(pass(word|phrase)?|token|secret|api[\s_-]?key|authorization|cookie|session|credential)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|sk-[a-z0-9]+|ghp_[a-z0-9]+|xox[bap]-[a-z0-9-]+)"
)
_REDACTED = "[redacted]"


def redact_value(value):
    if isinstance(value, dict):
        return {
            key: _REDACTED if _SENSITIVE_KEYS.search(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(_REDACTED, value)
    return value


def audit(tool, risk, arguments, decision, result=None, outcome=None):
    entry = {
        "risk": str(risk) if isinstance(risk, RiskLevel) else str(risk),
        "decision": decision.to_dict() if hasattr(decision, "to_dict") else decision,
        "arguments": redact_value(arguments or {}),
    }
    if outcome is not None:
        entry["outcome"] = outcome
    db.log_action(
        tool,
        entry,
        "denied" if hasattr(decision, "allowed") and not decision.allowed else (result or ""),
        bool(getattr(decision, "allowed", False)),
    )
    return entry