from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class EngineeringCheck:
    """One deterministic engineering sanity check."""
    name: str
    passed: bool
    actual: float = 0.0
    expected: float = 0.0
    tolerance: float = 0.0
    unit: str = ""
    message: str = ""
    evidence: Tuple[Dict[str, Any], ...] = ()


@dataclass(frozen=True)
class EngineeringCheckReport:
    checks: Tuple[EngineeringCheck, ...] = ()
    warnings: Tuple[str, ...] = ()

    @property
    def passed(self):
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def failed(self):
        return tuple(c for c in self.checks if not c.passed)
