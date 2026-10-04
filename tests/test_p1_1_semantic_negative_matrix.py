"""P1.1 Semantic Negative Matrix & Engineering Hardening Tests.

Validates the explicit fail-closed hardening requirements of P1.1:
1. Unknown Symbol -> Rejected as UNKNOWN_SYMBOL_TYPE, forbidden to fallback to CONCENTRATED_FORCE.
2. Missing Direction -> Marks FORCE_DIRECTION_UNKNOWN, blocks synthesis until explicitly confirmed.
3. Zero Direction Vector -> Strictly rejected as ZERO_DIRECTION_VECTOR; never invent default.
4. Out-of-bounds Coordinates -> Strictly rejected as COORDINATE_OUT_OF_BOUNDS; clamping forbidden.
5. Moment / Torque -> Preserves distinct "moment" load_type; never degraded to concentrated force.
6. Roller Support -> Preserves "DISPLACEMENT(u2=0)" freeing tangential DOFs; never degraded to ENCASTRE.
7. Invalid Unit -> Drops unit_confidence to 0.0, forces human confirmation.
8. Missing Unit -> Drops unit_confidence to 0.5, flags MISSING_UNIT_IN_OBSERVATIONS.
9. Ambiguous CAD Candidates -> Triggers AMBIGUOUS_MULTI_CANDIDATE, strictly blocks execution.
10. Unassessed Spatial Confidence -> Remains None (NOT_ASSESSED) during 2D stage; never fabricated as 1.0.
11. Load Vector Direction Mapping -> Accurately maps 2D direction vectors to CF1/CF2 with correct signs.
"""

import pytest

from abaqus_ai_agent.contracts.geometry import ImagePoint
from abaqus_ai_agent.contracts.multimodal import (
    CalloutType,
    HITLConfirmationDecision,
    HITLStatus,
    VisualCallout,
)
from abaqus_ai_agent.grounding.feature_grounding import GroundedRegion
from abaqus_ai_agent.grounding.multimodal import (
    HITLBlockedError,
    MultimodalHITLWorkflow,
    correlate_callout_with_cad,
    parse_drawing_callout,
)
from abaqus_ai_agent.perception.boundary_load_extractor import BoundaryLoadExtractor
from abaqus_ai_agent.perception.contracts import (
    ObservationProvenance,
    PerceptionConfidence,
    RawDimensionObservation,
    RawSymbolObservation,
    RawTextObservation,
)
from abaqus_ai_agent.perception.dimension_extractor import DimensionExtractor
from abaqus_ai_agent.perception.ingestion import IngestedPage
from abaqus_ai_agent.perception.perception_pipeline import PerceptionPipeline
from abaqus_ai_agent.perception.provider import MockVisionProvider, RuleBasedVisionProvider


def test_unknown_symbol_rejected_not_concentrated_force():
    """Negative Probe 1: Unrecognized symbol must be rejected; guessing as CONCENTRATED_FORCE is forbidden."""
    extractor = BoundaryLoadExtractor()
    provenance = ObservationProvenance(source_path="drawing.pdf", page_index=0)
    unknown_sym = RawSymbolObservation(
        symbol_type="UNKNOWN_WELD_NOTATION",
        location=(0.4, 0.4),
        direction=None,
        confidence=0.95,
        text_content=None,
        provenance=provenance,
    )

    valid_callouts, rejected = extractor.extract(symbols=[unknown_sym])
    assert len(valid_callouts) == 0, "Unknown symbol must not produce valid callouts!"
    assert len(rejected) == 1, "Unknown symbol must be explicitly recorded in rejected observations!"
    assert rejected[0].reason == "UNKNOWN_SYMBOL_TYPE"
    assert "guessing as force is forbidden" in rejected[0].detail


def test_concentrated_force_missing_direction_requires_confirmation():
    """Negative Probe 2: Concentrated force without direction vector must trigger FORCE_DIRECTION_UNKNOWN."""
    extractor = BoundaryLoadExtractor()
    provenance = ObservationProvenance(source_path="drawing.pdf", page_index=0)
    force_no_dir = RawSymbolObservation(
        symbol_type="ARROW",
        location=(0.5, 0.5),
        direction=None,  # No direction provided
        confidence=0.90,
        text_content="F = 1000 N",
        provenance=provenance,
    )

    valid_callouts, rejected = extractor.extract(symbols=[force_no_dir])
    assert len(valid_callouts) == 1
    callout = valid_callouts[0]
    assert callout.semantic_intent == "CONCENTRATED_FORCE"
    assert callout.direction_vector is None
    assert callout.metadata.get("direction_status") == "UNKNOWN"

    # Correlate with CAD candidate
    candidate = [{"name": "TipFace", "entity_type": "Face", "point": (100.0, 5.0, 5.0), "index": 1}]
    obs = correlate_callout_with_cad(callout, candidate)

    assert obs.requires_confirmation is True
    assert obs.status == HITLStatus.NEEDS_CONFIRMATION.value
    assert "FORCE_DIRECTION_UNKNOWN" in obs.uncertainty_reasons

    # Attempting to synthesize without confirmation must block
    workflow = MultimodalHITLWorkflow()
    workflow.register_observation(obs)
    with pytest.raises(HITLBlockedError, match="pending human confirmation"):
        workflow.synthesize_specs(fail_closed=True)


