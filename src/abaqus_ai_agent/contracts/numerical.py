from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class NumericalVerificationResult:
    name: str
    status: str
    error: float
    tolerance: float
    points: Tuple[float, ...] = ()
    method: str = "successive_relative_change"
    message: str = ""
    observed_order: Optional[float] = None
    extrapolated_value: Optional[float] = None
    gci: Optional[float] = None

    @property
    def passed(self):
        return self.status == "converged" and self.error <= self.tolerance


@dataclass(frozen=True)
class NumericalRefinementCase:
    name: str
    refinement_value: float
    action_plan: Tuple[Any, ...] = ()
    model_name: Optional[str] = None
    job_name: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if not self.name:
            raise ValueError("refinement case name is required")
        if self.refinement_value <= 0:
            raise ValueError("refinement_value must be > 0")
        if self.action_plan is None:
            raise ValueError("action_plan must be a tuple; use () when no plan is declared")
        object.__setattr__(self, "metadata", dict(self.metadata or {}))


@dataclass(frozen=True)
class NumericalRefinementReport:
    name: str
    dimension: str
    cases: Tuple[NumericalRefinementCase, ...]
    values: Tuple[float, ...]
    verification: NumericalVerificationResult
    runs: Tuple[Dict[str, Any], ...] = ()

    @property
    def passed(self):
        return self.verification.passed and all(
            run.get("status") == "completed" for run in self.runs
        )

    @property
    def failed_cases(self):
        return tuple(run for run in self.runs if run.get("status") != "completed")
