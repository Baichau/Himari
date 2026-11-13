"""Agent orchestration loop: interpret, plan, authorize, execute, observe, verify."""

import logging

from ..security import SecurityLayer, risk_for
from .executor import Executor, classify_result
from .planner import SYSTEM_PROMPT, Planner
from .state import (
    AgentCancelledError,
    AgentState,
    AgentStatus,
    AgentStep,
    CancellationToken,
    StepStatus,
)
from .tool_registry import ToolRegistry

log = logging.getLogger("himari.agent")

MAX_AGENT_ROUNDS = 5
OBSERVATION_LIMIT = 4000


class AgentOrchestrator:
    def __init__(
        self,
        registry=None,
        security=None,
        planner=None,
        executor=None,
        max_rounds=MAX_AGENT_ROUNDS,
        timeout_seconds=30,
        confirm_callback=None,
        on_status=None,
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
        self.on_status = on_status

        previous_hook = getattr(self.security, "on_confirmation", None)

        def permission_notice(tool, risk, reason):
            if self._active_state is not None:
                self._active_state.status = AgentStatus.WAITING_FOR_PERMISSION
                self._emit(self._active_state, f"Waiting for your permission to use {tool}.")
            if previous_hook:
                previous_hook(tool, risk, reason)

        self.security.on_confirmation = permission_notice

    _active_state = None

    def run(self, task, token=None):
        token = token or CancellationToken()
        state = AgentState(task=str(task), max_rounds=self.max_rounds)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": state.task},
        ]
        blocked = set()
        self._active_state = state
        state.status = AgentStatus.UNDERSTANDING
        self._emit(state, "Understanding the request.")

        try:
            for round_index in range(self.max_rounds):
                token.check()
                state.status = AgentStatus.PLANNING
                state.rounds = round_index + 1
                self._emit(state, "Deciding the next step.")

                plan = self.planner.next_action(
                    messages, self.registry.specs(), token=token
                )
                token.check()

                if plan.get("type") == "final":
                    self._finish_with_answer(state, plan)
                    break

                name = plan.get("name")
                arguments = plan.get("arguments")
                step = self._execute_plan(state, plan, name, arguments, token, blocked)
                state.add_step(step)

                if step.status is StepStatus.DENIED:
                    blocked.add(name)
                elif step.status is StepStatus.FAILED and step.risk == "high":
                    blocked.add(name)

                self._remember(messages, name, step, plan.get("ignored_calls", 0))
                state.status = AgentStatus.OBSERVING
                self._emit(state, self._observation_detail(step))
            else:
                state.finish(
                    AgentStatus.FAILED,
                    f"Stopped after {self.max_rounds} tool rounds without a final answer.",
                )
        except AgentCancelledError:
            state.finish(AgentStatus.CANCELLED, "The task was cancelled.")
        except Exception as exc:
            log.warning("Agent task failed: %s", exc)
            state.finish(AgentStatus.FAILED, f"Task failed: {exc}")
        finally:
            self._active_state = None

        self._emit(state, self._final_detail(state))
        return state

    def _execute_plan(self, state, plan, name, arguments, token, blocked):
        risk = str(risk_for(name))
        if name in blocked:
            return AgentStep(
                index=len(state.steps) + 1,
                tool=str(name),
                arguments=arguments if isinstance(arguments, dict) else {},
                status=StepStatus.DENIED,
                risk=risk,
                error=(
                    "This action was denied or failed earlier and will not be "
                    "retried automatically. Choose a different approach."
                ),
            )

        def started(_tool):
            state.status = AgentStatus.EXECUTING
            self._emit(state, f"Running {name}.")

        result = self.executor.execute(name, arguments, token=token, on_start=started)
        return AgentStep(
            index=len(state.steps) + 1,
            tool=str(name),
            arguments=result.arguments,
            status=result.status,
            risk=result.risk,
            result=result.result,
            error=result.error,
        )

    def _finish_with_answer(self, state, plan):
        state.status = AgentStatus.VERIFYING
        self._emit(state, "Checking the result.")
        content = (plan.get("content") or "").strip()
        if not content:
            state.finish(
                AgentStatus.FAILED,
                "The model returned an empty final answer, so the task is not verified.",
            )
            return
        state.final_answer = content
        state.finish(AgentStatus.COMPLETED)

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
            observation = f"Result: {step.result}{note}"
        messages.append({
            "role": "tool",
            "content": observation[:OBSERVATION_LIMIT],
            "tool_name": name,
        })

    @staticmethod
    def _observation_detail(step):
        label = step.status.value.capitalize()
        detail = f"Observed {step.tool}: {label}"
        return detail + (f" ({step.error})" if step.error else "")

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
        if state.status is AgentStatus.CANCELLED:
            return "Task cancelled."
        return f"Task failed: {state.error}"

    def _emit(self, state, detail):
        if not self.on_status:
            return
        event = {
            "task_id": state.task_id,
            "status": state.status.value,
            "round": state.rounds,
            "detail": detail,
            "verified": state.verified,
            "steps": [step.to_dict() for step in state.steps],
        }
        try:
            self.on_status(event)
        except Exception as exc:
            log.warning("Agent status callback failed: %s", exc)


def run_task(task, confirm_callback=None, on_status=None, token=None, **kwargs):
    """Convenience entry point used by the UI and tests."""
    orchestrator = AgentOrchestrator(
        confirm_callback=confirm_callback, on_status=on_status, **kwargs
    )
    return orchestrator.run(task, token=token)
