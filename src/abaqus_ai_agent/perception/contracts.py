"""P1.1 Multimodal Engineering Perception Contracts.

Defines the data models for:
- Observation provenance (source document, page index, dimensions, extraction method)
- Multidimensional perception confidence metrics
- Raw unstructured observations (text, symbols, dimensions)
- Explicit rejected observations for fail-closed auditing

Architectural Invariants (P1.1 Interface Freeze):
- Zero Direct Code Generation: Perception models never generate Abaqus Python scripts.
- Transient Perception Evidence: Raw observations are ephemeral perception evidence,
  not final engineering facts.
- No Silent Repair: Invalid coordinates (< 0 or > 1) and zero-length direction
  vectors are strictly rejected and recorded as RejectedObservation, never clamped
  or invented.
- Canonical Downstream Output: Perception layer validates and converts raw observations
  into canonical VisualCallout instances.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class ObservationProvenance:
    """Provenance and spatial context for an engineering perception observation."""
    source_path: str
    page_index: int = 0
    source_dimensions: Tuple[float, float] = (0.0, 0.0)  # (width, height) in native units/pixels
    extraction_method: str = "unknown"  # "vector_pdf", "raster_ocr", "symbol_matcher", etc.
    provider_id: str = "mock"
    provider_confidence: float = 1.0
    timestamp: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.source_path:
            raise ValueError("source_path must not be empty")
        if self.page_index < 0:
            raise ValueError(f"page_index must be non-negative, got {self.page_index}")


@dataclass(frozen=True)
class PerceptionConfidence:
    """Multidimensional perception confidence evaluation.

    Supports explicit unassessed dimensions (None) to avoid fabricating high
    confidence when units or spatial alignment have not been evaluated.
    """
    text_confidence: float = 1.0
    symbol_confidence: float = 1.0
    unit_confidence: Optional[float] = None  # None = NOT_ASSESSED
    spatial_confidence: Optional[float] = None  # None = NOT_ASSESSED
    has_ambiguous_candidates: bool = False
    ambiguity_reasons: Tuple[str, ...] = ()

    def __post_init__(self):
        for name, val in (
            ("text_confidence", self.text_confidence),
            ("symbol_confidence", self.symbol_confidence),
            ("unit_confidence", self.unit_confidence),
            ("spatial_confidence", self.spatial_confidence),
        ):
            if val is not None and not (0.0 <= val <= 1.0):
                raise ValueError(f"{name} must be in [0.0, 1.0], got {val}")

    @property
    def is_unit_assessed(self) -> bool:
        """Indicates whether unit confidence has been explicitly evaluated."""
        return self.unit_confidence is not None

    @property
    def is_spatial_assessed(self) -> bool:
        """Indicates whether spatial/CAD alignment confidence has been explicitly evaluated."""
        return self.spatial_confidence is not None

    @property
    def overall_confidence(self) -> float:
        """Conservative aggregate confidence (minimum across all evaluated dimensions)."""
        assessed = [
            c for c in (
                self.text_confidence,
                self.symbol_confidence,
                self.unit_confidence,
                self.spatial_confidence,
            )
            if c is not None
        ]
        return min(assessed) if assessed else 1.0

    @property
    def requires_human_confirmation(self) -> bool:
        """Heuristic check indicating whether human confirmation is advised."""
        return self.has_ambiguous_candidates or self.overall_confidence < 0.85


@dataclass(frozen=True)
class RawTextObservation:
    """Raw textual block extracted from a drawing or document."""
    text: str
    box: Tuple[float, float, float, float]  # (ymin, xmin, ymax, xmax) in normalized [0, 1] coordinates
    confidence: float = 1.0
    is_vector: bool = False
    provenance: Optional[ObservationProvenance] = None

    def __post_init__(self):
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")

    @property
    def center(self) -> Tuple[float, float]:
        """Calculates normalized center (x, y)."""
        ymin, xmin, ymax, xmax = self.box
        return ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)

    @property
    def is_normalized_in_bounds(self) -> bool:
        """Checks if all box coordinates are strictly within [0.0, 1.0]."""
        return all(0.0 <= c <= 1.0 for c in self.box)


@dataclass(frozen=True)
class RawSymbolObservation:
    """Raw mechanical or graphic symbol detected in a drawing."""
    symbol_type: str  # e.g. "ARROW", "FIXED", "PINNED", "ROLLER", "PRESSURE", "SYMMETRY_X"
    location: Tuple[float, float]  # Normalized anchor (x, y) in [0, 1]
    direction: Optional[Tuple[float, float]] = None  # Orientation vector (dx, dy)
    confidence: float = 1.0
    text_content: Optional[str] = None
    provenance: Optional[ObservationProvenance] = None

    def __post_init__(self):
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")

    @property
    def is_location_in_bounds(self) -> bool:
        x, y = self.location
        return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


@dataclass(frozen=True)
class RawDimensionObservation:
    """Raw dimension and tolerance annotation detected in a drawing."""
    text: str
    location: Tuple[float, float]  # Normalized anchor (x, y)
    span_start: Optional[Tuple[float, float]] = None
    span_end: Optional[Tuple[float, float]] = None
    nominal_value: Optional[float] = None
    tolerance_upper: Optional[float] = None
    tolerance_lower: Optional[float] = None
    unit: Optional[str] = None  # e.g. "mm", "m", "in"
    confidence: float = 1.0
    provenance: Optional[ObservationProvenance] = None

    def __post_init__(self):
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")

    @property
    def is_location_in_bounds(self) -> bool:
        x, y = self.location
        return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


@dataclass(frozen=True)
class RejectedObservation:
    """Audit record of a raw observation rejected by fail-closed validation."""
    raw_observation: Any
    reason: str  # e.g. "COORDINATE_OUT_OF_BOUNDS", "ZERO_DIRECTION_VECTOR", "AMBIGUOUS_UNIT"
    detail: Optional[str] = None
    provenance: Optional[ObservationProvenance] = None
