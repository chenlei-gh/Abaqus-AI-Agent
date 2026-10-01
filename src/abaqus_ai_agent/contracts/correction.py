from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class RepairCandidate:
    name: str
    diagnostic_class: str
    action: Dict[str, Any]
    rationale: str = ""
    requires_confirmation: bool = True


@dataclass(frozen=True)
class CorrectionAttempt:
    attempt: int
    diagnostic_class: str
    repair: Optional[str]
    status: str
    diagnostics: Tuple[Dict[str, Any], ...] = ()
    confirmed: bool = False
    retry_allowed: bool = False


@dataclass(frozen=True)
class CorrectionPolicy:
    max_attempts: int = 1
    allowed_diagnostics: Tuple[str, ...] = (
        "missing_output_request",
        "invalid_parameter",
    )

    def __post_init__(self):
        if self.max_attempts < 0:
            raise ValueError("max_attempts must be >= 0")
