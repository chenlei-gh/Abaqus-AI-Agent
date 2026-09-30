from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class AbaqusAction:
    """A native Abaqus mutation with explicit pre/post conditions."""
    action_type: str
    model_name: str
    target: Optional[str]
    parameters: Dict[str, Any]
    requires_confirmation: bool = True
    preconditions: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    expected_state: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    evidence: Tuple[str, ...] = field(default_factory=tuple)
    rollback: Optional[Dict[str, Any]] = None

    def with_conditions(self, preconditions=(), expected_state=(), evidence=()):
        return AbaqusAction(
            action_type=self.action_type, model_name=self.model_name,
            target=self.target, parameters=dict(self.parameters),
            requires_confirmation=self.requires_confirmation,
            preconditions=tuple(preconditions),
            expected_state=tuple(expected_state),
            evidence=tuple(evidence), rollback=self.rollback)
