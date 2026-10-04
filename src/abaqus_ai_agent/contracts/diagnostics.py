"""P1.4 Solver Failure Diagnostics & Controlled Self-Healing Contracts."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..diagnostics.solver_patterns import DiagnosticIssue


class DiagnosticSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class RemediationCategory(str, Enum):
    BOUNDARY_CONDITION = "BOUNDARY_CONDITION"
    STEP_CONTROLS = "STEP_CONTROLS"
    CONTACT_STABILIZATION = "CONTACT_STABILIZATION"
    DAMPING = "DAMPING"
    MESH_REFINEMENT = "MESH_REFINEMENT"
    UNRESOLVED = "UNRESOLVED"


class RemediationRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class RemediationAction:
    """A concrete, auditable engineering change proposed to fix a diagnosed failure."""
    action_id: str
    category: RemediationCategory
    diagnosis_id: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    risk_level: RemediationRisk = RemediationRisk.LOW

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "category": self.category.value if hasattr(self.category, "value") else str(self.category),
            "diagnosis_id": self.diagnosis_id,
            "description": self.description,
            "parameters": dict(self.parameters),
            "rationale": self.rationale,
            "risk_level": self.risk_level.value if hasattr(self.risk_level, "value") else str(self.risk_level),
        }


@dataclass(frozen=True)
class HealingAttempt:
    """Record of a single self-healing iteration."""
    attempt_number: int
    trigger_issues: Tuple[str, ...]
    actions_applied: Tuple[RemediationAction, ...]
    pre_run_id: str
    post_run_id: str
    run_diff: Optional[Dict[str, Any]] = None
    outcome: str = "IN_PROGRESS"  # "ACCEPTED", "FAILED", "BLOCKED"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "trigger_issues": list(self.trigger_issues),
            "actions_applied": [a.to_dict() for a in self.actions_applied],
            "pre_run_id": self.pre_run_id,
            "post_run_id": self.post_run_id,
            "run_diff": self.run_diff,
            "outcome": self.outcome,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SelfHealingResult:
    """Consolidated report of an automated solver failure diagnosis and healing cycle."""
    healed: bool
    total_attempts: int
    initial_status: str
    final_status: str
    diagnosed_issues: Tuple[Any, ...] = ()
    remediations_applied: Tuple[RemediationAction, ...] = ()
    attempts: Tuple[HealingAttempt, ...] = ()
    final_run_diff: Optional[Dict[str, Any]] = None
    unresolved_issues: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healed": self.healed,
            "total_attempts": self.total_attempts,
            "initial_status": self.initial_status,
            "final_status": self.final_status,
            "diagnosed_issues": [iss.to_dict() for iss in self.diagnosed_issues],
            "remediations_applied": [r.to_dict() for r in self.remediations_applied],
            "attempts": [att.to_dict() for att in self.attempts],
            "final_run_diff": self.final_run_diff,
            "unresolved_issues": list(self.unresolved_issues),
            "metadata": dict(self.metadata),
        }
