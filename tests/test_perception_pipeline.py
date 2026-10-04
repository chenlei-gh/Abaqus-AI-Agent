"""Unit and integration tests for P1.1 PerceptionPipeline.

Tests:
- End-to-end orchestration: page ingestion -> provider -> extractors -> PerceptionResult.
- Fail-closed validation tracking with RejectedObservation.
- Multidimensional PerceptionConfidence metrics.
- Seamless bridge to GA-2A CAD grounding via correlate_with_cad().
- Seamless bridge to GA-2B MultimodalHITLWorkflow gate and intent synthesis.
"""

from pathlib import Path
import pytest
from PIL import Image

from abaqus_ai_agent.contracts.geometry import ImagePoint
from abaqus_ai_agent.contracts.multimodal import (
    CalloutType,
    HITLConfirmationDecision,
    HITLStatus,
)
from abaqus_ai_agent.grounding.feature_grounding import GroundedRegion
from abaqus_ai_agent.grounding.multimodal import (
    HITLBlockedError,
    MultimodalHITLWorkflow,
)
from abaqus_ai_agent.perception.contracts import (
    ObservationProvenance,
    RawDimensionObservation,
    RawSymbolObservation,
    RawTextObservation,
)
from abaqus_ai_agent.perception.ingestion import IngestedPage
from abaqus_ai_agent.perception.perception_pipeline import PerceptionPipeline
from abaqus_ai_agent.perception.provider import MockVisionProvider


@pytest.fixture
def mock_page() -> IngestedPage:
    return IngestedPage(
        page_index=0,
        width=1000.0,
        height=800.0,
        is_vector=True,
        source_path="mock_drawing.pdf",
    )


def test_perception_pipeline_mock_execution(mock_page: IngestedPage):
    prov = mock_page.build_provenance(extraction_method="mock", provider_id="mock_test")

    mock_texts = [
        RawTextObservation(
            text="Material: Steel Q235",
            box=(0.05, 0.05, 0.08, 0.25),
            confidence=0.99,
            provenance=prov,
        )
    ]
    mock_symbols = [
        RawSymbolObservation(
            symbol_type="FIXED",
            location=(0.1, 0.9),
            text_content="Fixed base",
            confidence=0.96,
            provenance=prov,
        ),
        RawSymbolObservation(
            symbol_type="ARROW",
            location=(0.8, 0.2),
            direction=(0.0, -1.0),
            text_content="F = 8000 N",
            confidence=0.97,
            provenance=prov,
        ),
    ]
    mock_dimensions = [
        RawDimensionObservation(
            text="L = 600 mm",
            location=(0.5, 0.85),
            nominal_value=600.0,
            unit="mm",
            confidence=0.98,
            provenance=prov,
        )
    ]

    provider = MockVisionProvider(
        text_blocks=mock_texts,
        symbols=mock_symbols,
        dimensions=mock_dimensions,
    )
    pipeline = PerceptionPipeline(provider=provider)

    result = pipeline.process_page(mock_page)

    assert result.page_index == 0
    assert result.source_path == "mock_drawing.pdf"
    assert result.valid_callout_count == 3  # 1 dim + 2 loads/supports
    assert len(result.rejected_observations) == 0

    # Verify types
    types = {c.callout_type for c in result.callouts}
    assert CalloutType.DIMENSION.value in types
    assert CalloutType.SYMBOL.value in types
    assert CalloutType.ARROW.value in types

    # Check confidence
    assert result.confidence.overall_confidence >= 0.95
    assert not result.confidence.requires_human_confirmation


def test_perception_pipeline_rejection_tracking(mock_page: IngestedPage):
    """Ensure invalid observations are properly captured and recorded in result."""
    prov = mock_page.build_provenance(extraction_method="mock", provider_id="mock_test")

    # One valid, two invalid
    mock_symbols = [
        RawSymbolObservation(
            symbol_type="FIXED",
            location=(0.2, 0.8),
            confidence=0.95,
            provenance=prov,
        ),
        # Out of bounds coordinate
        RawSymbolObservation(
            symbol_type="ARROW",
            location=(1.25, 0.5),
            direction=(0.0, -1.0),
            confidence=0.90,
            provenance=prov,
        ),
        # Zero direction vector
        RawSymbolObservation(
            symbol_type="ARROW",
            location=(0.5, 0.5),
            direction=(0.0, 0.0),
            confidence=0.90,
            provenance=prov,
        ),
    ]

    provider = MockVisionProvider(symbols=mock_symbols)
    pipeline = PerceptionPipeline(provider=provider)

    result = pipeline.process_page(mock_page)

    assert result.valid_callout_count == 1
    assert len(result.rejected_observations) == 2
    assert result.has_rejections
    reasons = [r.reason for r in result.rejected_observations]
    assert "COORDINATE_OUT_OF_BOUNDS" in reasons
    assert "ZERO_DIRECTION_VECTOR" in reasons
    assert result.confidence.has_ambiguous_candidates


def test_perception_bridge_to_ga2a_and_hitl(mock_page: IngestedPage):
    """Direct integration test proving Perception -> GA-2A Grounding -> GA-2B HITL."""
    prov = mock_page.build_provenance(extraction_method="mock", provider_id="mock_test")

    mock_symbols = [
        RawSymbolObservation(
            symbol_type="FIXED",
            location=(0.1, 0.5),
            text_content="Fixed base",
            confidence=0.95,
            provenance=prov,
        ),
        RawSymbolObservation(
            symbol_type="ARROW",
            location=(0.9, 0.5),
            direction=(0.0, -1.0),
            text_content="F = 5000 N",
            confidence=0.95,
            provenance=prov,
        ),
    ]

    provider = MockVisionProvider(symbols=mock_symbols)
    pipeline = PerceptionPipeline(provider=provider)
    result = pipeline.process_page(mock_page)

    # 1. Candidate CAD geometry (canonical GroundedRegion representations)
    candidates = [
        GroundedRegion(
            target_semantic="FIXED_BASE",
            entity_type="Face",
            entity_ids=("1",),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.92,
            status="RESOLVED",
        ),
        GroundedRegion(
            target_semantic="LOAD_SURFACE",
            entity_type="Face",
            entity_ids=("2",),
            anchor_point=(100.0, 0.0, 0.0),
            confidence=0.92,
            status="RESOLVED",
        ),
    ]

    # 2. Correlate with CAD via GA-2A bridge
    observations = pipeline.correlate_with_cad(result, cad_candidates=candidates)
    assert len(observations) == 2

    # 3. Feed observations to existing GA-2B HITL workflow
    workflow = MultimodalHITLWorkflow(confidence_threshold=0.85)
    for obs in observations:
        workflow.register_observation(obs)

    # Both observations have multiple candidates in candidate set, so they require confirmation
    for obs in workflow.list_observations():
        assert obs.status == HITLStatus.NEEDS_CONFIRMATION.value

    # Synthesizing specs while unconfirmed must raise HITLBlockedError (Fail-Closed Gate)
    with pytest.raises(HITLBlockedError):
        workflow.synthesize_specs()

    # Engineer confirms each observation explicitly
    for obs in workflow.list_observations():
        decision = HITLConfirmationDecision(
            observation_id=obs.observation_id,
            decision="CONFIRM",
            confirmed_by="lead_cae_engineer",
        )
        workflow.confirm(decision)

    # Now all observations are confirmed; synthesis must succeed
    bc_specs, load_specs, grounded_regions = workflow.synthesize_specs()
    assert len(bc_specs) >= 1 or len(load_specs) >= 1
    assert len(grounded_regions) >= 1
