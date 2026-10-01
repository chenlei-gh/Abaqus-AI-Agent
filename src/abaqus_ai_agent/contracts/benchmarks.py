from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    description: str
    expected_actions: Tuple[str, ...] = ()
    acceptance: Tuple[Dict[str, Any], ...] = ()
    tolerance: float = 0.0
    release: str = ""


@dataclass(frozen=True)
class BenchmarkResult:
    case: BenchmarkCase
    passed: bool
    observed: Dict[str, Any] = field(default_factory=dict)
    failures: Tuple[str, ...] = ()
    evidence: Tuple[Dict[str, Any], ...] = ()
