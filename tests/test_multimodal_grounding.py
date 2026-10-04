"""Tests for Track GA-2B: Multimodal Perception & Human-in-the-Loop Grounding.

Verifies:
1. GA-2B.1: 2D drawing text, callout, and dimension parsing.
2. GA-2B.2: Grounding observation generation, candidate correlation, and uncertainty tracking.
3. GA-2B.3: Mandatory Human-in-the-Loop (HITL) fail-closed confirmation gate.
4. GA-2B.4: Confirmed multimodal intent compilation into valid Abaqus action plans passing preflight.
"""

import pytest
from abaqus_ai_agent.contracts.geometry import ImagePoint, ImageRegion, ViewProjection, resolve_region
from abaqus_ai_agent.contracts.multimodal import (
    CalloutType,
    MultimodalSourceType,
    GroundingIntentType,
    HITLStatus,
    VisualCallout,
    BlueprintView,
    GroundingObservation,
    HITLConfirmationDecision,
)
from abaqus_ai_agent.grounding.feature_grounding import GroundedRegion
from abaqus_ai_agent.grounding.multimodal import (
    MultimodalGroundingError,
    HITLBlockedError,
    parse_drawing_callout,
    correlate_callout_with_cad,
    MultimodalHITLWorkflow,
)
from abaqus_ai_agent.planning.compiler import (
    compile_intent_to_actions,
    IntentGeometrySpec,
    IntentStepSpec,
    IntentMeshSpec,
)
from abaqus_ai_agent.contracts.material import MaterialDefinition, ElasticProperties
from abaqus_ai_agent.validation.preflight import preflight_action


# --- GA-2B.1: 2D Drawing & Visual Callout Parsing ---

def test_parse_drawing_callout_fixed_boundary():
    callout = parse_drawing_callout(
        callout_id="c_fixed_1",
        text="Encastre fixed support at root face",
        location=ImagePoint(0.1, 0.5),
    )
    assert callout.callout_id == "c_fixed_1"
    assert callout.semantic_intent == "FIXED_SUPPORT"
    assert callout.callout_type == CalloutType.TEXT.value
    assert callout.location.x == 0.1
    assert callout.location.y == 0.5


def test_parse_drawing_callout_load_with_magnitude_and_unit():
    callout = parse_drawing_callout(
        callout_id="c_load_1",
        text="Apply 2500 N downward vertical load",
        location=ImagePoint(0.9, 0.5),
        direction_vector=(0.0, -1.0),
    )
    assert callout.callout_id == "c_load_1"
    assert callout.semantic_intent == "CONCENTRATED_FORCE"
    assert callout.magnitude == pytest.approx(2500.0)
    assert callout.unit == "N"
    assert callout.callout_type == CalloutType.ARROW.value
    assert callout.direction_vector == (0.0, -1.0)


def test_parse_drawing_callout_pressure_load():
    callout = parse_drawing_callout(
        callout_id="c_press_1",
        text="Uniform pressure 3.5 MPa on top surface",
        location=ImagePoint(0.5, 0.1),
    )
    assert callout.semantic_intent == "PRESSURE"
    assert callout.magnitude == pytest.approx(3.5)
    assert callout.unit == "MPa"


def test_parse_drawing_callout_symmetry_planes():
    callout_x = parse_drawing_callout(callout_id="c_symm_x", text="Symmetry plane X")
    assert callout_x.semantic_intent == "SYMMETRY_X"

    callout_y = parse_drawing_callout(callout_id="c_symm_y", text="Symmetry Y constraint")
    assert callout_y.semantic_intent == "SYMMETRY_Y"


def test_visual_callout_zero_direction_raises():
    with pytest.raises(ValueError, match="direction_vector cannot be zero-length"):
        VisualCallout(
            callout_id="invalid",
            callout_type=CalloutType.ARROW.value,
            location=ImagePoint(0.5, 0.5),
            direction_vector=(0.0, 0.0),
        )


# --- GA-2B.2: Topological Candidate Correlation & Uncertainty ---

def test_correlate_callout_single_unambiguous_candidate():
    callout = parse_drawing_callout(
        callout_id="c_fix",
        text="Fixed face",
        location=ImagePoint(0.1, 0.5),
    )
    candidates = [
        {
            "name": "RootFace",
            "entity_type": "Face",
            "point": (0.0, 10.0, 5.0),
            "index": 1,
            "confidence": 0.95,
        }
    ]
    obs = correlate_callout_with_cad(callout, candidates, target_semantic="FIXED_ROOT")

    assert obs.observation_id == "obs_c_fix"
    assert obs.detected_intent_type == GroundingIntentType.BOUNDARY_CONDITION.value
    assert len(obs.candidate_regions) == 1
    assert obs.selected_region is not None
    assert obs.selected_region.anchor_point == (0.0, 10.0, 5.0)
    assert obs.confidence > 0.85
    assert len(obs.uncertainty_reasons) == 0
    assert obs.requires_confirmation is False


