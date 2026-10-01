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
    diagnostics: Tuple[Dict[str, Any], ...] = ()


@dataclass(frozen=True)
class SensitivityReport:
    baseline: Dict[str, float]
    cases: Tuple[SensitivityResult, ...] = ()
    ranking: Tuple[Tuple[str, float], ...] = ()

    @property
    def completed(self):
        return all(c.status == "completed" for c in self.cases)

    @property
    def failed_cases(self):
        return tuple(c for c in self.cases if c.status != "completed")