def test_zero_length_direction_vector_rejected():
    """Negative Probe 3: Zero-length direction vectors must be strictly rejected."""
    extractor = BoundaryLoadExtractor()
    zero_dir_sym = RawSymbolObservation(
        symbol_type="ARROW",
        location=(0.3, 0.3),
        direction=(0.0, 0.0),  # Illegal zero vector
        confidence=0.90,
        text_content="Load 500 N",
    )

    valid_callouts, rejected = extractor.extract(symbols=[zero_dir_sym])
    assert len(valid_callouts) == 0
    assert len(rejected) == 1
    assert rejected[0].reason == "ZERO_DIRECTION_VECTOR"


def test_out_of_range_coordinates_rejected_no_clamping():
    """Negative Probe 4: Coordinates outside [0, 1] must be strictly rejected without clamping."""
    extractor = BoundaryLoadExtractor()
    out_of_bounds_sym = RawSymbolObservation(
        symbol_type="FIXED",
        location=(1.05, 0.2),  # x > 1.0
        confidence=0.90,
    )

    valid_callouts, rejected = extractor.extract(symbols=[out_of_bounds_sym])
    assert len(valid_callouts) == 0
    assert len(rejected) == 1
    assert rejected[0].reason == "COORDINATE_OUT_OF_BOUNDS"
    assert "clamping forbidden" in rejected[0].detail


def test_moment_preserves_independent_mechanical_semantic():
    """Semantic Probe 5: Moment/torque must retain distinct 'moment' load_type."""
    callout = parse_drawing_callout(callout_id="c_moment", text="Torque 200000 N*mm")
    assert callout.semantic_intent == "MOMENT"
    assert callout.magnitude == pytest.approx(200000.0)

    candidate = [{"name": "ShaftFace", "entity_type": "Face", "point": (50.0, 0.0, 0.0), "index": 1}]
    obs = correlate_callout_with_cad(callout, candidate)

    workflow = MultimodalHITLWorkflow()
    workflow.register_observation(obs)
    decision = HITLConfirmationDecision(
        observation_id=obs.observation_id,
        decision="CONFIRM",
        confirmed_by="lead_engineer",
        override_direction="CM3",
    )
    workflow.confirm(decision)

    bcs, loads, regions = workflow.synthesize_specs(fail_closed=True)
    assert len(loads) == 1
    assert loads[0].load_type == "moment", "Moment must NOT be degraded to concentrated_force or pressure!"
    assert loads[0].direction == "CM3"
    assert loads[0].magnitude == pytest.approx(200000.0)


def test_roller_support_preserves_roller_boundary_semantic():
    """Semantic Probe 6: Roller support must restrict normal displacement while freeing tangential DOFs."""
    callout = parse_drawing_callout(callout_id="c_roller", text="Roller support at base")
    assert callout.semantic_intent == "ROLLER_SUPPORT"

    candidate = [{"name": "BaseContact", "entity_type": "Face", "point": (10.0, 0.0, 0.0), "index": 1}]
    obs = correlate_callout_with_cad(callout, candidate)

    workflow = MultimodalHITLWorkflow()
    workflow.register_observation(obs)
    decision = HITLConfirmationDecision(
        observation_id=obs.observation_id,
        decision="CONFIRM",
        confirmed_by="lead_engineer",
    )
    workflow.confirm(decision)

    bcs, loads, regions = workflow.synthesize_specs(fail_closed=True)
    assert len(bcs) == 1
    assert bcs[0].bc_type == "DISPLACEMENT", "Roller must NOT be degraded to ENCASTRE!"
    assert bcs[0].values == {"u2": 0.0}, "Roller must restrict normal displacement U2=0.0 while freeing U1/U3!"


def test_invalid_engineering_unit_fails_closed():
    """Negative Probe 7: Invalid or nonsensical units must drop unit_confidence to 0.0 and trigger HITL."""
    provider = MockVisionProvider(
        dimensions=[
            RawDimensionObservation(
                text="Length 100 invalid_unit_xyz",
                location=(0.5, 0.5),
                nominal_value=100.0,
                unit="invalid_unit_xyz",
                confidence=0.95,
            )
        ]
    )
    pipeline = PerceptionPipeline(provider=provider)
    dummy_page = IngestedPage(
        page_index=0,
        width=1000.0,
        height=800.0,
        is_vector=False,
        source_path="spec.png",
    )

    result = pipeline.process_page(dummy_page)
    assert result.confidence.unit_confidence == 0.0
    assert "INVALID_UNIT_IN_OBSERVATIONS" in result.confidence.ambiguity_reasons
    assert result.confidence.requires_human_confirmation is True


