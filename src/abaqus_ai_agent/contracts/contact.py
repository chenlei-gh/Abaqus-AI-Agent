from dataclasses import dataclass
from typing import Optional, Tuple


CONTACT_STATES = ("contact", "open", "either")
DIAGNOSTIC_STATUSES = (
    "pass",
    "fail",
    "warning",
    "insufficient_evidence",
    "not_applicable",
    "ambiguous",
)


@dataclass(frozen=True)
class ExpectedContactBehavior:
    """Explicit engineering expectation used to interpret contact evidence.

    The contract deliberately contains no universal pressure, opening, or
    penetration limits. Any such limits are problem-specific and must be
    declared by the caller.
    """
    contact_required: bool = True
    expected_state: str = "contact"
    expected_regions: Tuple[str, ...] = ()
    expected_separation: Optional[float] = None
    allowed_initial_interference: Optional[float] = None
    required_outputs: Tuple[str, ...] = ("CSTATUS", "CPRESS", "COPEN")

    def __post_init__(self):
        if self.expected_state not in CONTACT_STATES:
            raise ValueError("expected_state must be contact, open, or either")
        if self.expected_separation is not None and self.expected_separation < 0:
            raise ValueError("expected_separation must be non-negative")
        if (
            self.allowed_initial_interference is not None
            and self.allowed_initial_interference < 0
        ):
            raise ValueError("allowed_initial_interference must be non-negative")
        if not self.required_outputs:
            raise ValueError("required_outputs must not be empty")
        outputs = set(self.required_outputs)
        if self.contact_required and "CSTATUS" not in outputs:
            raise ValueError(
                "CSTATUS is required when contact behavior is part of the contract"
            )
        if (
            self.expected_separation is not None
            and "COPEN" not in outputs
        ):
            raise ValueError(
                "COPEN is required when expected_separation is declared"
            )
        if (
            self.allowed_initial_interference is not None
            and "COPEN" not in outputs
        ):
            raise ValueError(
                "COPEN is required when allowed_initial_interference is declared"
            )


@dataclass(frozen=True)
class ContactDiagnostic:
    name: str
    status: str
    value: Optional[float] = None
    limit: Optional[float] = None
    unit: str = ""
    message: str = ""

    def __post_init__(self):
        if self.status not in DIAGNOSTIC_STATUSES:
            raise ValueError("unsupported contact diagnostic status: %s" % self.status)


@dataclass(frozen=True)
class ContactDiagnosticReport:
    diagnostics: Tuple[ContactDiagnostic, ...] = ()

    @property
    def passed(self):
        return bool(self.diagnostics) and all(
            d.status in ("pass", "not_applicable") for d in self.diagnostics
        )

    @property
    def failed(self):
        return tuple(
            d for d in self.diagnostics
            if d.status in ("fail", "insufficient_evidence", "ambiguous")
        )
