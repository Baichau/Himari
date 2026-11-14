"""Structured execution plans.

A plan is a small dependency graph of executable steps. The model proposes it;
this module validates it, decides which steps are ready, and records outcomes.
Nothing here calls a tool or talks to the model.
"""

import re
import uuid
from dataclasses import dataclass, field

STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_SUCCEEDED = "succeeded"
STEP_FAILED = "failed"
STEP_DENIED = "denied"
STEP_SKIPPED = "skipped"
TERMINAL_STEP_STATUSES = {
    STEP_SUCCEEDED,
    STEP_FAILED,
    STEP_DENIED,
    STEP_SKIPPED,
}

PLAN_PROMPT = (
    "You are planning a Windows desktop task. Break the objective into the "
    "smallest number of real steps that each use one available tool.\n"
    "Return ONLY a JSON object, no prose, in this shape:\n"
    '{"objective": "...", "steps": [{"id": "s1", "objective": "...", '
    '"tool": "tool_name", "arguments": {...}, "depends_on": [], '
    '"expected": "observable result", "verify": "media_playing|app_running|'
    'file_exists|calendar_event|answer_present|result_ok"}]}\n'
    "Rules:\n"
    "- One tool per step, chosen only from the provided tools.\n"
    "- depends_on lists step ids that must succeed first. Independent steps "
    "may omit dependencies.\n"
    "- Do not invent tools, arguments, results, or permissions.\n"
    "- Keep the plan short; a single step is correct for a single action.\n"
    "- Verification describes how the outcome can be observed, not what the "
    "model hopes happened.\n"
)


def _clean_id(value, fallback):
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "")).strip("-")
    return text[:40] or fallback


@dataclass
class PlanStep:
    id: str
    objective: str
    tool: str = ""
    arguments: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)
    expected: str = ""
    verify: str = ""
    risk: str = "low"
    requires_approval: bool = False
    timeout_seconds: int = 0
    status: str = STEP_PENDING
    attempts: int = 0
    result: object = None
    error: str = ""
    verification: dict = field(default_factory=dict)

    @property
    def terminal(self):
        return self.status in TERMINAL_STEP_STATUSES

    @property
    def succeeded(self):
        return self.status == STEP_SUCCEEDED

    def to_dict(self):
        return {
            "id": self.id,
            "objective": self.objective,
            "tool": self.tool,
            "arguments": self.arguments,
            "depends_on": list(self.depends_on),
            "expected": self.expected,
            "verify": self.verify,
            "risk": self.risk,
            "requires_approval": self.requires_approval,
            "timeout_seconds": self.timeout_seconds,
            "status": self.status,
            "attempts": self.attempts,
            "result": self.result,
            "error": self.error,
            "verification": self.verification,
        }

    @classmethod
    def from_dict(cls, data, index=0):
        if not isinstance(data, dict):
            raise ValueError("Each plan step must be an object.")
        objective = str(
            data.get("objective") or data.get("title") or data.get("description") or ""
        ).strip()
        tool = str(data.get("tool") or data.get("capability") or "").strip()
        if not objective:
            objective = f"Run {tool}" if tool else ""
        if not objective:
            raise ValueError("A plan step needs an objective or a tool.")
        dependencies = data.get("depends_on") or data.get("dependencies") or []
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        if not isinstance(dependencies, list):
            raise ValueError("depends_on must be a list of step ids.")
        arguments = data.get("arguments") or data.get("input") or {}
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object.")
        verify = str(data.get("verify") or data.get("verification") or "").strip()
        return cls(
            id=_clean_id(data.get("id"), f"s{index + 1}"),
            objective=objective,
            tool=tool,
            arguments=arguments,
            depends_on=[str(d) for d in dependencies],
            expected=str(data.get("expected") or data.get("expected_output") or "").strip(),
            verify=verify,
            risk=str(data.get("risk") or "low"),
            requires_approval=bool(data.get("requires_approval", False)),
            timeout_seconds=int(data.get("timeout_seconds") or 0),
        )