def test_correlate_callout_ambiguous_multiple_candidates():
    callout = parse_drawing_callout(
        callout_id="c_hole",
        text="Mounting hole",
        location=ImagePoint(0.5, 0.5),
    )
    candidates = [
        {"name": "HoleA", "entity_type": "Face", "point": (20.0, 10.0, 5.0), "index": 2},
        {"name": "HoleB", "entity_type": "Face", "point": (80.0, 10.0, 5.0), "index": 3},
    ]
    obs = correlate_callout_with_cad(callout, candidates)

    assert len(obs.candidate_regions) == 2
    assert "AMBIGUOUS_MULTI_CANDIDATE" in obs.uncertainty_reasons
    assert obs.confidence <= 0.60
    assert obs.requires_confirmation is True
    assert obs.status == HITLStatus.NEEDS_CONFIRMATION.value


def test_correlate_callout_zero_candidates():
    callout = parse_drawing_callout(callout_id="c_none", text="External point")
    obs = correlate_callout_with_cad(callout, [])

    assert len(obs.candidate_regions) == 0
    assert "ZERO_CANDIDATES_FOUND" in obs.uncertainty_reasons
    assert obs.confidence == 0.0
    assert obs.requires_confirmation is True
    assert obs.status == HITLStatus.NEEDS_CONFIRMATION.value


def test_correlate_callout_with_perspective_raycast():
    view = ViewProjection(
        viewport_id="V1",
        projection_type="PERSPECTIVE",
        image_width=1000,
        image_height=1000,
        camera_position=(50.0, 10.0, 200.0),
        camera_target=(50.0, 10.0, 50.0),
        up_vector=(0.0, 1.0, 0.0),
        view_width=100.0,
        view_height=100.0,
    )
    callout = parse_drawing_callout(
        callout_id="c_tip",
        text="Apply 1000 N",
        location=ImagePoint(0.5, 0.5),
    )
    candidates = [
        {
            "name": "TipFace",
            "entity_type": "Face",
            "point": (50.0, 10.0, 0.0),
            "normal": (0.0, 0.0, 1.0),
            "index": 1,
        }
    ]
    obs = correlate_callout_with_cad(callout, candidates, view_projection=view)
    assert len(obs.candidate_regions) == 1
    assert obs.selected_region.anchor_point == (50.0, 10.0, 0.0)


# --- GA-2B.3: Mandatory Human-in-the-Loop (HITL) Gate ---

def test_hitl_blocks_unconfirmed_observation():
    """Negative probe: Unconfirmed observation must strictly block intent compilation."""
    callout = parse_drawing_callout(callout_id="c_fix", text="Fix here")
    obs = correlate_callout_with_cad(
        callout,
        [
            {"name": "FaceA", "entity_type": "Face", "point": (0.0, 0.0, 0.0), "index": 1},
            {"name": "FaceB", "entity_type": "Face", "point": (10.0, 0.0, 0.0), "index": 2},
        ],
    )
    workflow = MultimodalHITLWorkflow()
    workflow.register_observation(obs)

    # Attempting to synthesize specs while status is NEEDS_CONFIRMATION
    with pytest.raises(HITLBlockedError, match="pending human confirmation"):
        workflow.synthesize_specs(fail_closed=True)


def test_hitl_low_confidence_forced_to_needs_confirmation():
    callout = parse_drawing_callout(callout_id="c_1", text="Pressure 1.0 MPa")
    # Low confidence candidate (0.75 < 0.85 threshold)
    obs = correlate_callout_with_cad(
        callout,
        [{"name": "FaceA", "entity_type": "Face", "point": (0.0, 0.0, 0.0), "confidence": 0.75}],
    )
    workflow = MultimodalHITLWorkflow(confidence_threshold=0.85)
    registered = workflow.register_observation(obs)

    assert registered.requires_confirmation is True
    assert registered.status == HITLStatus.NEEDS_CONFIRMATION.value


def test_hitl_confirm_and_disambiguate():
    """Confirm an ambiguous observation by choosing a specific candidate semantic."""
    callout = parse_drawing_callout(callout_id="c_hole", text="Hole constraint")
    obs = correlate_callout_with_cad(
        callout,
        [
            {"name": "Hole_Left", "entity_type": "Face", "point": (20.0, 10.0, 0.0), "index": 1},
            {"name": "Hole_Right", "entity_type": "Face", "point": (80.0, 10.0, 0.0), "index": 2},
        ],
    )
    workflow = MultimodalHITLWorkflow()
    workflow.register_observation(obs)

    decision = HITLConfirmationDecision(
        observation_id="obs_c_hole",
        decision="CONFIRM",
        confirmed_by="lead_cae_engineer",
        selected_region_semantic="Hole_Right",
    )
    confirmed_obs = workflow.confirm(decision)

    assert confirmed_obs.status == HITLStatus.CONFIRMED.value
    assert confirmed_obs.confirmed_by == "lead_cae_engineer"
    assert confirmed_obs.selected_region.target_semantic == "Hole_Right"
    assert confirmed_obs.selected_region.anchor_point == (80.0, 10.0, 0.0)

    # Now synthesis succeeds
    bcs, loads, regions = workflow.synthesize_specs()
    assert len(bcs) == 1
    assert bcs[0].region == "Hole_Right"
    assert "Hole_Right" in regions


