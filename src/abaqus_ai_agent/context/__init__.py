"""State-Based Context Compaction & Three-Plane Engineering State Subsystem (P0-3)."""

from .manager import (
    CompactedContext,
    StateBasedContextManager,
    ToolExecutionRecord,
)
from .state import (
    EngineeringState,
    ExecutionState,
    GeometryState,
    ModelState,
    VerificationState,
)

__all__ = [
    "CompactedContext",
    "EngineeringState",
    "ExecutionState",
    "GeometryState",
    "ModelState",
    "StateBasedContextManager",
    "ToolExecutionRecord",
    "VerificationState",
]