@dataclass
class TaskPlan:
    objective: str
    steps: list = field(default_factory=list)
    profile: str = "guided"
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    notes: str = ""

    def add(self, step):
        if not isinstance(step, PlanStep):
            step = PlanStep.from_dict(step, len(self.steps))
        self.steps.append(step)
        return step

    def get(self, step_id):
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def validate(self):
        """Return (ok, errors). Never mutates the plan."""
        errors = []
        if not self.steps:
            errors.append("A plan needs at least one step.")
        seen = set()
        for step in self.steps:
            if step.id in seen:
                errors.append(f"Duplicate step id '{step.id}'.")
            seen.add(step.id)
            if step.id in step.depends_on:
                errors.append(f"Step '{step.id}' depends on itself.")
        for step in self.steps:
            missing = [dep for dep in step.depends_on if dep not in seen]
            if missing:
                errors.append(
                    f"Step '{step.id}' depends on unknown step(s): {', '.join(missing)}."
                )
        if not errors and self._has_cycle():
            errors.append("The plan's dependencies contain a cycle.")
        return (not errors, errors)

    def _has_cycle(self):
        by_id = {step.id: step for step in self.steps}
        visiting = set()
        done = set()

        def visit(step_id):
            if step_id in done:
                return False
            if step_id in visiting:
                return True
            visiting.add(step_id)
            step = by_id.get(step_id)
            for dep in step.depends_on if step else []:
                if visit(dep):
                    return True
            visiting.discard(step_id)
            done.add(step_id)
            return False

        return any(visit(step.id) for step in self.steps)

    def ready(self):
        """Pending steps whose dependencies have all succeeded."""
        done = {step.id for step in self.steps if step.succeeded}
        return [
            step
            for step in self.steps
            if step.status == STEP_PENDING and all(dep in done for dep in step.depends_on)
        ]

    def blocked(self):
        """Pending steps that can never run because a dependency ended badly."""
        dead = {
            step.id
            for step in self.steps
            if step.terminal and not step.succeeded
        }
        return [
            step
            for step in self.steps
            if step.status == STEP_PENDING
            and any(dep in dead for dep in step.depends_on)
        ]

    def skip_blocked(self):
        skipped = []
        while True:
            batch = self.blocked()
            if not batch:
                return skipped
            for step in batch:
                step.status = STEP_SKIPPED
                step.error = "A required earlier step did not succeed."
                skipped.append(step)

    def is_complete(self):
        return all(step.terminal for step in self.steps)

    @property
    def succeeded(self):
        return bool(self.steps) and all(step.succeeded for step in self.steps)

    def progress(self):
        counts = {status: 0 for status in (
            STEP_PENDING, STEP_RUNNING, STEP_SUCCEEDED, STEP_FAILED,
            STEP_DENIED, STEP_SKIPPED,
        )}
        for step in self.steps:
            counts[step.status] = counts.get(step.status, 0) + 1
        return counts

    def mark(self, step_id, status, result=None, error="", verification=None):
        step = self.get(step_id)
        if step is None:
            return None
        step.status = status
        step.result = result
        step.error = error or ""
        if verification is not None:
            step.verification = verification
        return step

    def to_dict(self):
        return {
            "plan_id": self.plan_id,
            "objective": self.objective,
            "profile": self.profile,
            "notes": self.notes,
            "steps": [step.to_dict() for step in self.steps],
            "progress": self.progress(),
            "valid": self.validate()[0],
        }

    @classmethod
    def from_json(cls, data, objective=""):
        if not isinstance(data, dict):
            raise ValueError("A plan must be a JSON object.")
        raw_steps = data.get("steps") or data.get("plan") or []
        if not isinstance(raw_steps, list):
            raise ValueError("'steps' must be a list.")
        plan = cls(
            objective=str(data.get("objective") or objective or "").strip(),
            profile=str(data.get("profile") or "guided"),
            notes=str(data.get("notes") or ""),
        )
        for index, raw in enumerate(raw_steps):
            plan.add(PlanStep.from_dict(raw, index))
        return plan

    def summary(self):
        counts = self.progress()
        parts = [
            f"{counts[STEP_SUCCEEDED]} succeeded",
            f"{counts[STEP_FAILED] + counts[STEP_DENIED]} failed",
        ]
        if counts[STEP_SKIPPED]:
            parts.append(f"{counts[STEP_SKIPPED]} skipped")
        if counts[STEP_PENDING]:
            parts.append(f"{counts[STEP_PENDING]} not run")
        return f"{len(self.steps)} step(s): " + ", ".join(parts)
