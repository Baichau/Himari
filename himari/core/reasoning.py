"""Adaptive reasoning depth.

Simple requests stay direct; multi-step or open-ended work gets a plan and a
larger budget. Escalation is a real change in planning, tool discovery,
verification and retry limits, not just a different system prompt.
"""

from dataclasses import dataclass, replace
from enum import Enum

from ..config import load
from .intent import Intent


class Profile(str, Enum):
    DIRECT = "direct"
    GUIDED = "guided"
    DEEP = "deep"


@dataclass(frozen=True)
class ReasoningBudget:
    profile: str = Profile.DIRECT.value
    max_rounds: int = 3
    max_steps: int = 3
    plan_first: bool = False
    verify_each_step: bool = True
    require_plan_approval: bool = False
    max_replans: int = 0
    escalate_after: int = 2

    def to_dict(self):
        return {
            "profile": self.profile,
            "max_rounds": self.max_rounds,
            "max_steps": self.max_steps,
            "plan_first": self.plan_first,
            "verify_each_step": self.verify_each_step,
            "require_plan_approval": self.require_plan_approval,
            "max_replans": self.max_replans,
        }


BUDGETS = {
    Profile.DIRECT.value: ReasoningBudget(),
    Profile.GUIDED.value: ReasoningBudget(
        profile=Profile.GUIDED.value,
        max_rounds=8,
        max_steps=8,
        plan_first=True,
        max_replans=1,
    ),
    Profile.DEEP.value: ReasoningBudget(
        profile=Profile.DEEP.value,
        max_rounds=16,
        max_steps=20,
        plan_first=True,
        max_replans=2,
        require_plan_approval=False,
    ),
}

_GUIDED_CATEGORIES = {"calendar", "app_control", "file", "screen", "system", "development"}
_READ_CATEGORIES = {"chat", "information", "research", "weather"}


def _config():
    try:
        config = load()
    except Exception:
        return {}
    section = config.get("reasoning", {}) if isinstance(config, dict) else {}
    return section if isinstance(section, dict) else {}


def choose(intent, text="", config=None):
    """Pick a reasoning budget for one understood request."""
    config = _config() if config is None else config
    override = str(config.get("profile") or "auto").strip().casefold()
    if override in BUDGETS:
        return BUDGETS[override]

    category = getattr(intent, "category", "chat")
    ambiguity = list(getattr(intent, "ambiguity", []) or [])
    multi_step = bool(getattr(intent, "multi_step", False))
    objective = str(getattr(intent, "objective", "") or text or "")

    budget = BUDGETS[Profile.DIRECT.value]
    if category == "deep_work" or category == "development":
        budget = BUDGETS[Profile.DEEP.value]
    elif multi_step or category in _GUIDED_CATEGORIES - {"system"}:
        budget = BUDGETS[Profile.GUIDED.value]
    elif ambiguity and getattr(intent, "requires_action", False):
        budget = BUDGETS[Profile.GUIDED.value]
    elif len(objective) > 220:
        budget = BUDGETS[Profile.GUIDED.value]
    elif category in _READ_CATEGORIES:
        budget = BUDGETS[Profile.DIRECT.value]

    try:
        configured_rounds = int(config.get("max_rounds", budget.max_rounds))
    except (TypeError, ValueError):
        configured_rounds = budget.max_rounds
    configured_rounds = max(1, min(configured_rounds, 30))
    return replace(budget, max_rounds=configured_rounds)


class ReasoningController:
    """Track outcomes and escalate when the current depth is not enough."""

    def __init__(self, budget):
        self.budget = budget
        self.failures = 0
        self.successes = 0
        self.escalations = 0

    def note_success(self):
        self.successes += 1

    def note_failure(self):
        self.failures += 1

    def should_escalate(self):
        if not _config().get("auto_escalate", True):
            return False
        return (
            self.failures >= max(1, self.budget.escalate_after)
            and self.budget.profile != Profile.DEEP.value
        )

    def escalate(self):
        order = (Profile.DIRECT.value, Profile.GUIDED.value, Profile.DEEP.value)
        current = self.budget.profile
        index = order.index(current) if current in order else 0
        next_profile = order[min(index + 1, len(order) - 1)]
        self.budget = BUDGETS[next_profile]
        self.escalations += 1
        self.failures = 0
        return self.budget

    def allows_step(self, step_count):
        return step_count < self.budget.max_steps
