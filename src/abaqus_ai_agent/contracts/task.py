from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .capability import CapabilityResolution
from .intent import EngineeringIntent


class TaskStatus(str, Enum):
    """Lifecycle status of a high-level engineering requirement task."""

    COMPLETED = "COMPLETED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class EngineeringTaskResult:
    """Consolidated end-to-end result of solve_requirement().

    Unifies the complete engineering task lifecycle:
    Natural Language / Intent -> Capability Routing -> Action Plan -> Preflight ->
    Execution / Solver -> Evidence V2 -> Acceptance -> Summary Card -> Engineering Report.
    """

    status: TaskStatus
    intent: Optional[EngineeringIntent] = None
    capability: Optional[CapabilityResolution] = None
    plan: Optional[Any] = None
    run: Optional[Any] = None
    acceptance: Optional[Any] = None
    metrics: Tuple[Any, ...] = ()
    summary_card: Dict[str, Any] = field(default_factory=dict)
    report_markdown: Optional[str] = None
    clarification_prompt: Optional[str] = None
    errors: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_completed(self) -> bool:
        return self.status == TaskStatus.COMPLETED

    @property
    def needs_clarification(self) -> bool:
        return self.status == TaskStatus.NEEDS_CLARIFICATION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "intent_id": self.intent.id if self.intent else None,
            "capability_id": self.capability.capability_id if self.capability else None,
            "physics_domain": self.capability.physics_domain if self.capability else None,
            "acceptance_passed": getattr(self.acceptance, "passed", False) if self.acceptance else False,
            "engineering_status": getattr(self.run, "engineering_status", None) if self.run else None,
            "summary_card": dict(self.summary_card),
            "clarification_prompt": self.clarification_prompt,
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }
