"""Single-step tool execution behind the security layer."""

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field

from ..security import SecurityLayer, risk_for
from ..security.policies import tool_is_known
from .state import AgentCancelledError, StepStatus
from .tool_registry import ToolArgumentError, ToolRegistry, UnknownToolError

log = logging.getLogger("himari.agent.executor")

DEFAULT_STEP_TIMEOUT_SECONDS = 30

_FAILURE_PREFIXES = (
    "denied:",
    "tool error:",
    "permission denied",
    "invalid arguments",
    "unknown tool",
    "outside the configured allowed folders",
)


class ToolTimeoutError(RuntimeError):
    pass


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


def classify_result(result):
    """Never assume success: obvious failures become failed steps."""
    if result is None:
        return False, "The tool returned no result."
    if isinstance(result, dict) and result.get("ok") is False:
        return False, str(result.get("error") or "The tool reported failure.")
    if isinstance(result, str):
        text = result.strip()
        if not text:
            return False, "The tool returned an empty result."
        lowered = text.casefold()
        if lowered.startswith(_FAILURE_PREFIXES):
            return False, text
    return True, ""


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

    def execute(self, tool, arguments, token=None):
        if token is not None:
            token.check()

        risk = str(risk_for(tool)) if tool_is_known(tool) else "high"

        try:
            self.registry.get(tool)
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

        handler = self.registry.get(tool)["fn"]
        try:
            result = self._call(handler, validated)
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

    def _call(self, handler, arguments):
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(handler, **arguments)
        try:
            return future.result(timeout=self.timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            raise ToolTimeoutError(
                f"'{getattr(handler, '__name__', 'tool')}' did not finish within "
                f"{self.timeout_seconds} seconds and will not be retried automatically."
            )
        finally:
            pool.shutdown(wait=False)
