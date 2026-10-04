"""GA-2B: Multimodal Perception & Grounding Contracts.

Defines the data models for:
- 2D engineering blueprint and drawing callouts (VisualCallout, BlueprintView)
- Grounding observations correlating visual callouts with 3D CAD topology
- Mandatory Human-in-the-Loop (HITL) confirmation states and gates

Core Architectural Rules:
- Zero Direct Code Generation: Models never fabricate raw Abaqus Python scripts.
- Direct Reuse of GroundedRegion: Candidate entities must be canonical GroundedRegion
  objects compatible with RegionResolver and IntentCompiler.
- Fail-Closed Gate: Unconfirmed or low-confidence observations strictly block
  intent synthesis and execution.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .geometry import ImagePoint, ImageRegion, ViewProjection


class CalloutType(str, Enum):
    ARROW = "ARROW"
    TEXT = "TEXT"
    DIMENSION = "DIMENSION"
    SYMBOL = "SYMBOL"
    REGION_BOX = "REGION_BOX"


class MultimodalSourceType(str, Enum):
    BLUEPRINT_VIEW = "blueprint_view"
    DRAWING_ANNOTATION = "drawing_annotation"
    PHOTO = "photo"
    ANNOTATED_VIEWPORT = "annotated_viewport"


class GroundingIntentType(str, Enum):
    BOUNDARY_CONDITION = "BOUNDARY_CONDITION"
    LOAD = "LOAD"
    DIMENSION = "DIMENSION"
    MATERIAL = "MATERIAL"


class HITLStatus(str, Enum):
    PENDING = "PENDING"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class VisualCallout:
    """An individual visual element parsed from a 2D drawing or image."""
    callout_id: str
    callout_type: str  # CalloutType value
    location: ImagePoint  # Anchor coordinate in normalized image space [0, 1]
    direction_vector: Optional[Tuple[float, float]] = None  # 2D orientation vector, e.g. pointing arrow
    region_box: Optional[ImageRegion] = None  # Optional bounding area
    text_content: Optional[str] = None  # Extracted text, e.g. "Fixed base", "F = 1000 N"
    semantic_intent: Optional[str] = None  # e.g. "FIXED_SUPPORT", "PRESSURE", "CONCENTRATED_FORCE"
    magnitude: Optional[float] = None  # Scalar value if present
    unit: Optional[str] = None  # Unit string, e.g. "N", "MPa", "mm"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.callout_id:
            raise ValueError("callout_id must not be empty")
        if self.direction_vector is not None:
            dx, dy = self.direction_vector
            if dx == 0.0 and dy == 0.0:
                raise ValueError("direction_vector cannot be zero-length")


@dataclass(frozen=True)
class BlueprintView:
    """A standard orthographic or projection view within an engineering drawing."""
    view_id: str
    view_type: str  # "FRONT", "TOP", "RIGHT", "LEFT", "BOTTOM", "BACK", "ISOMETRIC", "SECTION", "DETAIL"
    callouts: Tuple[VisualCallout, ...] = ()
    projection: Optional[ViewProjection] = None  # Calibrated viewport camera if available
    image_path: Optional[str] = None
    scale: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.view_id:
            raise ValueError("view_id must not be empty")


@dataclass(frozen=True)
class GroundingObservation:
    """Structured correlation between a 2D visual callout and 3D CAD topology."""
    observation_id: str
    source_type: str  # MultimodalSourceType value
    callout: VisualCallout
    detected_intent_type: str  # GroundingIntentType value
    target_topology_type: str  # "Face", "Edge", "Vertex"
    candidate_regions: Tuple[Any, ...] = ()  # Canonical GroundedRegion candidates
    selected_region: Optional[Any] = None  # Primary candidate
    confidence: float = 1.0  # [0.0, 1.0]
    uncertainty_reasons: Tuple[str, ...] = ()
    requires_confirmation: bool = False
    status: str = HITLStatus.PENDING.value
    confirmed_by: Optional[str] = None
    rejection_reason: Optional[str] = None
    view_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.observation_id:
            raise ValueError("observation_id must not be empty")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")
        if self.target_topology_type not in ("Face", "Edge", "Vertex"):
            raise ValueError(f"unsupported target_topology_type: {self.target_topology_type}")
        if self.status not in tuple(s.value for s in HITLStatus):
            raise ValueError(f"invalid HITL status: {self.status}")


@dataclass(frozen=True)
class HITLConfirmationDecision:
    """Record of an explicit engineer decision on a grounding observation."""
    observation_id: str
    decision: str  # "CONFIRM", "REJECT", "REFINE"
    confirmed_by: str
    selected_region_semantic: Optional[str] = None  # Specific semantic or ID chosen
    selected_anchor_point: Optional[Tuple[float, float, float]] = None
    override_magnitude: Optional[float] = None
    override_unit: Optional[str] = None
    override_direction: Optional[str] = None  # e.g. "CF1", "CF2", "CF3", "CM3"
    notes: Optional[str] = None
