"""Contracts for P1.2 Intent Reasoning, Engineering Plausibility & Tiered HITL."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .intent import EngineeringIntent


class InferenceRiskLevel(str, Enum):
    """Risk tier for inferred engineering parameters."""
    LOW = "LOW"          # Deterministic standardization (e.g. standard unit conversion, canonical alias)
    MEDIUM = "MEDIUM"    # Engineering heuristics (e.g. mesh size from bounding box, default Poisson's ratio)
    HIGH = "HIGH"        # Ambiguous or critical engineering assumptions (e.g. load direction, missing BCs)


class PlausibilitySeverity(str, Enum):
    """Severity of physical plausibility issues."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"  # Fail-closed blocker


class ReasoningStatus(str, Enum):
    """Outcome of intent reasoning and plausibility auditing."""
    RESOLVED = "RESOLVED"                  # All parameters fully specified or safely standardized
    ASSISTED = "ASSISTED"                  # Engineering heuristics applied (MEDIUM risk), execution permitted
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"  # Ambiguity or missing inputs requiring user response
    BLOCKED = "BLOCKED"                    # Physical impossibility or unconstrained rigid body motion


@dataclass(frozen=True)
class InferredParameter:
    """Audit record for an automatically inferred engineering parameter."""
    parameter_name: str
    inferred_value: Any
    original_value: Any = None
    source: str = "engineering_common_sense"
    confidence: float = 1.0
    risk_level: InferenceRiskLevel = InferenceRiskLevel.LOW
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter_name": self.parameter_name,
            "inferred_value": str(self.inferred_value),
            "original_value": str(self.original_value) if self.original_value is not None else None,
            "source": self.source,
            "confidence": self.confidence,
            "risk_level": self.risk_level.value,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class PlausibilityCheckResult:
    """Outcome of a single engineering consistency check."""
    check_name: str
    passed: bool
    severity: PlausibilitySeverity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_name": self.check_name,
            "passed": self.passed,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class IntentReasoningResult:
    """Comprehensive outcome of the P1.2 Intent Reasoning Engine."""
    status: ReasoningStatus
    enriched_intent: Optional[EngineeringIntent] = None
    inferred_mesh: Optional[Any] = None
    inferred_material: Optional[Dict[str, Any]] = None
    inferences: Tuple[InferredParameter, ...] = field(default_factory=tuple)
    plausibility_checks: Tuple[PlausibilityCheckResult, ...] = field(default_factory=tuple)
    clarification_prompt: Optional[str] = None
    blockers: Tuple[str, ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_executable(self) -> bool:
        """Whether the model is safe and well-posed for compilation and execution."""
        return self.status in (ReasoningStatus.RESOLVED, ReasoningStatus.ASSISTED)

    @property
    def has_high_risk_assumptions(self) -> bool:
        """Whether any inference carries HIGH risk level."""
        return any(inf.risk_level == InferenceRiskLevel.HIGH for inf in self.inferences)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "is_executable": self.is_executable,
            "inferences_count": len(self.inferences),
            "inferences": [inf.to_dict() for inf in self.inferences],
            "plausibility_checks": [c.to_dict() for c in self.plausibility_checks],
            "clarification_prompt": self.clarification_prompt,
            "blockers": list(self.blockers),
        }
