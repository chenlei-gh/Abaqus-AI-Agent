from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class SensitivityCase:
    name: str
    parameters: Dict[str, Any]
    model_name: Optional[str] = None
    job_name: Optional[str] = None


@dataclass(frozen=True)
class SensitivityResult:
    case: SensitivityCase
    values: Dict[str, float]
    relative_changes: Dict[str, float]
    status: str = "completed"
    execution_status: str = "completed"
    result_status: str = "available"
    acceptance_status: str = "not_evaluated"
    diagnostics: Tuple[Dict[str, Any], ...] = ()

    def __post_init__(self):
        if self.status not in ("completed", "failed"):
            raise ValueError("status must be completed or failed")
        if self.execution_status not in ("completed", "failed"):
            raise ValueError("execution_status must be completed or failed")
        if self.result_status not in ("available", "unavailable", "error"):
            raise ValueError("result_status must be available, unavailable, or error")
        if self.acceptance_status not in ("not_evaluated", "passed", "failed"):
            raise ValueError("invalid acceptance_status")


@dataclass(frozen=True)
class SensitivityReport:
    baseline: Dict[str, float]
    cases: Tuple[SensitivityResult, ...] = ()
    ranking: Tuple[Tuple[str, float], ...] = ()

    @property
    def completed(self):
        """Return True only when execution and declared results completed.

        Sensitivity intentionally does not evaluate engineering Acceptance, so
        acceptance_status remains "not_evaluated" unless a caller supplies
        that separate evidence explicitly.
        """
        return all(
            c.status == "completed"
            and c.execution_status == "completed"
            and c.result_status == "available"
            for c in self.cases
        )

    @property
    def failed_cases(self):
        return tuple(c for c in self.cases if c.status != "completed")
