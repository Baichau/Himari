"""Himari's personality: persona, prompts, mode, and avatar expressions.

Tone only. The core safety and honesty prompt is always included, and this
package never changes permissions, the voice engine, or avatar assets.
"""

from .expressions import (
    AVATAR_STATES,
    EXPRESSIONS,
    duration_seconds,
    expr_from_status,
    is_transient,
    label_for,
    normalize_expression,
)
from .persona import DEFAULT_PERSONA, Persona, load_persona
from .prompts import (
    CORE_SYSTEM_PROMPT,
    build_messages,
    build_system_prompt,
    is_technical_request,
)
from .state import (
    AvatarExpression,
    Mode,
    PersonalityState,
)

__all__ = [
    "AVATAR_STATES",
    "AvatarExpression",
    "CORE_SYSTEM_PROMPT",
    "DEFAULT_PERSONA",
    "EXPRESSIONS",
    "Mode",
    "Persona",
    "PersonalityState",
    "build_messages",
    "build_system_prompt",
    "duration_seconds",
    "expr_from_status",
    "is_technical_request",
    "is_transient",
    "label_for",
    "load_persona",
    "normalize_expression",
]
