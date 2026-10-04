"""P1.1 Engineering Perception Pipeline Orchestrator.

Orchestrates:
1. Document ingestion (vector PDF / raster images).
2. Provider invocation (text blocks, mechanical symbols, dimensions).
3. Dedicated extractors (DimensionExtractor, BoundaryLoadExtractor).
4. Strict fail-closed coordinate/vector validation and provenance retention.
5. Direct integration with existing GA-2A grounding (correlate_callout_with_cad)
   and GA-2B HITL confirmation (MultimodalHITLWorkflow).

Architectural Invariants (P1.1 Interface Freeze):
- Zero Direct Code Generation: No Abaqus Python scripts emitted.
- Reuses existing contracts: VisualCallout, GroundingObservation, GroundedRegion.
- No second HITL workflow: Direct plug-in to MultimodalHITLWorkflow.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..contracts.geometry import ViewProjection
from ..contracts.multimodal import GroundingObservation, VisualCallout
from ..grounding.multimodal import correlate_callout_with_cad
from .boundary_load_extractor import BoundaryLoadExtractor
from .contracts import (
    ObservationProvenance,
    PerceptionConfidence,
    RejectedObservation,
)
from .dimension_extractor import DimensionExtractor
from .ingestion import DocumentIngestionPipeline, IngestedPage
from .provider import BaseVisionProvider, RuleBasedVisionProvider


@dataclass(frozen=True)
class PerceptionResult:
    """Consolidated perception result for a document page."""
    source_path: str
    page_index: int
    callouts: Tuple[VisualCallout, ...]
    rejected_observations: Tuple[RejectedObservation, ...]
    confidence: PerceptionConfidence
    provenance: ObservationProvenance
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_rejections(self) -> bool:
        return len(self.rejected_observations) > 0

    @property
    def valid_callout_count(self) -> int:
        return len(self.callouts)


class PerceptionPipeline:
    """Unified orchestrator converting engineering blueprints and photos into canonical VisualCallouts."""

    def __init__(
        self,
        provider: Optional[BaseVisionProvider] = None,
        ingestion_pipeline: Optional[DocumentIngestionPipeline] = None,
        dimension_extractor: Optional[DimensionExtractor] = None,
        boundary_load_extractor: Optional[BoundaryLoadExtractor] = None,
    ):
        self.provider = provider or RuleBasedVisionProvider()
        self.ingestion = ingestion_pipeline or DocumentIngestionPipeline()
        self.dim_extractor = dimension_extractor or DimensionExtractor()
        self.load_extractor = boundary_load_extractor or BoundaryLoadExtractor()

    def process_file(
        self,
        file_path: Union[str, Path],
    ) -> Sequence[PerceptionResult]:
        """Ingest a multi-page document or image and extract validated VisualCallout items per page."""
        pages = self.ingestion.load_document(file_path)
        return tuple(self.process_page(page) for page in pages)

    def process_page(
        self,
        page: IngestedPage,
    ) -> PerceptionResult:
        """Process a single ingested page into a validated PerceptionResult."""
        provenance = page.build_provenance(
            extraction_method="vector_pdf" if page.is_vector else "raster_vision",
            provider_id=self.provider.provider_id,
        )

        # 1. Invoke vision provider
        raw_texts = self.provider.extract_text_blocks(page, provenance)
        raw_symbols = self.provider.detect_symbols(page, provenance)
        raw_dimensions = self.provider.detect_dimensions(page, provenance)

        # 2. Extract dimensions
        dim_callouts, dim_rejected = self.dim_extractor.extract(
            dimensions=raw_dimensions,
            text_blocks=raw_texts,
        )

        # 3. Extract boundary conditions and loads
        load_callouts, load_rejected = self.load_extractor.extract(
            symbols=raw_symbols,
            text_blocks=raw_texts,
        )

        all_callouts = dim_callouts + load_callouts
        all_rejected = dim_rejected + load_rejected

        # 4. Assess multidimensional perception confidence
        text_conf = (
            min((t.confidence for t in raw_texts), default=1.0)
            if raw_texts
            else 1.0
        )
        sym_conf = (
            min((s.confidence for s in raw_symbols), default=1.0)
            if raw_symbols
            else 1.0
        )
        dim_conf = (
            min((d.confidence for d in raw_dimensions), default=1.0)
            if raw_dimensions
            else 1.0
        )

        ambiguity_reasons = []
        if all_rejected:
            ambiguity_reasons.append(f"{len(all_rejected)}_OBSERVATIONS_REJECTED")

        # Evaluate unit confidence strictly across all callouts with numeric magnitude
        valid_units = {
            "mm", "m", "cm", "in", "ft",
            "n", "kn", "mn", "lbf",
            "pa", "kpa", "mpa", "gpa", "bar", "psi",
            "n*m", "n*mm", "kn*m", "lbf*in", "lbf*ft",
            "deg", "rad", "°", "%",
        }
        numeric_callouts = [c for c in all_callouts if c.magnitude is not None]
        if not numeric_callouts:
            unit_conf: Optional[float] = None  # NOT_ASSESSED
        else:
            has_invalid_unit = False
            has_missing_unit = False
            for c in numeric_callouts:
                if c.unit is None:
                    has_missing_unit = True
                else:
                    norm_unit = c.unit.strip().lower()
                    if norm_unit not in valid_units:
                        has_invalid_unit = True

            if has_invalid_unit:
                unit_conf = 0.0
                ambiguity_reasons.append("INVALID_UNIT_IN_OBSERVATIONS")
            elif has_missing_unit:
                unit_conf = 0.5
                ambiguity_reasons.append("MISSING_UNIT_IN_OBSERVATIONS")
            else:
                unit_conf = 1.0

        # Check for forces without clear direction vectors
        for c in all_callouts:
            if c.semantic_intent == "CONCENTRATED_FORCE" and c.direction_vector is None:
                ambiguity_reasons.append("FORCE_DIRECTION_UNKNOWN")

        # In 2D perception stage, 3D spatial alignment is NOT_ASSESSED (None)
        spatial_conf: Optional[float] = None

        confidence = PerceptionConfidence(
            text_confidence=text_conf,
            symbol_confidence=min(sym_conf, dim_conf),
            unit_confidence=unit_conf,
            spatial_confidence=spatial_conf,
            has_ambiguous_candidates=bool(ambiguity_reasons),
            ambiguity_reasons=tuple(ambiguity_reasons),
        )

        return PerceptionResult(
            source_path=page.source_path,
            page_index=page.page_index,
            callouts=all_callouts,
            rejected_observations=all_rejected,
            confidence=confidence,
            provenance=provenance,
            metadata={
                "page_dimensions": (page.width, page.height),
                "is_vector": page.is_vector,
                "provider_id": self.provider.provider_id,
            },
        )

    def correlate_with_cad(
        self,
        perception_result: PerceptionResult,
        cad_candidates: Sequence[Any],
        view_projection: Optional[ViewProjection] = None,
        target_semantic: Optional[str] = None,
    ) -> Sequence[GroundingObservation]:
        """Bridge perception callouts directly to existing GA-2A CAD grounding.

        Produces canonical GroundingObservation objects compatible with MultimodalHITLWorkflow.
        """
        observations = []
        for callout in perception_result.callouts:
            obs = correlate_callout_with_cad(
                callout=callout,
                candidates=cad_candidates,
                view_projection=view_projection,
                target_semantic=target_semantic,
            )
            observations.append(obs)
        return tuple(observations)
