from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ExperimentInput:
    """Normalized user experiment input.

    image/annotations are deliberately external to the solver; the grounding
    layer converts them into native regions before actions are created.
    """
    requirements: str
    material: Dict[str, Any]
    model_name: str
    image_path: Optional[str] = None
    annotations: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
