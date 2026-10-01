from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class NumericalVerificationResult:
    name: str
    status: str
    error: float
    tolerance: float
    points: Tuple[float, ...] = ()
    message: str = ""

    @property
    def passed(self):
        return self.status == "converged" and self.error <= self.tolerance
