from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ContactDiagnostic:
    name: str
    status: str
    value: Optional[float] = None
    limit: Optional[float] = None
    unit: str = ""
    message: str = ""


@dataclass(frozen=True)
class ContactDiagnosticReport:
    diagnostics: Tuple[ContactDiagnostic, ...] = ()

    @property
    def passed(self):
        return bool(self.diagnostics) and all(d.status == "pass" for d in self.diagnostics)
