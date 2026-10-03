from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class CapabilityStatus(str, Enum):
    """What the Agent can legitimately claim about an engineering operation."""

    SUPPORTED = "supported"
    ASSISTED = "assisted"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    EXECUTABLE = "executable_unverified"


@dataclass(frozen=True)
class CapabilityResult:
    """Standardized cross-cutting boundary contract across GA modules.
    
    Prevents ambiguous capabilities by requiring explicit status, clear reasoning,
    optional evidence, and actionable next steps.
    """

    capability: str
    status: CapabilityStatus
    reason: str
    evidence: Optional[Dict[str, Any]] = None
    required_user_input: Optional[str] = None
    next_action: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_supported(self) -> bool:
        return self.status == CapabilityStatus.SUPPORTED

    @property
    def is_blocked(self) -> bool:
        return self.status == CapabilityStatus.BLOCKED

    @property
    def needs_assistance(self) -> bool:
        return self.status == CapabilityStatus.ASSISTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "reason": self.reason,
            "evidence": dict(self.evidence) if self.evidence is not None else None,
            "required_user_input": self.required_user_input,
            "next_action": self.next_action,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityResult":
        st_raw = data.get("status", "unsupported")
        try:
            status = CapabilityStatus(st_raw)
        except (ValueError, TypeError):
            status = CapabilityStatus.UNSUPPORTED

        return cls(
            capability=str(data.get("capability", "unknown")),
            status=status,
            reason=str(data.get("reason", "")),
            evidence=data.get("evidence"),
            required_user_input=data.get("required_user_input"),
            next_action=data.get("next_action"),
            metadata=dict(data.get("metadata", {})),
        )
