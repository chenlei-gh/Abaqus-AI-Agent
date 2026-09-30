from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .geometry import ImagePoint


@dataclass(frozen=True)
class EngineeringIntent:
    """Solver-independent engineering requirement.

    The LLM may populate this contract; deterministic validation decides what
    can actually be executed.
    """
    id: str
    kind: str
    description: str
    location: Optional[ImagePoint] = None
    magnitude: Optional[float] = None
    unit: Optional[str] = None
    direction: Optional[str] = None
    analysis_type: Optional[str] = None
    material: Optional[Dict[str, Any]] = None
    boundary_conditions: tuple = ()
    loads: tuple = ()
    contacts: tuple = ()
    mesh_requirements: Dict[str, Any] = field(default_factory=dict)
    outputs: tuple = ()
    acceptance_criteria: tuple = ()
    unit_system: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
