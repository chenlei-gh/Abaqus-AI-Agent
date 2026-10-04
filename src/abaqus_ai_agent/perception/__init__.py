"""P1.1 Multimodal Engineering Perception & Document Ingestion Package.

Exposes:
- Ingestion pipeline for engineering PDFs (vector-first & raster fallback) and images.
- Provider-neutral vision provider abstraction and deterministic test mocks.
- Specialized dimension/tolerance and boundary/load extractors.
- PerceptionPipeline orchestrating extraction, validation, and GA-2B CAD correlation.
"""

from .boundary_load_extractor import BoundaryLoadExtractor
from .contracts import (
    ObservationProvenance,
    PerceptionConfidence,
    RawDimensionObservation,
    RawSymbolObservation,
    RawTextObservation,
    RejectedObservation,
)
from .dimension_extractor import DimensionExtractor
from .ingestion import DocumentIngestionPipeline, IngestedPage, IngestionError
from .perception_pipeline import PerceptionPipeline, PerceptionResult
from .provider import (
    BaseVisionProvider,
    MockVisionProvider,
    RuleBasedVisionProvider,
)

__all__ = [
    "BaseVisionProvider",
    "BoundaryLoadExtractor",
    "DimensionExtractor",
    "DocumentIngestionPipeline",
    "IngestedPage",
    "IngestionError",
    "MockVisionProvider",
    "ObservationProvenance",
    "PerceptionConfidence",
    "PerceptionPipeline",
    "PerceptionResult",
    "RawDimensionObservation",
    "RawSymbolObservation",
    "RawTextObservation",
    "RejectedObservation",
    "RuleBasedVisionProvider",
]
