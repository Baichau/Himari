"""Task lifecycle and durable task records.

The record is what the UI shows and what lets a long task be inspected after a
restart. It stores state and reports, not hidden reasoning.
"""

import time
import uuid
from dataclasses import dataclass, field

from .state import AgentStatus

TERMINAL = {
    AgentStatus.COMPLETED,
    AgentStatus.PARTIALLY_COMPLETED,
    AgentStatus.FAILED,
    AgentStatus.CANCELLED,
}

ALLOWED = {
    AgentStatus.IDLE: {
        AgentStatus.UNDERSTANDING, AgentStatus.PLANNING, AgentStatus.EXECUTING,
        AgentStatus.WAITING_FOR_USER, AgentStatus.FAILED, AgentStatus.CANCELLED,
    },
    AgentStatus.UNDERSTANDING: {
        AgentStatus.PLANNING, AgentStatus.WAITING_FOR_USER, AgentStatus.COMPLETED,
        AgentStatus.FAILED, AgentStatus.CANCELLED,
    },
    AgentStatus.PLANNING: {
        AgentStatus.EXECUTING, AgentStatus.WAITING_FOR_PERMISSION,
        AgentStatus.WAITING_FOR_USER, AgentStatus.RECOVERING,
        AgentStatus.COMPLETED, AgentStatus.PARTIALLY_COMPLETED,
        AgentStatus.FAILED, AgentStatus.CANCELLED,
    },
    AgentStatus.EXECUTING: {
        AgentStatus.OBSERVING, AgentStatus.WAITING_FOR_PERMISSION,
        AgentStatus.RECOVERING, AgentStatus.VERIFYING,
        AgentStatus.FAILED, AgentStatus.CANCELLED,
    },
    AgentStatus.OBSERVING: {
        AgentStatus.VERIFYING, AgentStatus.EXECUTING, AgentStatus.PLANNING,
        AgentStatus.RECOVERING, AgentStatus.WAITING_FOR_PERMISSION,
        AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED,
    },
    AgentStatus.VERIFYING: {
        AgentStatus.COMPLETED, AgentStatus.PARTIALLY_COMPLETED,
        AgentStatus.RECOVERING, AgentStatus.PLANNING, AgentStatus.EXECUTING,
        AgentStatus.FAILED, AgentStatus.CANCELLED,
    },
    AgentStatus.RECOVERING: {
        AgentStatus.PLANNING, AgentStatus.EXECUTING, AgentStatus.WAITING_FOR_USER,
        AgentStatus.PARTIALLY_COMPLETED, AgentStatus.COMPLETED,
        AgentStatus.FAILED, AgentStatus.CANCELLED,
    },
    AgentStatus.WAITING_FOR_PERMISSION: {
        AgentStatus.EXECUTING, AgentStatus.PLANNING, AgentStatus.OBSERVING,
        AgentStatus.RECOVERING, AgentStatus.PARTIALLY_COMPLETED,
        AgentStatus.FAILED, AgentStatus.CANCELLED,
    },
    AgentStatus.WAITING_FOR_USER: {
        AgentStatus.PLANNING, AgentStatus.COMPLETED, AgentStatus.PARTIALLY_COMPLETED,
        AgentStatus.FAILED, AgentStatus.CANCELLED,
    },
}


def can_transition(current, target):
    if current in TERMINAL:
        return False
    return target in ALLOWED.get(current, set())


@dataclass
class TaskRecord:
    objective: str
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: AgentStatus = AgentStatus.IDLE
    profile: str = "direct"
    intent: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    steps: list = field(default_factory=list)
    report: str = ""
    error: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    history: list = field(default_factory=list)

    def transition(self, target, detail=""):
        if not isinstance(target, AgentStatus):
            target = AgentStatus(str(target))
        if target != self.status and not can_transition(self.status, target):
            raise ValueError(
                f"Cannot move task {self.task_id} from {self.status.value} "
                f"to {target.value}."
            )
        if target != self.status:
            self.status = target
            self.updated = time.time()
            self.history.append({
                "at": self.updated,
                "status": target.value,
                "detail": str(detail or "")[:500],
            })
        return self.status

    @property
    def finished(self):
        return self.status in TERMINAL

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "status": self.status.value,
            "profile": self.profile,
            "intent": self.intent,
            "plan": self.plan,
            "steps": self.steps,
            "report": self.report,
            "error": self.error,
            "created": self.created,
            "updated": self.updated,
            "history": self.history,
        }

    @classmethod
    def from_state(cls, state):
        return cls(
            objective=state.task,
            task_id=state.task_id,
            status=state.status,
            profile=getattr(state, "profile", "direct"),
            intent=state.intent.to_dict() if hasattr(state.intent, "to_dict") else {},
            plan=state.plan.to_dict() if hasattr(state.plan, "to_dict") else {},
            steps=[step.to_dict() for step in state.steps],
            report=state.final_answer,
            error=state.error,
            created=state.started,
            updated=time.time(),
        )

    def save(self):
        """Best-effort durable copy; never breaks a task if the DB is busy."""
        try:
            from .. import db

            db.save_task(
                self.task_id,
                self.objective,
                self.profile,
                self.status.value,
                self.to_dict(),
            )
            return True
        except Exception:
            return False

    @classmethod
    def load(cls, task_id):
        try:
            from .. import db

            data = db.load_task(task_id)
        except Exception:
            return None
        if not data:
            return None
        payload = data.get("payload")
        return cls.from_dict(payload if isinstance(payload, dict) and payload else data)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        try:
            status = AgentStatus(str(data.get("status") or "idle"))
        except ValueError:
            status = AgentStatus.FAILED
        return cls(
            objective=str(data.get("objective") or data.get("task") or ""),
            task_id=str(data.get("task_id") or ""),
            status=status,
            profile=str(data.get("profile") or "direct"),
            intent=data.get("intent") or {},
            plan=data.get("plan") or {},
            steps=data.get("steps") or [],
            report=str(data.get("report") or ""),
            error=str(data.get("error") or ""),
            created=float(data.get("created") or time.time()),
            updated=float(data.get("updated") or time.time()),
            history=data.get("history") or [],
        )
