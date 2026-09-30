from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .geometry import ImagePoint


@dataclass(frozen=True)
class EngineeringIntent:
    """Solver-independent description of an experimental intent."""
    id: str
    kind: str
    description: str
    location: Optional[ImagePoint] = None
    magnitude: Optional[float] = None
    unit: Optional[str] = None
    direction: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
