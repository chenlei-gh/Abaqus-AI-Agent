from dataclasses import dataclass
from typing import Optional, Tuple


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
