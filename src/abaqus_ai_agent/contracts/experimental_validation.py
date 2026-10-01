from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class ExperimentalObservation:
    """One measured quantity used to validate an analysis result."""
    name: str
    measured: float
    simulated: float
    tolerance: float
    unit: str = ""
    uncertainty: Optional[float] = None
    source: str = ""

    def __post_init__(self):
        if not self.name:
            raise ValueError("name is required")
        if self.tolerance < 0:
            raise ValueError("tolerance must be non-negative")
        if self.uncertainty is not None and self.uncertainty < 0:
            raise ValueError("uncertainty must be non-negative")


@dataclass(frozen=True)
class ExperimentalValidationResult:
    name: str
    measured: float
    simulated: float
    error: float
    relative_error: Optional[float]
    tolerance: float
    passed: bool
    unit: str = ""
    uncertainty: Optional[float] = None
    source: str = ""


@dataclass(frozen=True)
class ExperimentalValidationReport:
    results: Tuple[ExperimentalValidationResult, ...] = ()
    metadata: Dict[str, str] = field(default_factory=dict)

    @property
    def passed(self):
        return bool(self.results) and all(result.passed for result in self.results)

    @property
    def failed(self):
        return tuple(result for result in self.results if not result.passed)
