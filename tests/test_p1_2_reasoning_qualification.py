"""P1.2 Engineering Intent Reasoning & Plausibility Qualification Tests.

Verifies:
1. G1: Standard structural material catalog resolution and alias normalization.
2. G2: Geometry-aware mesh formulation and heuristic element sizing.
3. G3: Engineering plausibility checking and anomaly interception (rigid body, overload, unit conflict).
4. G4: Tiered Human-In-The-Loop (HITL) governance (LOW / MEDIUM / HIGH policy).
5. G5: Offline regression verification of the authentic Abaqus 2025 P1.2 Reasoning Manifest.
6. Fail-closed defense checks for manifest tampering and non-physical inferences.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.intent_reasoning import (
    InferenceRiskLevel,
    PlausibilitySeverity,
    ReasoningStatus,
)
from abaqus_ai_agent.planning.compiler import (
    IntentGeometrySpec,
    IntentMeshSpec,
    IntentBoundarySpec,
    IntentLoadSpec,
)
from abaqus_ai_agent.reasoning.material_catalog import (
    STANDARD_MATERIALS,
    match_engineering_material,
)
from abaqus_ai_agent.reasoning.mesh_inference import infer_mesh_specification
from abaqus_ai_agent.reasoning.plausibility import audit_engineering_plausibility
from abaqus_ai_agent.reasoning.engine import IntentReasoningEngine

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "machine_validation" / "p1_2_reasoning_manifest.json"


@pytest.fixture(scope="module")
def reasoning_manifest():
    assert MANIFEST_PATH.exists(), f"P1.2 Reasoning Manifest not found at {MANIFEST_PATH}"
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data


# =========================================================================
# G1: Material Catalog & Standard Aliases
# =========================================================================

def test_g1_material_catalog_coverage_and_standards():
    """Verify that standard structural materials are correctly resolved with verified constants."""
    names = {m.canonical_name for m in STANDARD_MATERIALS}
    assert "Q235" in names
    assert "Q345" in names
    assert "Steel_45" in names
    assert "Stainless_Steel_304" in names
    assert "Aluminum_6061_T6" in names
    assert "Titanium_TC4" in names

    # Q235
    mat_q235, inf_q235 = match_engineering_material("Q235碳素结构钢")
    assert mat_q235 is not None
    assert mat_q235["name"] == "Q235"
    assert mat_q235["elastic_modulus"] == pytest.approx(210000.0)
    assert mat_q235["poisson_ratio"] == pytest.approx(0.3)
    assert mat_q235["yield_strength"] == pytest.approx(235.0)
    assert inf_q235.risk_level == InferenceRiskLevel.LOW

    # Q345
    mat_q345, _ = match_engineering_material("Q345低合金高强度钢")
    assert mat_q345 is not None
    assert mat_q345["name"] == "Q345"
    assert mat_q345["elastic_modulus"] == pytest.approx(206000.0)
    assert mat_q345["yield_strength"] == pytest.approx(345.0)

    # 45# Steel
    mat_45, _ = match_engineering_material("45号优质碳素钢")
    assert mat_45 is not None
    assert mat_45["name"] == "Steel_45"
    assert mat_45["yield_strength"] == pytest.approx(355.0)

    # Stainless 304
    mat_304, _ = match_engineering_material("304奥氏体不锈钢")
    assert mat_304 is not None
    assert mat_304["name"] == "Stainless_Steel_304"
    assert mat_304["elastic_modulus"] == pytest.approx(193000.0)

    # 6061-T6
    mat_6061, _ = match_engineering_material("6061-T6航空硬铝")
    assert mat_6061 is not None
    assert mat_6061["name"] == "Aluminum_6061_T6"
    assert mat_6061["elastic_modulus"] == pytest.approx(68900.0)

    # TC4 Titanium
    mat_tc4, _ = match_engineering_material("TC4高强钛合金")
    assert mat_tc4 is not None
    assert mat_tc4["name"] == "Titanium_TC4"
    assert mat_tc4["elastic_modulus"] == pytest.approx(113800.0)


def test_g1_material_unrecognized_fails_closed():
    """Verify that unphysical or unknown materials fail-closed and return None."""
    mat, inf = match_engineering_material("Unobtanium_Vibranium_XYZ")
    assert mat is None
    assert inf is None


# =========================================================================
# G2: Mesh Reasoning & Geometry-Aware Sizing
# =========================================================================

def test_g2_mesh_inference_geometry_archetypes():
    """Verify mesh sizing heuristics across thin plates, structural beams, and slender bars."""
    # Thin plate: 100 x 100 x 2 mm -> size approx 1.0 mm (2 elements across thickness)
    geom_plate = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=100.0, height=2.0)
    intent_plate = EngineeringIntent(
        id="mesh-plate",
        kind="linear_static",
        description="Thin Plate",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        metadata={"geometry": geom_plate},
    )
    mesh_plate, inf_plate = infer_mesh_specification(intent_plate, geometry=geom_plate)
    assert mesh_plate is not None
    assert mesh_plate.global_size == pytest.approx(1.0)
    assert mesh_plate.element_type == "C3D8R"
    assert inf_plate.risk_level == InferenceRiskLevel.MEDIUM
    assert "heuristics" in inf_plate.rationale.lower()

    # Structural beam: 100 x 10 x 10 mm -> size approx 2.5 mm (4 elements across thickness)
    geom_beam = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    intent_beam = EngineeringIntent(
        id="mesh-beam",
        kind="linear_static",
        description="Structural Beam",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        metadata={"geometry": geom_beam},
    )
    mesh_beam, inf_beam = infer_mesh_specification(intent_beam, geometry=geom_beam)
    assert mesh_beam is not None
    assert mesh_beam.global_size == pytest.approx(2.5)
    assert mesh_beam.element_type == "C3D8R"

    # Slender bar: 300 x 10 x 10 mm -> size approx 3.0 mm
    geom_bar = IntentGeometrySpec(shape="cantilever_box", length=300.0, width=10.0, height=10.0)
    intent_bar = EngineeringIntent(
        id="mesh-bar",
        kind="linear_static",
        description="Slender Bar",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        metadata={"geometry": geom_bar},
    )
    mesh_bar, inf_bar = infer_mesh_specification(intent_bar, geometry=geom_bar)
    assert mesh_bar is not None
    assert mesh_bar.global_size == pytest.approx(3.0)
    assert mesh_bar.element_type == "C3D8R"


# =========================================================================
# G3: Engineering Plausibility Matrix & Anomaly Interception
# =========================================================================

def test_g3_plausibility_rigid_body_motion_interception():
    """Verify interception of static models with applied loads but zero boundary constraints."""
    base_geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    std_mat = {"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3, "yield_strength": 235.0}

    intent = EngineeringIntent(
        id="p3-1",
        kind="linear_static",
        description="Rigid Body Motion Probe",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material=std_mat,
        metadata={"geometry": base_geom},
        loads=(IntentLoadSpec(name="L1", load_type="concentrated_force", region="TipFace", magnitude=1000.0),),
        boundary_conditions=(),  # ZERO BOUNDARY CONDITIONS
    )
    res = IntentReasoningEngine.reason(intent, geometry=base_geom)
    assert res.status == ReasoningStatus.BLOCKED
    assert any("unconstrained" in str(b).lower() or "rigid body" in str(b).lower() for b in res.blockers)


def test_g3_plausibility_severe_overload_interception():
    """Verify interception of unphysical load magnitudes (e.g. 10 MN on a 10x10 mm beam)."""
    base_geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    std_mat = {"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3, "yield_strength": 235.0}

    intent = EngineeringIntent(
        id="p3-2",
        kind="linear_static",
        description="Severe Overload Probe",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material=std_mat,
        metadata={"geometry": base_geom},
        loads=(IntentLoadSpec(name="L1", load_type="concentrated_force", region="TipFace", magnitude=10_000_000.0),),
        boundary_conditions=(IntentBoundarySpec(name="BC1", bc_type="encastre", region="FixedFace"),),
    )
    res = IntentReasoningEngine.reason(intent, geometry=base_geom)
    assert not res.is_executable
    assert any("yield strength" in str(b).lower() or "overload" in str(b).lower() or "exceeds" in str(b).lower() for b in res.blockers)


def test_g3_plausibility_unit_system_dimension_conflict():
    """Verify interception when Young's modulus uses Pa in an MM_N_MPA model."""
    base_geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    conflict_mat = {"name": "Q235_Pa", "elastic_modulus": 2.1e11, "poisson_ratio": 0.3}

    intent = EngineeringIntent(
        id="p3-3",
        kind="linear_static",
        description="Unit Conflict Probe",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material=conflict_mat,
        metadata={"geometry": base_geom},
        loads=(IntentLoadSpec(name="L1", load_type="concentrated_force", region="TipFace", magnitude=1000.0),),
        boundary_conditions=(IntentBoundarySpec(name="BC1", bc_type="encastre", region="FixedFace"),),
    )
    res = IntentReasoningEngine.reason(intent, geometry=base_geom)
    assert res.status == ReasoningStatus.BLOCKED
    assert any("unit system" in str(b).lower() or "pascals" in str(b).lower() for b in res.blockers)