def test_missing_unit_lowers_confidence_not_silently_ignored():
    """Negative Probe 8: Callout with magnitude but missing unit drops confidence to 0.5."""
    provider = MockVisionProvider(
        symbols=[
            RawSymbolObservation(
                symbol_type="ARROW",
                location=(0.5, 0.5),
                direction=(0.0, -1.0),
                confidence=0.95,
                text_content="5000",  # Value exists, unit missing
            )
        ]
    )
    pipeline = PerceptionPipeline(provider=provider)
    dummy_page = IngestedPage(
        page_index=0,
        width=1000.0,
        height=800.0,
        is_vector=False,
        source_path="spec.png",
    )

    result = pipeline.process_page(dummy_page)
    assert result.confidence.unit_confidence == 0.5
    assert "MISSING_UNIT_IN_OBSERVATIONS" in result.confidence.ambiguity_reasons
    assert result.confidence.requires_human_confirmation is True


def test_ambiguous_cad_candidates_triggers_hitl_blocking():
    """Negative Probe 9: Multiple matching CAD candidates must block execution until resolved."""
    callout = parse_drawing_callout(callout_id="c_multi", text="Fixed face")
    candidates = [
        {"name": "Face_A", "entity_type": "Face", "point": (10.0, 0.0, 0.0), "index": 1},
        {"name": "Face_B", "entity_type": "Face", "point": (20.0, 0.0, 0.0), "index": 2},
    ]
    obs = correlate_callout_with_cad(callout, candidates)

    assert len(obs.candidate_regions) == 2
    assert obs.confidence <= 0.60
    assert "AMBIGUOUS_MULTI_CANDIDATE" in obs.uncertainty_reasons
    assert obs.requires_confirmation is True
    assert obs.status == HITLStatus.NEEDS_CONFIRMATION.value

    workflow = MultimodalHITLWorkflow()
    workflow.register_observation(obs)
    with pytest.raises(HITLBlockedError, match="pending human confirmation"):
        workflow.synthesize_specs(fail_closed=True)


def test_spatial_confidence_not_assessed_in_2d_stage():
    """Integrity Probe 10: In 2D perception stage, 3D spatial alignment is NOT_ASSESSED (None)."""
    provider = MockVisionProvider(
        dimensions=[
            RawDimensionObservation(
                text="100 mm",
                location=(0.5, 0.5),
                nominal_value=100.0,
                unit="mm",
                confidence=0.98,
            )
        ]
    )
    pipeline = PerceptionPipeline(provider=provider)
    dummy_page = IngestedPage(
        page_index=0,
        width=1000.0,
        height=800.0,
        is_vector=False,
        source_path="spec.png",
    )

    result = pipeline.process_page(dummy_page)
    assert result.confidence.is_spatial_assessed is False
    assert result.confidence.spatial_confidence is None


def test_directional_vectors_mapped_correctly_to_abaqus_cf():
    """Physical Mapping Probe 11: 2D direction vectors mapped to CF1 / CF2 with consistent signs."""
    # Downward force: (0.0, -1.0) -> CF2 with negative sign
    callout_down = parse_drawing_callout(
        callout_id="c_down",
        text="Load 1000 N downward",
        direction_vector=(0.0, -1.0),
    )
    candidate = [{"name": "TipFace", "entity_type": "Face", "point": (100.0, 0.0, 0.0), "index": 1}]
    obs_down = correlate_callout_with_cad(callout_down, candidate)

    wf_down = MultimodalHITLWorkflow()
    wf_down.register_observation(obs_down)
    wf_down.confirm(HITLConfirmationDecision(observation_id=obs_down.observation_id, decision="CONFIRM", confirmed_by="eng"))
    _, loads_down, _ = wf_down.synthesize_specs()
    assert loads_down[0].direction == "CF2"
    assert loads_down[0].magnitude == pytest.approx(-1000.0)

    # Rightward force: (1.0, 0.0) -> CF1 with positive sign
    callout_right = parse_drawing_callout(
        callout_id="c_right",
        text="Load 2000 N rightward",
        direction_vector=(1.0, 0.0),
    )
    obs_right = correlate_callout_with_cad(callout_right, candidate)
    wf_right = MultimodalHITLWorkflow()
    wf_right.register_observation(obs_right)
    wf_right.confirm(HITLConfirmationDecision(observation_id=obs_right.observation_id, decision="CONFIRM", confirmed_by="eng"))
    _, loads_right, _ = wf_right.synthesize_specs()
    assert loads_right[0].direction == "CF1"
    assert loads_right[0].magnitude == pytest.approx(2000.0)
