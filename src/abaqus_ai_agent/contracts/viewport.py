from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

@dataclass(frozen=True)
class ViewportState:
    viewport_name: str=""
    projection: str="unknown"
    camera_position: Tuple[float,...]=()
    camera_target: Tuple[float,...]=()
    camera_up: Tuple[float,...]=()
    displayed_instances: Tuple[str,...]=()
    displayed_object: str=""
    image_path: str=""
    metadata: Dict[str,Any]=field(default_factory=dict)