def test_hitl_confirm_with_parameter_override():
    """Engineer modifies load magnitude during confirmation."""
    callout = parse_drawing_callout(callout_id="c_load", text="Load 1000 N")
    obs = correlate_callout_with_cad(
        callout,
        [{"name": "TipFace", "entity_type": "Face", "point": (100.0, 0.0, 0.0), "index": 1}],
    )
    workflow = MultimodalHITLWorkflow()
    workflow.register_observation(obs)

    decision = HITLConfirmationDecision(
        observation_id="obs_c_load",
        decision="CONFIRM",
        confirmed_by="engineer_chen",
        override_magnitude=1500.0,
        override_unit="N",
    )
    workflow.confirm(decision)

    bcs, loads, regions = workflow.synthesize_specs()
    assert len(loads) == 1
    assert loads[0].magnitude == pytest.approx(1500.0)


def test_hitl_reject_observation():
    callout = parse_drawing_callout(callout_id="c_noise", text="Uncertain artifact")
    obs = correlate_callout_with_cad(
        callout,
        [{"name": "FaceX", "entity_type": "Face", "point": (5.0, 5.0, 0.0), "index": 1}],
    )
    workflow = MultimodalHITLWorkflow()
    workflow.register_observation(obs)

    workflow.reject("obs_c_noise", reason="Artifact is manufacturing watermark, not engineering constraint")
    rejected_obs = workflow.get_observation("obs_c_noise")
    assert rejected_obs.status == HITLStatus.REJECTED.value
    assert "watermark" in rejected_obs.rejection_reason

    # Synthesis ignores rejected observations without blocking
    bcs, loads, regions = workflow.synthesize_specs()
    assert len(bcs) == 0
    assert len(loads) == 0


# --- GA-2B.4: Full-Chain Compilation from Confirmed Multimodal Intent ---

def test_multimodal_intent_to_compiler_action_plan_full_chain():
    """Verify that confirmed multimodal observations feed cleanly into compile_intent_to_actions."""
    # 1. 2D Drawing inputs: Fixed root and transverse pressure load
    callout_bc = parse_drawing_callout(callout_id="bc_1", text="Fixed end support (Encastre)")
    callout_load = parse_drawing_callout(
        callout_id="load_1",
        text="Apply 4.0 MPa uniform pressure",
        direction_vector=(0.0, -1.0),
    )

    # 2. Geometric candidates
    cand_bc = [{"name": "RootFace", "entity_type": "Face", "point": (0.0, 10.0, 5.0), "index": 1}]
    cand_load = [{"name": "TopFace", "entity_type": "Face", "point": (50.0, 20.0, 5.0), "index": 2}]

    obs_bc = correlate_callout_with_cad(callout_bc, cand_bc, target_semantic="FIXED_ROOT")
    obs_load = correlate_callout_with_cad(callout_load, cand_load, target_semantic="TOP_PRESSURE")

    # 3. Register in HITL Workflow
    workflow = MultimodalHITLWorkflow()
    workflow.register_observation(obs_bc)
    workflow.register_observation(obs_load)

    # Explicit confirmation by engineer
    workflow.confirm(HITLConfirmationDecision(observation_id="obs_bc_1", decision="CONFIRM", confirmed_by="cae_eng"))
    workflow.confirm(HITLConfirmationDecision(observation_id="obs_load_1", decision="CONFIRM", confirmed_by="cae_eng"))

    # 4. Synthesize specifications and grounded regions
    bcs, loads, grounded_regions = workflow.synthesize_specs()
    assert len(bcs) == 1
    assert len(loads) == 1
    assert "FIXED_ROOT" in grounded_regions
    assert "TOP_PRESSURE" in grounded_regions

    # 5. Compile into canonical ActionPlan
    geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=20.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210e3, poisson_ratio=0.3),
    )
    step = IntentStepSpec(name="StaticStep", time_period=1.0)
    mesh = IntentMeshSpec(global_size=5.0)

    plan = compile_intent_to_actions(
        model_name="MultimodalModel",
        part_name="BeamPart",
        job_name="MultimodalJob",
        geometry=geom,
        material=mat,
        step=step,
        bcs=bcs,
        loads=loads,
        mesh=mesh,
        grounded_regions=grounded_regions,
    )

    assert plan.model_name == "MultimodalModel"
    assert "EncastreBC" in plan.cae_script
    assert "Pressure" in plan.cae_script
    assert "findAt(((0.0, 10.0, 5.0),))" in plan.cae_script
    assert "findAt(((50.0, 20.0, 5.0),))" in plan.cae_script

    # 6. Preflight checks
    for action in plan.actions:
        pf = preflight_action(action)
        assert pf.passed is True, f"Preflight failed on action {action.action_type}: {pf.blockers}"
