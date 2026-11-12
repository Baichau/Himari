"""Task and step state for the agent loop."""

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class AgentError(RuntimeError):
    pass


class AgentCancelledError(AgentError):
    pass


class AgentStatus(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    INVALID = "invalid"


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set()

    def check(self):
        if self._event.is_set():
            raise AgentCancelledError("The task was cancelled.")


@dataclass
class AgentStep:
    index: int
    tool: str
    arguments: dict
    status: StepStatus = StepStatus.PENDING
    risk: str = "high"
    result: object = None
    error: str = ""

    def to_dict(self):
        return {
            "index": self.index,
            "tool": self.tool,
            "arguments": self.arguments,
            "status": self.status.value,
            "risk": self.risk,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class AgentState:
    task: str
    status: AgentStatus = AgentStatus.IDLE
    steps: list = field(default_factory=list)
    rounds: int = 0
    max_rounds: int = 5
    final_answer: str = ""
    error: str = ""
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started: float = field(default_factory=time.time)
    finished: float = None

    def add_step(self, step):
        self.steps.append(step)
        return step

    def finish(self, status, error=""):
        self.status = status
        self.error = error
        self.finished = time.time()
        return self

    @property
    def verified(self):
        """True only when every executed step reported success."""
        return all(step.status is StepStatus.SUCCEEDED for step in self.steps)

    @property
    def duration_seconds(self):
        end = self.finished if self.finished is not None else time.time()
        return round(end - self.started, 3)

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "task": self.task,
            "status": self.status.value,
            "rounds": self.rounds,
            "max_rounds": self.max_rounds,
            "final_answer": self.final_answer,
            "error": self.error,
            "verified": self.verified,
            "duration_seconds": self.duration_seconds,
            "steps": [step.to_dict() for step in self.steps],
        }
