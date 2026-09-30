from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class ImagePoint:
    """Normalized image coordinate, origin at top-left."""
    x: float
    y: float

    def __post_init__(self):
        if not 0.0 <= self.x <= 1.0 or not 0.0 <= self.y <= 1.0:
            raise ValueError("image coordinates must be in [0, 1]")


@dataclass(frozen=True)
class ImageRegion:
    """A normalized annotation region in image coordinates."""
    center: ImagePoint
    width: float
    height: float

    def __post_init__(self):
        if not 0.0 < self.width <= 1.0 or not 0.0 < self.height <= 1.0:
            raise ValueError("region width and height must be in (0, 1]")


@dataclass(frozen=True)
class ViewProjection:
    """Camera/projection metadata supplied by the Abaqus adapter."""
    viewport_id: str
    projection_type: str
    image_width: int
    image_height: int
    camera_position: Optional[Tuple[float, float, float]] = None
    camera_target: Optional[Tuple[float, float, float]] = None
    up_vector: Optional[Tuple[float, float, float]] = None
    view_width: Optional[float] = None
    view_height: Optional[float] = None
    view_offset_x: float = 0.0
    view_offset_y: float = 0.0


@dataclass(frozen=True)
class GeometryCandidate:
    """Candidate Abaqus entity plus independent grounding evidence."""
    entity_type: str
    name: Optional[str]
    index: Optional[int]
    centroid: Optional[Tuple[float, float, float]]
    normal: Optional[Tuple[float, float, float]]
    area: Optional[float]
    distance_score: float
    visual_score: float
    topology_score: float

    def __post_init__(self):
        for name, value in (
            ("distance_score", self.distance_score),
            ("visual_score", self.visual_score),
            ("topology_score", self.topology_score),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("%s must be in [0, 1]" % name)

    @property
    def total_score(self) -> float:
        """Normalized evidence score used for ranking."""
        return (
            0.4 * self.distance_score
            + 0.4 * self.visual_score
            + 0.2 * self.topology_score
        )


@dataclass(frozen=True)
class GroundingResult:
    """Evidence-backed geometry resolution result."""
    intent_id: str
    candidates: List[GeometryCandidate]
    selected: Optional[GeometryCandidate]
    confidence: float
    requires_confirmation: bool
    evidence: Tuple[str, ...] = ()
