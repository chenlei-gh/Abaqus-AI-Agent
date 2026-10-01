from dataclasses import dataclass
from typing import Any, Dict, Tuple

@dataclass(frozen=True)
class CalibrationObservation:
    name: str
    inputs: Any
    measured: float
    uncertainty: float = None
    def __post_init__(self):
        if not self.name: raise ValueError("calibration observation name is required")
        if not isinstance(self.measured, (int, float)): raise TypeError("measured value must be numeric")
        if self.uncertainty is not None and self.uncertainty <= 0: raise ValueError("uncertainty must be positive")

@dataclass(frozen=True)
class ParameterBound:
    name: str
    initial: float
    lower: float
    upper: float
    step: float
    def __post_init__(self):
        if not self.name: raise ValueError("parameter name is required")
        if self.lower > self.upper: raise ValueError("parameter lower bound exceeds upper bound")
        if not self.lower <= self.initial <= self.upper: raise ValueError("initial parameter value must be inside bounds")
        if self.step <= 0: raise ValueError("parameter step must be positive")

@dataclass(frozen=True)
class CalibrationResult:
    parameters: Dict[str, float]
    objective: float
    iterations: int
    converged: bool
    status: str
    residuals: Tuple[float, ...] = ()
    diagnostics: Tuple[Dict[str, Any], ...] = ()
