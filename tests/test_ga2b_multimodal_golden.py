"""Regression tests for Track GA-2B: Multimodal Perception & Human-in-the-Loop Golden.

Validates:
1. Certified Evidence Manifest V2 integrity in `machine_validation/ga2b_multimodal_manifest.json`.
2. 100% Fail-closed boundary testing on all 4 negative probes.
3. Clean integration from 2D Blueprint -> VisualCallout -> GroundedRegion -> HITL -> Intent -> Preflight.
"""

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.contracts.geometry import ImagePoint
from abaqus_ai_agent.contracts.multimodal import (
    CalloutType,
    MultimodalSourceType,
    GroundingIntentType,
    HITLStatus,
    VisualCallout,
    GroundingObservation,
    HITLConfirmationDecision,
)
from abaqus_ai_agent.grounding.feature_grounding import GroundedRegion
from abaqus_ai_agent.grounding.multimodal import (
    HITLBlockedError,
    parse_drawing_callout,
    correlate_callout_with_cad,
    MultimodalHITLWorkflow,
)
from abaqus_ai_agent.acceptance import evaluate_result_acceptance


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "machine_validation" / "ga2b_multimodal_manifest.json"


def test_ga2b_multimodal_evidence_manifest_integrity():
    """Verify that the certified Abaqus 2025 GA-2B manifest exists and is QUALIFIED."""
    assert MANIFEST_PATH.exists(), f"GA-2B manifest missing at {MANIFEST_PATH}"
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert data["case_id"] == "GA2B_Multimodal_Golden"
    assert data["status"] == "QUALIFIED"
    assert data["evidence_tier"] == "REAL_ABAQUS"
    assert data["solver"] == "Abaqus 2025"

    wf = data["workflow"]
    assert wf["2d_callout_parsing"] == "PASS"
    assert wf["topological_candidate_correlation"] == "PASS"
    assert wf["mandatory_hitl_gate"] == "PASS"
    assert wf["intent_compiler_actions"] == "PASS"
    assert wf["preflight_checks"] == "PASS"
    assert wf["live_solver_execution"] == "PASS"
    assert wf["odb_extraction"] == "PASS"
    assert wf["equilibrium_balance"] == "PASS"
    assert wf["evidence_v2_acceptance"] == "PASS"

    probes = wf["negative_probes"]
    assert probes["unconfirmed_hitl_blocked"] == "PASS"
    assert probes["observation_rejection_fail_closed"] == "PASS"
    assert probes["missing_required_results_blocked"] == "PASS"
    assert probes["tampered_evidence_blocked"] == "PASS"

    # Physics metrics check
    metrics = data["metrics"]
    assert metrics["applied_force_N"] == pytest.approx(1000.0)
    assert metrics["measured_reaction_force_N"] == pytest.approx(1000.0, rel=1e-3)
    assert metrics["equilibrium_error_percent"] < 0.01
    assert metrics["max_mises_MPa"] > 0.0
    assert metrics["max_displacement_mm"] > 0.0

    # Real solver artifacts check
    arts = data["artifacts"]
    for ext in ("inp", "odb", "sta", "msg", "dat", "log"):
        key = f"Job_GA2B_Multimodal.{ext}"
        assert key in arts, f"Missing artifact {key}"
        assert arts[key]["exists"] is True
        assert len(arts[key]["sha256"]) == 64
        assert arts[key]["size_bytes"] > 0


def test_ga2b_negative_probe_unconfirmed_blocks_execution():
    """Negative Probe 1: Attempting to synthesize intent with unconfirmed observations must fail closed."""
    callout = parse_drawing_callout(callout_id="callout_test_1", text="Fixed at Base")
    candidate = [{"name": "RootFace", "entity_type": "Face", "point": (0.0, 5.0, 10.0), "index": 1}]
    obs = correlate_callout_with_cad(callout, candidate, target_semantic="FIXED_ROOT")

    workflow = MultimodalHITLWorkflow()
    workflow.register_observation(obs)

    # Observation is PENDING / NEEDS_CONFIRMATION -> MUST block
    with pytest.raises(HITLBlockedError, match="pending human confirmation"):
        workflow.synthesize_specs(fail_closed=True)


def test_ga2b_negative_probe_rejected_observation():
    """Negative Probe 2: Explicitly rejected observations must not generate any model actions."""
    callout = parse_drawing_callout(callout_id="callout_test_2", text="Apply 500 N")
    candidate = [{"name": "TipFace", "entity_type": "Face", "point": (100.0, 5.0, 10.0), "index": 2}]
    obs = correlate_callout_with_cad(callout, candidate, target_semantic="TIP_LOAD")

    workflow = MultimodalHITLWorkflow()
    workflow.register_observation(obs)
    workflow.reject("obs_callout_test_2", reason="Load value is deprecated", engineer_id="test_runner")

    bcs, loads, regions = workflow.synthesize_specs(fail_closed=True)
    assert len(bcs) == 0
    assert len(loads) == 0
    assert len(regions) == 0


def test_ga2b_negative_probe_missing_odb_results_blocked():
    """Negative Probe 3: Acceptance engine fails closed when required ODB output is missing."""
    acc = evaluate_result_acceptance(
        result_status="completed",
        odb_status="valid",
        physics_domain="linear_static",
        required_metrics=("reaction_force", "max_mises", "max_displacement"),
        values={"max_mises": 5.29},  # missing displacement & reaction force
        odb_fields=("S",),
        require_evidence=False,
    )
    assert acc.passed is False
    assert acc.result_validity == "RESULT_INVALID"
    assert "missing_required_metric:reaction_force" in acc.blocked
