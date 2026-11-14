"""Core orchestration primitives: intent, capabilities, context, reasoning.

These modules are deliberately free of UI and agent-loop dependencies so the
chat path, the task executor, and tests can all share them.
"""

from .capabilities import Capability, CapabilityRegistry, registry
from .context import EnvironmentContext, EnvironmentSnapshot
from .intent import Intent, IntentEngine, brief, parse_intent_json, rules_intent
from .reasoning import Profile, ReasoningBudget, ReasoningController, choose

__all__ = [
    "Capability",
    "CapabilityRegistry",
    "EnvironmentContext",
    "EnvironmentSnapshot",
    "Intent",
    "IntentEngine",
    "Profile",
    "ReasoningBudget",
    "ReasoningController",
    "brief",
    "choose",
    "parse_intent_json",
    "registry",
    "rules_intent",
]
