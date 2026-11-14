"""Agent engine: bounded, verified, permission-aware task execution."""

from .executor import Executor, ExecutionResult, classify_result
from .orchestrator import MAX_AGENT_ROUNDS, AgentOrchestrator, run_task
from .plan import PlanStep, TaskPlan
from .planner import Planner
from .recovery import Recovery, classify as classify_failure, decide
from .state import (
    AgentCancelledError,
    AgentError,
    AgentState,
    AgentStatus,
    AgentStep,
    CancellationToken,
    StepStatus,
)
from .task import TaskRecord
from .tool_registry import (
    ToolArgumentError,
    ToolRegistry,
    UnknownToolError,
)
from .verification import Verification, verify, verify_objective

__all__ = [
    "AgentCancelledError",
    "AgentError",
    "AgentOrchestrator",
    "AgentState",
    "AgentStatus",
    "AgentStep",
    "CancellationToken",
    "ExecutionResult",
    "Executor",
    "MAX_AGENT_ROUNDS",
    "PlanStep",
    "Planner",
    "Recovery",
    "StepStatus",
    "TaskPlan",
    "TaskRecord",
    "ToolArgumentError",
    "ToolRegistry",
    "UnknownToolError",
    "Verification",
    "classify_failure",
    "classify_result",
    "decide",
    "run_task",
    "verify",
    "verify_objective",
]
