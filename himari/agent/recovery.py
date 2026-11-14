"""Failure classification and recovery decisions.

The rule is deliberately conservative: a failed or uncertain *mutating* action
is never repeated automatically. The agent is told what went wrong and given a
different route, or the user is asked.
"""

from dataclasses import dataclass, field

from ..security import risk_for

PERMISSION = "permission"
INVALID = "invalid"
UNAVAILABLE = "unavailable"
TIMEOUT = "timeout"
NOT_FOUND = "not_found"
VERIFICATION = "verification"
UNKNOWN = "unknown"

ACTION_RETRY = "retry"
ACTION_ALTERNATIVE = "alternative"
ACTION_REPLAN = "replan"
ACTION_ESCALATE = "escalate"
ACTION_ASK_USER = "ask_user"
ACTION_STOP = "stop"

ALTERNATIVES = {
    "play_music": ["spotify_search", "now_playing", "open_app"],
    "spotify_search": ["research_web", "open_app"],
    "now_playing": ["media_control"],
    "weather_forecast": ["research_web", "search_web"],
    "open_app": ["find_app", "installed_apps"],
    "find_app": ["installed_apps", "app_registry"],
    "click_control": ["capture_screen_text", "screen_scene", "click_at"],
    "set_control_text": ["type_text", "press_keys"],
    "type_text": ["set_control_text"],
    "write_file": ["write_desktop_file"],
    "calendar_create": ["calendar_list"],
    "calendar_delete": ["calendar_list"],
    "research_web": ["search_web", "fetch_url"],
}

_MUTATING_HINTS = (
    "write", "create", "delete", "close", "launch", "open", "click", "type",
    "press", "set_", "control", "play", "install", "run_", "send", "focus",
)


@dataclass
class Recovery:
    action: str
    kind: str
    reason: str
    alternatives: list = field(default_factory=list)
    retry_allowed: bool = False

    def to_dict(self):
        return {
            "action": self.action,
            "kind": self.kind,
            "reason": self.reason,
            "alternatives": list(self.alternatives),
            "retry_allowed": self.retry_allowed,
        }


def classify(error="", *, denied=False, invalid=False, timed_out=False, verification_failed=False):
    text = str(error or "").casefold()
    if verification_failed:
        return VERIFICATION
    if denied or "denied" in text or "permission" in text or "disabled in settings" in text:
        return PERMISSION
    if invalid or "invalid" in text or "unknown tool" in text or "argument" in text:
        return INVALID
    if timed_out or "timed out" in text:
        return TIMEOUT
    if "not installed" in text or "unavailable" in text or "not available" in text:
        return UNAVAILABLE
    if "not found" in text or "no such" in text or "could not find" in text:
        return NOT_FOUND
    return UNKNOWN


def mutates(tool):
    name = str(tool or "")
    risk = str(risk_for(name)) if name else "high"
    return risk in {"medium", "high"} or any(hint in name for hint in _MUTATING_HINTS)


def alternatives_for(tool):
    return [alt for alt in ALTERNATIVES.get(str(tool or ""), []) if alt != tool]


def decide(tool, kind, attempts=1, allowed_tools=None):
    """Choose what the agent should do next. Never triggers an action."""
    allowed = set(allowed_tools) if allowed_tools is not None else None
    alts = alternatives_for(tool)
    if allowed is not None:
        alts = [alt for alt in alts if alt in allowed]

    if kind == PERMISSION:
        return Recovery(
            ACTION_STOP,
            kind,
            "The action is blocked by Settings or was denied; it will not be retried.",
        )
    if kind == INVALID:
        return Recovery(
            ACTION_REPLAN,
            kind,
            "The tool call was invalid; correct the arguments before trying again.",
            alts,
        )
    if kind == UNAVAILABLE:
        if alts:
            return Recovery(
                ACTION_ALTERNATIVE,
                kind,
                "The preferred method is unavailable; use a working alternative.",
                alts,
            )
        return Recovery(
            ACTION_ASK_USER,
            kind,
            "No working method is available for this action.",
        )
    if kind == TIMEOUT:
        if mutates(tool):
            return Recovery(
                ACTION_ASK_USER,
                kind,
                "The action timed out after it may have run, so repeating it could "
                "duplicate the effect. Check the current state first.",
                alts,
            )
        return Recovery(
            ACTION_RETRY if attempts < 2 else ACTION_ALTERNATIVE,
            kind,
            "The read-only request timed out.",
            alts,
            retry_allowed=attempts < 2,
        )
    if kind == VERIFICATION:
        if mutates(tool):
            return Recovery(
                ACTION_ALTERNATIVE,
                kind,
                "The call completed but the intended outcome was not observed. "
                "Do not repeat it blindly; inspect the state and use another method.",
                alts,
            )
        return Recovery(
            ACTION_ALTERNATIVE if alts else ACTION_REPLAN,
            kind,
            "The result did not confirm the expected outcome.",
            alts,
        )
    if kind == NOT_FOUND:
        return Recovery(
            ACTION_ALTERNATIVE if alts else ACTION_REPLAN,
            kind,
            "The target could not be found; resolve it differently or ask the user.",
            alts,
        )
    if mutates(tool):
        return Recovery(
            ACTION_ASK_USER,
            kind,
            "The action failed in an unclear way and will not be repeated automatically.",
            alts,
        )
    return Recovery(
        ACTION_RETRY if attempts < 2 else ACTION_STOP,
        kind,
        "The read-only call failed.",
        alts,
        retry_allowed=attempts < 2,
    )


def guidance(recovery, tool):
    """One short line the model can act on."""
    parts = [recovery.reason]
    if recovery.alternatives:
        parts.append("Alternatives: " + ", ".join(recovery.alternatives) + ".")
    if recovery.action == ACTION_ASK_USER:
        parts.append("Ask one focused question or stop and explain.")
    elif recovery.action == ACTION_REPLAN:
        parts.append("Produce a corrected next step.")
    elif recovery.action == ACTION_STOP:
        parts.append("Do not retry this action.")
    return " ".join(parts)
