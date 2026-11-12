"""Conversational and avatar state for the personality layer."""

import time
from dataclasses import dataclass, field
from enum import Enum


class Mode(str, Enum):
    CONVERSATION = "conversation"
    TECHNICAL = "technical"


class AvatarExpression(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    HAPPY = "happy"
    CONFUSED = "confused"
    SAD = "sad"
    ERROR = "error"


MAX_HISTORY = 20


@dataclass
class PersonalityState:
    expression: AvatarExpression = AvatarExpression.IDLE
    mode: Mode = Mode.CONVERSATION
    history: list = field(default_factory=list)

    def set_mode(self, mode):
        try:
            self.mode = mode if isinstance(mode, Mode) else Mode(str(mode))
        except ValueError:
            self.mode = Mode.CONVERSATION
        return self.mode

    def transition(self, expression, reason=""):
        """Move to a known expression and record the change.

        Returns the new expression, or None when the value is not a supported
        avatar state. The state is never left invalid.
        """
        try:
            target = (
                expression
                if isinstance(expression, AvatarExpression)
                else AvatarExpression(str(expression or "").strip().casefold())
            )
        except ValueError:
            return None
        if target is self.expression:
            return None
        self.expression = target
        self._record(target, reason)
        return target

    def reset(self):
        self.expression = AvatarExpression.IDLE
        self.history.clear()
        return self.expression

    def _record(self, expression, reason):
        self.history.append({
            "expression": expression.value,
            "reason": str(reason)[:200],
            "ts": time.time(),
        })
        if len(self.history) > MAX_HISTORY:
            del self.history[:-MAX_HISTORY]

    def to_dict(self):
        return {
            "expression": self.expression.value,
            "mode": self.mode.value,
            "history": list(self.history),
        }
