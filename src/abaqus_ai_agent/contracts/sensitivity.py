from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class SensitivityCase:
    name: str
    parameters: Dict[str, Any]


@dataclass(frozen=True)
class SensitivityResult:
    case: SensitivityCase
    values: Dict[str, float]
    relative_changes: Dict[str, float]
    status: str = "completed"


@dataclass(frozen=True)
class SensitivityReport:
    baseline: Dict[str, float]
    cases: Tuple[SensitivityResult, ...] = ()
    ranking: Tuple[Tuple[str, float], ...] = ()

    @property
    def completed(self):
        return all(c.status == "completed" for c in self.cases)
