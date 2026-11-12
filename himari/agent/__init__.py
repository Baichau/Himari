"""Agent engine: bounded, verified, permission-aware task execution."""

from .executor import Executor, ExecutionResult, classify_result
from .orchestrator import MAX_AGENT_ROUNDS, AgentOrchestrator, run_task
from .planner import Planner
from .state import (
    AgentCancelledError,
    AgentError,
    AgentState,
    AgentStatus,
    AgentStep,
    CancellationToken,
    StepStatus,
)
from .tool_registry import (
    ToolArgumentError,
    ToolRegistry,
    UnknownToolError,
)

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
    "Planner",
    "StepStatus",
    "ToolArgumentError",
    "ToolRegistry",
    "UnknownToolError",
    "classify_result",
    "run_task",
]
