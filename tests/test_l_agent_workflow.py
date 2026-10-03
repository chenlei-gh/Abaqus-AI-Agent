"""Tests for Phase L — Autonomous Agent Engineering Workflow Validation (L1–L4).

Tests deterministic software contracts, JEV routing, fail-closed ambiguity handling,
MaterialResolver environmental preflight, solver failure diagnosis patterns, and
vision/viewport topology grounding logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from abaqus_ai_agent.contracts.geometry import ImagePoint
from abaqus_ai_agent.contracts.material_record import (
    MaterialCondition,
    MaterialCurve,
    MaterialIdentity,
    MaterialProperty,
    MaterialRecord,
    MaterialSource,
)
from abaqus_ai_agent.contracts.material_resolver import MaterialResolver
from abaqus_ai_agent.diagnostics.solver_patterns import (
    DiagnosticIssue,
    diagnose_solver_artifacts,
)
from abaqus_ai_agent.grounding.resolver import (
    region_expression,
    resolve_image_point,
    selection_from_candidates,
)
from abaqus_ai_agent.typesafe_intent import JevDecisionBundle, JevIntentRouter


# ==============================================================================
# L1: End-to-End JEV Intent Workflow Contracts
# ==============================================================================
def test_l1_jev_intent_routing_complete():
    """Verify L1 JEV properly routes complete engineering prompt to typed intent."""
    router = JevIntentRouter()
    prompt = "对100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm和最大Mises应力不超过600MPa。"
    res = router.route(prompt)

    assert res.status == "ROUTED"
    assert res.intent is not None
    assert res.decision_bundle is not None
    assert res.decision_bundle.physics_choice.value == "linear_static"
    assert res.decision_bundle.completeness_score.score >= 4.0
    assert res.decision_bundle.is_well_constrained_noul.is_yes is True
    assert len(res.intent.acceptance_criteria) >= 1


def test_l1_jev_ambiguity_gate_fail_closed():
    """Verify L1 JEV fails closed and blocks incomplete/ambiguous natural language prompts."""
    router = JevIntentRouter()
    ambiguous_prompts = [
        "算一下梁",
        "受力分析",
        "A bar under some load",
    ]
    for prompt in ambiguous_prompts:
        res = router.route(prompt)
        assert res.status == "NEEDS_CLARIFICATION", f"Prompt '{prompt}' should fail closed"
        assert res.intent is None
        assert res.clarification_prompt is not None


# ==============================================================================
# L2: Material Intelligence Grounding Contracts
# ==============================================================================
@pytest.fixture
def pa66_gf30_record() -> MaterialRecord:
    identity = MaterialIdentity(
        polymer_family="PA66",
        manufacturer="BASF",
        grade="Ultramid A3WG6",
        trade_name="Ultramid",
        reinforcement_type="glass_fiber",
        reinforcement_content=30.0,
    )
    source = MaterialSource(
        provider="CAMPUS",
        source_type="iso_database",
        locator="CAMPUS-ISO-BASF-Ultramid-A3WG6",
        retrieved_at="2026-10-03T00:00:00Z",
        evidence_level="certified_lab",
    )
    cond_23 = MaterialCondition(
        temperature=23.0,
        temperature_unit="C",
        humidity_state="dry",
        test_standard="ISO 527-1/-2",
    )
    cond_80 = MaterialCondition(
        temperature=80.0,
        temperature_unit="C",
        humidity_state="dry",
        test_standard="ISO 527-1/-2",
    )
    props = (
        MaterialProperty(
            name="youngs_modulus",
            value=8500.0,
            unit="MPa",
            quantity="stress",
            condition=cond_23,
        ),
        MaterialProperty(
            name="youngs_modulus",
            value=4500.0,
            unit="MPa",
            quantity="stress",
            condition=cond_80,
        ),
        MaterialProperty(
            name="poisson_ratio",
            value=0.35,
            unit="dimensionless",
            quantity="dimensionless",
            condition=cond_23,
        ),
        MaterialProperty(
            name="density",
            value=1360.0,
            unit="kg/m3",
            quantity="density",
            condition=cond_23,
        ),
    )
    return MaterialRecord(
        identity=identity,
        source=source,
        default_condition=cond_23,
        properties=props,
    )


def test_l2_material_resolver_matched_temperature(pa66_gf30_record):
    """Verify MaterialResolver maps condition-specific polymer properties to Abaqus MaterialDefinition."""
    res = MaterialResolver.resolve(
        pa66_gf30_record,
        target_temperature=23.0,
        target_unit_system="MM_N_MPA",
    )
    assert res.status in ("RESOLVED", "ASSISTED")
    mat_def = res.material_definition
    assert mat_def is not None
    assert mat_def.name == "PA66_BASF_Ultramid_A3WG6"
    assert mat_def.elastic is not None
    assert mat_def.elastic.youngs_modulus == 8500.0
    assert mat_def.elastic.poisson_ratio == 0.35
    assert mat_def.density == pytest.approx(1.36e-9, rel=1e-5)


def test_l2_material_resolver_extreme_temp_blocked(pa66_gf30_record):
    """Verify MaterialResolver fails closed on uncharacterized high-temperature operating conditions."""
    res = MaterialResolver.resolve(
        pa66_gf30_record,
        target_temperature=160.0,  # Far from 23 C and 80 C
        allow_assisted_assumptions=False,
    )
    assert res.status == "BLOCKED"
    assert res.material_definition is None
    assert any("Fail-closed on uncharacterized thermal degradation" in d for d in res.diagnostics)


# ==============================================================================
# L3: Solver Failure Diagnostics & Remediation Contracts
# ==============================================================================
def test_l3_solver_diagnostics_singularity_extraction():
    """Verify Solver Doctor correctly extracts numerical singularities and cutbacks from .msg output."""
    sample_msg = """
 ***WARNING: SOLVER PROBLEM. NUMERICAL SINGULARITY WHEN PROCESSING NODE 12 D.O.F. 1
 ***ERROR: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT
 ***WARNING: THE SYSTEM MATRIX HAS 3 NEGATIVE EIGENVALUES
    """
    sample_sta = """
  1  1  1  0.100  0.100  1.000  5  10  U
    """
    issues = diagnose_solver_artifacts(
        msg_text=sample_msg,
        sta_text=sample_sta,
        job_status="FAILED",
    )
    issue_ids = [i.diagnosis_id for i in issues]
    assert "NUMERICAL_SINGULARITY" in issue_ids
    assert "NEGATIVE_EIGENVALUE" in issue_ids
    assert "TOO_MANY_CUTBACKS" in issue_ids

    # Verify suggested remediation is structured and actionable
    sing_issue = next(i for i in issues if i.diagnosis_id == "NUMERICAL_SINGULARITY")
    assert sing_issue.suggested_remediation is not None
    assert "constraint" in sing_issue.suggested_remediation.lower() or "boundary" in sing_issue.suggested_remediation.lower()


# ==============================================================================
# L4: Vision & Viewport Topology Grounding Contracts
# ==============================================================================
def test_l4_viewport_grounding_resolution_and_find_at():
    """Verify 2D viewport coordinates accurately resolve to candidate face and synthesize findAt."""
    click_pt = ImagePoint(0.1, 0.5)
    probe = {
        "faces": [
            {
                "instance": "Beam-1",
                "index": 0,
                "entity_type": "Face",
                "entity_key": "Face:0",
                "centroid": (0.0, 5.0, 5.0),
                "locator_point": (0.0, 5.0, 5.0),
                "normal": (-1.0, 0.0, 0.0),
                "screen": (0.1, 0.5),
                "screen_polygon": [(0.05, 0.3), (0.15, 0.3), (0.15, 0.7), (0.05, 0.7)],
                "facing_score": 1.0,
                "camera_depth": 50.0,
            },
            {
                "instance": "Beam-1",
                "index": 1,
                "entity_type": "Face",
                "entity_key": "Face:1",
                "centroid": (100.0, 5.0, 5.0),
                "locator_point": (100.0, 5.0, 5.0),
                "normal": (1.0, 0.0, 0.0),
                "screen": (0.9, 0.5),
                "screen_polygon": [(0.85, 0.3), (0.95, 0.3), (0.95, 0.7), (0.85, 0.7)],
                "facing_score": 0.2,
                "camera_depth": 150.0,
            },
        ]
    }

    res = resolve_image_point("intent_grounding", click_pt, probe)
    assert res.selected is not None
    assert res.selected.entity_key == "Face:0"
    assert res.selected.centroid == (0.0, 5.0, 5.0)

    sel = selection_from_candidates([res.selected], name="RootSet")
    expr = region_expression(sel.targets[0], variable="inst")
    assert "inst.faces.findAt" in expr
    assert "0.0, 5.0, 5.0" in expr


# ==============================================================================
# Verified Manifest Integrity Gate
# ==============================================================================
def test_l_agent_workflow_manifest_integrity():
    """Verify Phase L evidence manifest exists, contains 4 gates, and all gates passed."""
    evidence_path = Path(__file__).resolve().parents[1] / "machine_validation" / "l_agent_workflow_evidence.json"
    assert evidence_path.exists(), "Phase L evidence manifest must exist"

    with open(evidence_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["suite_name"] == "Phase L Autonomous Agent Engineering Workflow Validation"
    assert data["gate_count"] == 4
    assert data["passed_count"] == 4
    assert data["all_passed"] is True

    gate_ids = [g["gate_id"] for g in data["gates"]]
    assert "L1_E2E_WORKFLOW" in gate_ids
    assert "L2_MATERIAL_INTELLIGENCE" in gate_ids
    assert "L3_SOLVER_HEALING" in gate_ids
    assert "L4_VIEWPORT_GROUNDING" in gate_ids

    # Validate that every gate possesses non-empty cryptographic SHA-256 artifact hashes
    for gate in data["gates"]:
        artifacts = gate.get("artifacts", {})
        assert len(artifacts) >= 3, f"Gate {gate['gate_id']} missing artifact hashes"
        for k, v in artifacts.items():
            assert len(v) == 64, f"Invalid SHA-256 in gate {gate['gate_id']}: {k}={v}"
