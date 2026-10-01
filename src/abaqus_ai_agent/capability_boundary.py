from dataclasses import dataclass
from enum import Enum

from .actions.script import action_to_script


class CapabilityStatus(str, Enum):
    """What the Agent can legitimately claim about an operation."""

    SUPPORTED = "supported"
    EXECUTABLE = "executable_unverified"
    ASSISTED = "assisted"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CapabilityBoundary:
    """Explicit boundary between AI reasoning and Agent authority."""

    status: CapabilityStatus
    action_type: str
    reason: str
    engineering_verified: bool = False

    @property
    def executable(self) -> bool:
        return self.status in (
            CapabilityStatus.SUPPORTED,
            CapabilityStatus.EXECUTABLE,
        )

    @property
    def formally_supported(self) -> bool:
        return self.status == CapabilityStatus.SUPPORTED


def classify_action(action) -> CapabilityBoundary:
    """Classify an AbaqusAction without inferring engineering correctness."""
    action_type = getattr(action, "action_type", None)
    if not action_type:
        raise TypeError("expected an action with action_type")

    if action_type == "python":
        return CapabilityBoundary(
            CapabilityStatus.EXECUTABLE,
            action_type,
            "native Abaqus Python escape hatch; domain semantics are not verified",
        )

    if isinstance(action_type, str):
        # Script generation is the existing executable registry. Do not
        # duplicate the action-type list in a second capability registry.
        script = action_to_script(action)
        if script is not None:
            return CapabilityBoundary(
                CapabilityStatus.SUPPORTED,
                action_type,
                "typed Agent Action; validation and execution are explicit",
            )

    return CapabilityBoundary(
        CapabilityStatus.UNSUPPORTED,
        str(action_type),
        "action type has no native Agent script path",
    )
