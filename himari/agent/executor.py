"""Single-step tool execution behind the security layer."""

import logging
from dataclasses import dataclass, field

from ..security import SecurityLayer, risk_for
from ..security.policies import tool_is_known
from ..tool_exec import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    ToolTimeoutError,
    call as call_tool,
    timeout_for,
)
from ..tool_results import classify_result
from .state import AgentCancelledError, StepStatus
from .tool_registry import ToolArgumentError, ToolRegistry, UnknownToolError

log = logging.getLogger("himari.agent.executor")

DEFAULT_STEP_TIMEOUT_SECONDS = DEFAULT_TOOL_TIMEOUT_SECONDS


@dataclass
class ExecutionResult:
    tool: str
    arguments: dict
    status: StepStatus
    risk: str = "high"
    result: object = None
    error: str = ""
    timed_out: bool = False
    metadata: dict = field(default_factory=dict)

    @property
    def succeeded(self):
        return self.status is StepStatus.SUCCEEDED


class Executor:
    def __init__(
        self,
        security=None,
        registry=None,
        timeout_seconds=DEFAULT_STEP_TIMEOUT_SECONDS,
    ):
        self.security = security or SecurityLayer()
        self.registry = registry or ToolRegistry()
        self.timeout_seconds = timeout_seconds

    def execute(self, tool, arguments, token=None, on_start=None):
        if token is not None:
            token.check()

        risk = str(risk_for(tool)) if tool_is_known(tool) else "high"

        try:
            entry = self.registry.get(tool)
        except UnknownToolError:
            return ExecutionResult(
                tool,
                arguments if isinstance(arguments, dict) else {},
                StepStatus.DENIED,
                risk,
                error=f"Unknown tool '{tool}' is denied by default.",
            )

        try:
            validated = self.registry.validate_arguments(tool, arguments)
        except ToolArgumentError as exc:
            return ExecutionResult(
                tool,
                arguments if isinstance(arguments, dict) else {},
                StepStatus.INVALID,
                risk,
                error=str(exc),
            )

        decision = self.security.authorize(tool, validated)
        if not decision.allowed:
            return ExecutionResult(
                tool,
                validated,
                StepStatus.DENIED,
                str(decision.risk),
                error=decision.reason,
            )

        handler = entry["fn"]
        timeout = timeout_for(entry, self.timeout_seconds)
        if on_start is not None:
            on_start(tool)
        try:
            result = call_tool(handler, validated, timeout, tool)
        except ToolTimeoutError as exc:
            self.security.record_result(tool, validated, f"Timed out: {exc}")
            return ExecutionResult(
                tool,
                validated,
                StepStatus.FAILED,
                str(decision.risk),
                error=str(exc),
                timed_out=True,
            )
        except AgentCancelledError:
            raise
        except Exception as exc:
            self.security.record_result(tool, validated, f"Tool error: {exc}")
            return ExecutionResult(
                tool,
                validated,
                StepStatus.FAILED,
                str(decision.risk),
                error=f"Tool error: {exc}",
            )

        if token is not None:
            token.check()

        succeeded, error = classify_result(result)
        self.security.record_result(tool, validated, result)
        return ExecutionResult(
            tool,
            validated,
            StepStatus.SUCCEEDED if succeeded else StepStatus.FAILED,
            str(decision.risk),
            result=result,
            error=error,
        )
