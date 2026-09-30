from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..contracts.geometry import ImagePoint, ImageRegion


@dataclass(frozen=True)
class Annotation:
    id: str
    kind: str
    point: Optional[ImagePoint] = None
    region: Optional[ImageRegion] = None
    label: Optional[str] = None
    text: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AnnotationSet:
    image_width: int
    image_height: int
    annotations: List[Annotation]
    source: str = "user"
