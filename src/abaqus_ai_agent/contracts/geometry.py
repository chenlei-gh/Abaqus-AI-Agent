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
    center: ImagePoint
    width: float
    height: float

    def __post_init__(self):
        if not 0.0 < self.width <= 1.0 or not 0.0 < self.height <= 1.0:
            raise ValueError("region width and height must be in (0, 1]")


@dataclass(frozen=True)
class ViewProjection:
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
    screen_polygon: Optional[Tuple[Tuple[float, float], ...]] = None
    screen_path: Optional[Tuple[Tuple[float, float], ...]] = None
    entity_key: Optional[str] = None
    camera_depth: Optional[float] = None
    facing_score: Optional[float] = None
    locator_point: Optional[Tuple[float, float, float]] = None

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
        return (0.4 * self.distance_score +
                0.4 * self.visual_score +
                0.2 * self.topology_score)


@dataclass(frozen=True)
class GroundingResult:
    """Deterministic grounding result; confidence is a policy signal, not proof."""
    intent_id: str
    candidates: List[GeometryCandidate]
    selected: Optional[GeometryCandidate]
    confidence: float
    requires_confirmation: bool
    evidence: Tuple[Tuple[str, ...], ...]

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


@dataclass(frozen=True)
class GeometrySelection:
    """A grouped geometric selection ready for Abaqus region binding.

    Targets are executor-neutral locators; integer geometry indices remain
    diagnostics only. region_kind is one of temporary, set, or surface.
    """
    targets: Tuple[dict, ...]
    entity_type: str
    region_kind: str = "temporary"
    name: Optional[str] = None
    surface_side: Optional[str] = None

    def __post_init__(self):
        if not self.targets:
            raise ValueError("geometry selection requires at least one target")
        if self.entity_type not in ("Face", "Edge", "Vertex"):
            raise ValueError("unsupported geometry entity type")
        if self.region_kind not in ("temporary", "set", "surface"):
            raise ValueError("region_kind must be temporary, set, or surface")
        if self.region_kind in ("set", "surface") and not self.name:
            raise ValueError("named selections require a name")
        if self.region_kind == "surface" and self.entity_type not in ("Face", "Edge"):
            raise ValueError("surfaces require Face or Edge targets")
        if self.surface_side not in (None, "side1", "side2"):
            raise ValueError("surface_side must be side1, side2, or None")


@dataclass(frozen=True)
class RegionBinding:
    """Plan for materializing a GeometrySelection in an Abaqus model."""
    region_kind: str
    name: Optional[str]
    entity_type: str
    targets: Tuple[dict, ...]
    surface_side: Optional[str] = None

    def __post_init__(self):
        if self.region_kind not in ("temporary", "set", "surface"):
            raise ValueError("unsupported region kind")
        if self.region_kind != "temporary" and not self.name:
            raise ValueError("named region requires a name")
        if self.region_kind == "surface" and self.entity_type not in ("Face", "Edge"):
            raise ValueError("surface requires Face or Edge")
        if self.surface_side not in (None, "side1", "side2"):
            raise ValueError("surface_side must be side1, side2, or None")
