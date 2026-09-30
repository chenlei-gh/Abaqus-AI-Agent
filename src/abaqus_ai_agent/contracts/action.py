from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AbaqusAction:
    """A proposed native Abaqus mutation, separate from execution."""
    action_type: str
    model_name: str
    target: Optional[str]
    parameters: Dict[str, Any]
    requires_confirmation: bool = True
