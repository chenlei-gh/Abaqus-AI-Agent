from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class UncertaintyParameter:
    name: str
    nominal: float
    lower: float
    upper: float
    unit: str = ""

    def __post_init__(self):
        if self.lower > self.nominal or self.nominal > self.upper:
            raise ValueError("uncertainty bounds must contain nominal value")


@dataclass(frozen=True)
class UncertaintyScenario:
    name: str
    parameters: Dict[str, float]


@dataclass(frozen=True)
class UncertaintyReport:
    scenarios: Tuple[UncertaintyScenario, ...] = ()
    outputs: Tuple[Dict[str, Any], ...] = ()
    method: str = "tolerance_bounds"
