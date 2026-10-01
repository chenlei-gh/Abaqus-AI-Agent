from dataclasses import dataclass
from math import isfinite
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class UncertaintyParameter:
    name: str
    nominal: float
    lower: float
    upper: float
    unit: str = ""

    def __post_init__(self):
        if not self.name:
            raise ValueError("uncertainty parameter name is required")
        if not all(isfinite(float(value)) for value in (self.nominal, self.lower, self.upper)):
            raise ValueError("uncertainty parameter bounds must be finite")
        if self.lower > self.nominal or self.nominal > self.upper:
            raise ValueError("uncertainty bounds must contain nominal value")


@dataclass(frozen=True)
class UncertaintyScenario:
    name: str
    parameters: Dict[str, float]
    model_name: Optional[str] = None
    job_name: Optional[str] = None
    action_plan: Tuple[Any, ...] = ()

    def __post_init__(self):
        if not self.name:
            raise ValueError("uncertainty scenario name is required")
        for name, value in self.parameters.items():
            if not name:
                raise ValueError("uncertainty parameter name is required")
            if not isfinite(float(value)):
                raise ValueError("uncertainty scenario values must be finite")
        if self.action_plan is None:
            raise ValueError("action_plan must be a tuple; use () when no plan is declared")


@dataclass(frozen=True)
class UncertaintyReport:
    scenarios: Tuple[UncertaintyScenario, ...] = ()
    outputs: Tuple[Dict[str, Any], ...] = ()
    method: str = "tolerance_bounds"

    @property
    def completed(self):
        return bool(self.scenarios) and len(self.outputs) == len(self.scenarios) and all(
            output.get("status") == "completed" for output in self.outputs
        )

    @property
    def failed_cases(self):
        return tuple(
            output for output in self.outputs
            if output.get("status") != "completed"
        )
