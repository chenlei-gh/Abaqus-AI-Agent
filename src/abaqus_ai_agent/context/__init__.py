"""State-Based Context Compaction & Three-Plane Engineering State Subsystem (P0-3).

NOT ENABLED ON THE SOLVE PATH. Static inspection found no product caller that
feeds this package into ``solve_requirement`` or report authorization. Absence
of a static import is not proof that a dynamic entry cannot reach it, so this
package is retained and marked unused. Do not describe it as part of the
running Agent loop, and do not delete it in this change.
"""

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