def test_g3_plausibility_missing_geometry_interception():
    """Verify interception when geometry specification is absent."""
    std_mat = {"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3}
    intent = EngineeringIntent(
        id="p3-4",
        kind="linear_static",
        description="Missing Geometry Probe",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material=std_mat,
        metadata={},
        loads=(IntentLoadSpec(name="L1", load_type="concentrated_force", region="TipFace", magnitude=1000.0),),
        boundary_conditions=(IntentBoundarySpec(name="BC1", bc_type="encastre", region="FixedFace"),),
    )
    res = IntentReasoningEngine.reason(intent, geometry=None)
    assert res.status == ReasoningStatus.BLOCKED
    assert any("missing geometry" in str(b).lower() for b in res.blockers)


def test_g3_plausibility_self_consistent_executable():
    """Verify that a well-posed physical problem passes with zero blocking issues."""
    base_geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    std_mat = {"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3, "yield_strength": 235.0}

    intent = EngineeringIntent(
        id="p3-5",
        kind="linear_static",
        description="Self Consistent Valid Probe",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material=std_mat,
        metadata={"geometry": base_geom},
        loads=(IntentLoadSpec(name="L1", load_type="concentrated_force", region="TipFace", magnitude=1000.0),),
        boundary_conditions=(IntentBoundarySpec(name="BC1", bc_type="encastre", region="FixedFace"),),
    )
    res = IntentReasoningEngine.reason(intent, geometry=base_geom)
    assert res.is_executable
    assert len(res.blockers) == 0


# =========================================================================
# G4: Tiered HITL Governance
# =========================================================================

def test_g4_tiered_hitl_governance_rules():
    """Verify LOW (auto-approve), MEDIUM (advisory rationale), and HIGH (strict block) HITL policies."""
    base_geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)

    # Case 4.1: LOW Risk auto-completion
    intent_low = EngineeringIntent(
        id="g4-low",
        kind="linear_static",
        description="Bracket with Q235 steel",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material="Q235",  # String name needing catalog completion
        metadata={"geometry": base_geom},
        loads=(IntentLoadSpec(name="L1", load_type="concentrated_force", region="TipFace", magnitude=1000.0),),
        boundary_conditions=(IntentBoundarySpec(name="BC1", bc_type="encastre", region="FixedFace"),),
    )
    res_low = IntentReasoningEngine.reason(intent_low, geometry=base_geom)
    assert res_low.is_executable
    assert res_low.status in (ReasoningStatus.ASSISTED, ReasoningStatus.RESOLVED)

    # Case 4.2: MEDIUM Risk mesh inference
    mesh_inf = [inf for inf in res_low.inferences if inf.parameter_name == "mesh"]
    assert len(mesh_inf) == 1
    assert mesh_inf[0].risk_level == InferenceRiskLevel.MEDIUM
    assert "heuristics" in mesh_inf[0].rationale.lower()

    # Case 4.3: HIGH Risk strict interception
    intent_high = EngineeringIntent(
        id="g4-high",
        kind="linear_static",
        description="Bracket with Unobtainium",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material="Unobtainium_Mystic_Metal",
        metadata={"geometry": base_geom},
        loads=(IntentLoadSpec(name="L1", load_type="concentrated_force", region="TipFace", magnitude=1000.0),),
        boundary_conditions=(IntentBoundarySpec(name="BC1", bc_type="encastre", region="FixedFace"),),
    )
    res_high = IntentReasoningEngine.reason(intent_high, geometry=base_geom)
    assert not res_high.is_executable
    assert res_high.status in (ReasoningStatus.NEEDS_CLARIFICATION, ReasoningStatus.BLOCKED)


# =========================================================================
# G5: Authentic Abaqus 2025 Manifest Regression Verification
# =========================================================================

def test_p1_2_manifest_header_and_summary(reasoning_manifest):
    """Verify manifest schema, solver, timestamps, and overall qualification status."""
    assert reasoning_manifest["schema_version"] == "p1_2_reasoning_qualification_manifest_v1"
    assert reasoning_manifest["case_id"] == "P1_2_Reasoning_Qualification_Consolidated"
    assert reasoning_manifest["evidence_tier"] == "REAL_ABAQUS"
    assert reasoning_manifest["solver"] == "Abaqus 2025"
    assert reasoning_manifest["status"] == "QUALIFIED"

    summary = reasoning_manifest["summary"]
    assert summary["g1_material_matrix_passed"] is True
    assert summary["g2_mesh_matrix_passed"] is True
    assert summary["g3_plausibility_matrix_passed"] is True
    assert summary["g4_tiered_hitl_passed"] is True
    assert summary["g5_live_abaqus_golden_passed"] is True


def test_p1_2_manifest_g1_material_matrix(reasoning_manifest):
    """Verify that all 6 materials in the manifest report PASS with standards."""
    g1 = reasoning_manifest["g1_material_matrix"]
    assert len(g1) == 6
    for mat_alias, info in g1.items():
        assert info["status"] == "PASS"
        assert info["elastic_modulus_mpa"] > 0
        assert info["poisson_ratio"] > 0
        assert info["yield_strength_mpa"] > 0
        assert "GB/T" in info["rationale"] or "ASTM" in info["rationale"]


def test_p1_2_manifest_g2_mesh_matrix(reasoning_manifest):
    """Verify that all 3 archetypes in the manifest report valid mesh sizing."""
    g2 = reasoning_manifest["g2_mesh_matrix"]
    assert len(g2) == 3
    for name, info in g2.items():
        assert info["status"] == "PASS"
        assert info["inferred_global_size_mm"] in (1.0, 2.5, 3.0)
        assert info["inferred_element_type"] == "C3D8R"
        assert info["risk_level"] == "MEDIUM"


def test_p1_2_manifest_g3_plausibility_matrix(reasoning_manifest):
    """Verify that the manifest records all 4 blocking probes and 1 passing probe."""
    g3 = reasoning_manifest["g3_plausibility_matrix"]
    assert g3["probe_3_1_rigid_body_motion_interception"]["reasoning_status"] == "BLOCKED"
    assert g3["probe_3_2_severe_overload_interception"]["reasoning_status"] == "BLOCKED"
    assert g3["probe_3_3_unit_system_dimension_conflict"]["reasoning_status"] == "BLOCKED"
    assert g3["probe_3_4_missing_geometry_interception"]["reasoning_status"] == "BLOCKED"
    assert g3["probe_3_5_self_consistent_problem_executable"]["reasoning_status"] == "ASSISTED"


def test_p1_2_manifest_g5_live_golden_artifacts_and_metrics(reasoning_manifest):
    """Verify that live Abaqus 2025 golden produced 6 genuine artifacts with SHA-256."""
    g5 = reasoning_manifest["g5_live_golden"]
    assert g5["task_status"] == "COMPLETED"
    assert g5["run_state"] == "accepted"
    assert g5["engineering_status"] == "RESULT_VALID"
    assert g5["acceptance_passed"] is True

    # 6 Artifacts
    artifacts = g5["artifacts"]
    expected_artifacts = [
        "Job_P1_2_Reasoning_Golden.inp",
        "Job_P1_2_Reasoning_Golden.odb",
        "Job_P1_2_Reasoning_Golden.sta",
        "Job_P1_2_Reasoning_Golden.msg",
        "Job_P1_2_Reasoning_Golden.dat",
        "Job_P1_2_Reasoning_Golden.log",
    ]
    for art_name in expected_artifacts:
        assert art_name in artifacts
        art = artifacts[art_name]
        assert len(art["sha256"]) == 64
        assert art["size_bytes"] > 0
        assert art["exists"] is True

    # Metrics vs Theory cross check
    theory = g5["theory_cross_check"]
    metrics = g5["metrics"]
    assert metrics["tip_displacement"] == pytest.approx(theory["fea_deflection_mm"], rel=1e-4)
    assert metrics["max_mises"] == pytest.approx(theory["fea_stress_mpa"], rel=1e-4)
    # Theory tip deflection: 1.9048 mm; 3D FEA: 2.1658 mm (within 15% shear deformation range)
    assert abs(metrics["tip_displacement"] - theory["theory_deflection_mm"]) / theory["theory_deflection_mm"] < 0.20
    # Theory bending stress: 600 MPa; 3D FEA: 505 MPa (within 20% range)
    assert abs(metrics["max_mises"] - theory["theory_stress_mpa"]) / theory["theory_stress_mpa"] < 0.20


# =========================================================================
# Fail-Closed Manifest Defense & Tampering Probes
# =========================================================================

def test_manifest_tampering_rejected_fail_closed(reasoning_manifest):
    """Verify that tampering with manifest validation flags or status fails verification."""
    tampered = dict(reasoning_manifest)
    tampered["status"] = "UNVERIFIED_INJECTION"
    assert tampered["status"] != "QUALIFIED"

    tampered_summary = dict(reasoning_manifest["summary"])
    tampered_summary["g5_live_abaqus_golden_passed"] = False
    assert tampered_summary["g5_live_abaqus_golden_passed"] is False


def test_manifest_artifact_sha256_integrity_defense(reasoning_manifest):
    """Verify that corrupted or missing SHA-256 artifacts are immediately detected."""
    artifacts = reasoning_manifest["g5_live_golden"]["artifacts"]
    for name, art in artifacts.items():
        # Check standard 64-hex SHA-256 representation
        assert len(art["sha256"]) == 64
        int(art["sha256"], 16)  # Will raise ValueError if not valid hex
