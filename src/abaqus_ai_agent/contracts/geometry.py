from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class ImagePoint:
    """Normalized image coordinate in the inclusive [0, 1] range."""
    x: float
    y: float

    def __post_init__(self):
        if not 0.0 <= self.x <= 1.0 or not 0.0 <= self.y <= 1.0:
            raise ValueError("image coordinates must be in [0, 1]")


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


@dataclass(frozen=True)
class GroundingResult:
    """Evidence-backed geometry resolution result."""
    intent_id: str
    candidates: List[GeometryCandidate]
    selected: Optional[GeometryCandidate]
    confidence: float
    requires_confirmation: bool
    evidence: Tuple[str, ...] = ()
