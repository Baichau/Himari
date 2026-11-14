"""Agent orchestration: understand, plan, execute, observe, verify, recover.

The application owns execution. The model proposes a plan or one next action;
the orchestrator validates it, runs it through the security layer, checks the
observed outcome, and reports honestly what happened.
"""

import logging

from ..core.capabilities import CapabilityRegistry
from ..core.context import EnvironmentContext
from ..core.intent import Intent, IntentEngine
from ..core.reasoning import ReasoningController, choose
from ..security import SecurityLayer, risk_for
from ..tool_results import as_text
from .executor import Executor, classify_result
from .plan import STEP_DENIED, STEP_FAILED, STEP_SUCCEEDED
from .planner import SYSTEM_PROMPT, Planner
from .recovery import classify, decide, guidance
from .state import (
    AgentCancelledError,
    AgentState,
    AgentStatus,
    AgentStep,
    CancellationToken,
    StepStatus,
)
from .task import TaskRecord
from .tool_registry import ToolRegistry
from .verification import verify, verify_objective

log = logging.getLogger("himari.agent")

MAX_AGENT_ROUNDS = 5
OBSERVATION_LIMIT = 4000
ENVIRONMENT_CATEGORIES = {"app_control", "screen", "system", "music", "file", "development"}


class AgentOrchestrator:
    def __init__(
        self,
        registry=None,
        security=None,
        planner=None,
        executor=None,
        max_rounds=None,
        timeout_seconds=30,
        confirm_callback=None,
        on_status=None,
        intent_engine=None,
        environment=None,
        persist=False,
    ):
        self.registry = registry or ToolRegistry()
        self.security = security or SecurityLayer(confirm_callback=confirm_callback)
        self.planner = planner or Planner()
        self.executor = executor or Executor(
            security=self.security,
            registry=self.registry,
            timeout_seconds=timeout_seconds,
        )
        self.max_rounds = max_rounds
        self._rounds_explicit = max_rounds is not None
        self.on_status = on_status
        self.intent_engine = intent_engine or IntentEngine()
        self.environment = environment or EnvironmentContext()
        self.persist = persist
        try:
            self.capabilities = CapabilityRegistry(tools=self.registry.entries())
        except Exception as exc:
            log.warning("Capability registry unavailable: %s", exc)
            self.capabilities = None
        self.controller = ReasoningController(choose(Intent(objective=""), ""))
        self._active_state = None
        self._record = None

        previous_hook = getattr(self.security, "on_confirmation", None)

        def permission_notice(tool, risk, reason):
            if self._active_state is not None:
                self._set_status(
                    self._active_state,
                    AgentStatus.WAITING_FOR_PERMISSION,
                    f"Waiting for your permission to use {tool}.",
                )
            if previous_hook:
                previous_hook(tool, risk, reason)

        self.security.on_confirmation = permission_notice

    def run(self, task, token=None, history=None):
        token = token or CancellationToken()
        state = AgentState(
            task=str(task), max_rounds=self.max_rounds or MAX_AGENT_ROUNDS
        )
        self._active_state = state
        self._record = TaskRecord(state.task, state.task_id) if self.persist else None

        try:
            self._set_status(state, AgentStatus.UNDERSTANDING, "Understanding the request.")
            state.intent = self._understand(state.task, history)
            budget = choose(state.intent, state.task)
            state.profile = budget.profile
            state.max_rounds = (
                self.max_rounds
                if self._rounds_explicit
                else max(MAX_AGENT_ROUNDS, budget.max_rounds)
            )
            self.controller = ReasoningController(budget)
            state.context = self._environment_brief(state.intent, budget)
            specs = self._specs(state.intent)
            messages = self._messages(state, specs)
            self._persist(state)

            self._set_status(state, AgentStatus.PLANNING, "Deciding the next step.")
            plan = self._make_plan(state, specs, budget, token)
            if plan is not None:
                state.plan = plan
                messages.append({
                    "role": "system",
                    "content": "Execution plan:\n" + _plan_text(plan),
                })
                self._run_plan(state, plan, messages, specs, token)
            else:
                self._run_steps(state, messages, specs, token)
        except AgentCancelledError:
            self._finish(state, AgentStatus.CANCELLED, "The task was cancelled.")
        except Exception as exc:
            log.warning("Agent task failed: %s", exc)
            self._finish(state, AgentStatus.FAILED, f"Task failed: {exc}")
        finally:
            self._active_state = None
            self._persist(state)
            self._record = None

        self._emit(state, self._final_detail(state))
        return state

    # -- understanding -------------------------------------------------

    def _understand(self, task, history):
        try:
            return self.intent_engine.understand(task, history=history or (), use_model=False)
        except Exception as exc:
            log.warning("Intent understanding failed: %s", exc)
            return Intent(objective=task, category="chat")

    def _environment_brief(self, intent, budget):
        if budget.profile == "direct" and getattr(intent, "category", "") not in ENVIRONMENT_CATEGORIES:
            return {}
        try:
            snapshot = self.environment.snapshot(intent=intent)
            data = snapshot.to_dict() if hasattr(snapshot, "to_dict") else {}
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            log.debug("Environment snapshot failed: %s", exc)
            return {}

    def _specs(self, intent):
        if self.capabilities is None:
            return self.registry.specs()
        try:
            specs = self.capabilities.specs(intent)
        except Exception as exc:
            log.warning("Capability selection failed: %s", exc)
            specs = []
        return specs or self.registry.specs()

    def _messages(self, state, specs):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        context = []
        intent = state.intent
        if intent is not None:
            summary = intent.brief() if hasattr(intent, "brief") else ""
            context.append(f"Request understood as: {summary or intent.category}.")
            if getattr(intent, "expected_outcome", ""):
                context.append(f"Expected outcome: {intent.expected_outcome}")
            if getattr(intent, "constraints", None):
                context.append("Constraints: " + "; ".join(map(str, intent.constraints)))
            if getattr(intent, "ambiguity", None):
                context.append(
                    "Open questions: " + "; ".join(map(str, intent.ambiguity))
                    + ". Ask one focused question only if it blocks the work."
                )
        if state.context:
            lines = [f"{key}: {value}" for key, value in state.context.items() if value]
            if lines:
                context.append("Current environment:\n" + "\n".join(lines))
        if self.capabilities is not None:
            notes = self.capabilities.environment_notes()
            if notes:
                context.append("Availability notes:\n" + "\n".join(notes))
        if context:
            messages.append({"role": "system", "content": "\n\n".join(context)})
        messages.append({"role": "user", "content": state.task})
        return messages

    def _make_plan(self, state, specs, budget, token):
        if not budget.plan_first:
            return None
        maker = getattr(self.planner, "make_plan", None)
        if not callable(maker):
            return None
        try:
            plan = maker(state.task, specs, token=token, max_steps=max(2, budget.max_steps))
        except AgentCancelledError:
            raise
        except Exception as exc:
            log.warning("Plan generation failed, falling back to step mode: %s", exc)
            return None
        if plan is None:
            return None
        ok, errors = plan.validate()
        if not ok:
            log.warning("Rejected plan: %s", "; ".join(errors))
            return None
        plan.profile = state.profile
        return plan

    # -- execution modes ----------------------------------------------

    def _run_plan(self, state, plan, messages, specs, token):
        blocked = set()
        while not plan.is_complete() and state.rounds < state.max_rounds:
            token.check()
            plan.skip_blocked()
            ready = plan.ready()
            if not ready:
                break
            plan_step = ready[0]
            state.rounds += 1
            self._set_status(
                state, AgentStatus.PLANNING, f"Next step: {plan_step.objective}"
            )
            step = self._execute_action(
                state,
                plan_step.tool,
                plan_step.arguments,
                token,
                blocked,
                objective=plan_step.objective,
                plan_step_id=plan_step.id,
            )
            state.add_step(step)
            self._update_plan(plan, plan_step, step)

            if step.status is StepStatus.SUCCEEDED:
                self.controller.note_success()
            elif step.status is not StepStatus.DENIED:
                self.controller.note_failure()

            if step.status is StepStatus.DENIED:
                blocked.add(plan_step.tool)
            elif step.status is StepStatus.FAILED and (
                step.risk == "high"
                or (
                    step.verification
                    and step.verification.get("definitive")
                    and not step.verification.get("ok", True)
                )
            ):
                blocked.add(plan_step.tool)

            self._remember(messages, plan_step.tool, step, 0)
            self._set_status(state, AgentStatus.OBSERVING, self._observation_detail(step))
            self._persist(state)

        if not plan.is_complete():
            plan.skip_blocked()
        self._set_status(state, AgentStatus.VERIFYING, "Checking the result.")
        outcome = verify_objective(state.intent, state.steps)
        state.outcome = outcome.to_dict()
        state.final_answer = self._compose_report(state, plan)
        if plan.succeeded and outcome.ok:
            self._finish(state, AgentStatus.COMPLETED)
        elif plan.progress().get(STEP_SUCCEEDED):
            self._finish(
                state,
                AgentStatus.PARTIALLY_COMPLETED,
                "Some steps did not complete, so the objective is only partly done.",
            )
        else:
            self._finish(state, AgentStatus.FAILED, "No planned step completed successfully.")

    def _run_steps(self, state, messages, specs, token):
        blocked = set()
        while state.rounds < state.max_rounds:
            token.check()
            state.rounds += 1
            self._set_status(state, AgentStatus.PLANNING, "Deciding the next step.")
            action = self.planner.next_action(messages, specs, token=token)
            token.check()

            if action.get("type") == "final":
                self._finish_with_answer(state, action)
                return

            name = action.get("name")
            arguments = action.get("arguments")
            step = self._execute_action(
                state, name, arguments, token, blocked, objective=""
            )
            state.add_step(step)

            if step.status is StepStatus.SUCCEEDED:
                self.controller.note_success()
            elif step.status is not StepStatus.DENIED:
                self._note_failure_and_maybe_escalate(state, step)
            if step.status is StepStatus.DENIED:
                blocked.add(name)
            elif step.status is StepStatus.FAILED and step.risk == "high":
                blocked.add(name)
            elif (
                step.status is StepStatus.FAILED
                and step.verification
                and step.verification.get("definitive")
                and not step.verification.get("ok", True)
            ):
                blocked.add(name)

            self._remember(messages, name, step, action.get("ignored_calls", 0))
            state.status = AgentStatus.OBSERVING
            self._emit(state, self._observation_detail(step))
            self._persist(state)
        else:
            self._finish(
                state,
                AgentStatus.FAILED,
                f"Stopped after {state.max_rounds} tool rounds without a final answer.",
            )

    def _execute_action(
        self, state, name, arguments, token, blocked, objective="", plan_step_id=""
    ):
        risk = str(risk_for(name))
        step = AgentStep(
            index=len(state.steps) + 1,
            tool=str(name),
            arguments=arguments if isinstance(arguments, dict) else {},
            status=StepStatus.PENDING,
            risk=risk,
            objective=objective,
            plan_step_id=plan_step_id,
        )
        if name in blocked:
            step.status = StepStatus.DENIED
            step.error = (
                "This action was denied or failed earlier and will not be "
                "retried automatically. Choose a different approach."
            )
            step.recovery = decide(str(name), classify(step.error, denied=True)).to_dict()
            return step

        def started(_tool):
            self._set_status(state, AgentStatus.EXECUTING, f"Running {name}.")

        result = self.executor.execute(name, arguments, token=token, on_start=started)
        step.arguments = result.arguments
        step.status = result.status
        step.risk = result.risk
        step.result = result.result
        step.error = result.error

        if result.status in (StepStatus.SUCCEEDED, StepStatus.FAILED) and result.result is not None:
            check = verify(name, result.arguments, result.result)
            step.verification = check.to_dict()
            if result.status is StepStatus.SUCCEEDED and check.definitive and not check.ok:
                step.status = StepStatus.FAILED
                step.error = check.detail or "The intended outcome was not observed."

        if step.status is not StepStatus.SUCCEEDED:
            kind = classify(
                step.error,
                denied=step.status is StepStatus.DENIED,
                invalid=step.status is StepStatus.INVALID,
                verification_failed=(
                    step.status is StepStatus.FAILED
                    and bool(step.verification)
                    and step.verification.get("definitive")
                    and not step.verification.get("ok", True)
                ),
            )
            attempts = sum(1 for prior in state.steps if prior.tool == step.tool) + 1
            step.recovery = decide(
                str(name), kind, attempts=attempts, allowed_tools=self._allowed_tools()
            ).to_dict()
        return step

    def _allowed_tools(self):
        if self.capabilities is None:
            return None
        try:
            intent = self._active_state.intent if self._active_state else None
            return set(self.capabilities.names(intent))
        except Exception:
            return None

    def _update_plan(self, plan, plan_step, step):
        mapping = {
            StepStatus.SUCCEEDED: STEP_SUCCEEDED,
            StepStatus.DENIED: STEP_DENIED,
            StepStatus.INVALID: STEP_FAILED,
            StepStatus.FAILED: STEP_FAILED,
        }
        plan_step.attempts += 1
        plan.mark(
            plan_step.id,
            mapping.get(step.status, STEP_FAILED),
            result=step.result,
            error=step.error,
            verification=step.verification,
        )

    def _note_failure_and_maybe_escalate(self, state, step):
        self.controller.note_failure()
        if not self.controller.should_escalate():
            return
        budget = self.controller.escalate()
        state.profile = budget.profile
        if budget.max_rounds > state.max_rounds:
            state.max_rounds = budget.max_rounds
        recovery = step.recovery or {}
        self._set_status(
            state,
            AgentStatus.RECOVERING,
            f"{recovery.get('reason', 'The last step failed.')} "
            f"Raising the effort level to {budget.profile}.",
        )

    # -- reporting ----------------------------------------------------

    def _finish_with_answer(self, state, action):
        self._set_status(state, AgentStatus.VERIFYING, "Checking the result.")
        content = (action.get("content") or "").strip()
        if not content:
            self._finish(
                state,
                AgentStatus.FAILED,
                "The model returned an empty final answer, so the task is not verified.",
            )
            return
        outcome = verify_objective(state.intent, state.steps)
        state.outcome = outcome.to_dict()
        state.final_answer = content
        self._finish(state, AgentStatus.COMPLETED)

    def _compose_report(self, state, plan):
        if plan.succeeded:
            head = f"Completed: {state.task}"
            details = []
            for step in plan.steps:
                note = ""
                if isinstance(step.verification, dict) and step.verification.get("detail"):
                    note = f" {step.verification['detail']}"
                details.append(f"- {step.objective}: {step.status}.{note}".rstrip())
            return head + "\n" + "\n".join(details)
        counts = plan.progress()
        lines = [
            f"Partly completed: {state.task}",
            f"{counts.get(STEP_SUCCEEDED, 0)} of {len(plan.steps)} step(s) succeeded.",
        ]
        for step in plan.steps:
            if not step.succeeded:
                reason = step.error or step.status
                lines.append(f"- Not done — {step.objective}: {reason}")
        return "\n".join(lines)

    def _finish(self, state, status, error=""):
        state.finish(status, error)
        if self._record is not None:
            try:
                self._record.transition(status, error or state.final_answer)
                self._record.report = state.final_answer
                self._record.error = state.error
                self._record.steps = [step.to_dict() for step in state.steps]
                self._record.plan = state.plan.to_dict() if hasattr(state.plan, "to_dict") else {}
                self._record.profile = state.profile
                self._record.save()
            except Exception as exc:
                log.debug("Task record update failed: %s", exc)
        self._emit(state, self._final_detail(state))

    def _set_status(self, state, status, detail):
        state.status = status
        if self._record is not None:
            try:
                self._record.transition(status, detail)
            except Exception:
                pass
        self._emit(state, detail)

    @staticmethod
    def _remember(messages, name, step, ignored_calls):
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": step.arguments}}],
        })
        note = ""
        if ignored_calls:
            note = f" ({ignored_calls} additional tool call(s) were ignored.)"
        succeeded, error = classify_result(step.result)
        if step.status is StepStatus.DENIED:
            observation = f"Denied: {step.error}{note}"
        elif step.status is StepStatus.INVALID:
            observation = f"Invalid arguments: {step.error}{note}"
        elif step.status is StepStatus.FAILED:
            observation = f"Failed: {step.error or error}{note}"
        else:
            observation = f"Result: {as_text(step.result)}{note}"
        if step.verification:
            check = step.verification
            observation += (
                f" Verified: {check.get('detail')}"
                if check.get("ok")
                else f" Not verified: {check.get('detail')}"
            )
        if step.recovery:
            observation += " " + guidance(_RecoveryView(step.recovery), step.tool)
        messages.append({
            "role": "tool",
            "content": observation[:OBSERVATION_LIMIT],
            "tool_name": name,
        })

    @staticmethod
    def _observation_detail(step):
        label = step.status.value.capitalize()
        detail = f"Observed {step.tool}: {label}"
        if step.verification and not step.verification.get("ok", True):
            detail += f" — {step.verification.get('detail')}"
        return detail + (f" ({step.error})" if step.error and not step.verification else "")

    @staticmethod
    def _final_detail(state):
        if state.status is AgentStatus.COMPLETED:
            if state.verified:
                return "Task completed and every executed step succeeded."
            unverified = sum(
                1 for step in state.steps if step.status is not StepStatus.SUCCEEDED
            )
            return (
                f"Task completed, but {unverified} of {len(state.steps)} step(s) "
                "did not succeed, so the outcome is not fully verified."
            )
        if state.status is AgentStatus.PARTIALLY_COMPLETED:
            done = sum(1 for step in state.steps if step.status is StepStatus.SUCCEEDED)
            return (
                f"Task partly completed: {done} of {len(state.steps)} step(s) "
                "succeeded. Check the remaining steps before trusting the result."
            )
        if state.status is AgentStatus.CANCELLED:
            return "Task cancelled."
        if state.status is AgentStatus.WAITING_FOR_USER:
            return "Waiting for one detail from you."
        return f"Task failed: {state.error}"

    def _persist(self, state):
        if self._record is None:
            return
        try:
            self._record.status = state.status
            self._record.profile = state.profile
            self._record.intent = (
                state.intent.to_dict() if hasattr(state.intent, "to_dict") else {}
            )
            self._record.plan = state.plan.to_dict() if hasattr(state.plan, "to_dict") else {}
            self._record.steps = [step.to_dict() for step in state.steps]
            self._record.report = state.final_answer
            self._record.error = state.error
            self._record.save()
        except Exception as exc:
            log.debug("Task persistence failed: %s", exc)

    def _emit(self, state, detail):
        if not self.on_status:
            return
        plan = state.plan.to_dict() if hasattr(state.plan, "to_dict") else None
        event = {
            "task_id": state.task_id,
            "status": state.status.value,
            "round": state.rounds,
            "detail": detail,
            "verified": state.verified,
            "profile": state.profile,
            "plan": plan,
            "final_answer": state.final_answer,
            "steps": [step.to_dict() for step in state.steps],
        }
        try:
            self.on_status(event)
        except Exception as exc:
            log.warning("Agent status callback failed: %s", exc)


class _RecoveryView:
    """Adapter so stored recovery dicts can reuse guidance()."""

    def __init__(self, data):
        self.reason = str(data.get("reason") or "")
        self.alternatives = list(data.get("alternatives") or [])
        self.action = str(data.get("action") or "")


def _plan_text(plan):
    lines = []
    for step in plan.steps:
        deps = f" after {', '.join(step.depends_on)}" if step.depends_on else ""
        lines.append(f"- {step.id}{deps}: {step.objective} via {step.tool}")
    return "\n".join(lines)


def run_task(task, confirm_callback=None, on_status=None, token=None, history=None, **kwargs):
    """Convenience entry point used by the UI and tests."""
    orchestrator = AgentOrchestrator(
        confirm_callback=confirm_callback, on_status=on_status, **kwargs
    )
    return orchestrator.run(task, token=token, history=history)
