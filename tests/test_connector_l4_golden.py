"""Regression & Negative Probes for Kinematic Connectors & Mechanism Joints L4.

Validates:
1. Certified Evidence Manifest V2 integrity in `machine_validation/connector_l4_manifest.json`.
2. Full Agent-chain: EngineeringIntent -> compile_intent_to_actions -> preflight_plan -> acceptance.
3. 100% Fail-closed boundary testing on all 9 negative probes.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.connector import (
    ConnectorEndpointSpec,
    ConnectorOrientationSpec,
    ConnectorBehaviorSpec,
    ConnectorElasticitySpec,
    ConnectorDampingSpec,
    IntentConnectorSpec,
    ConnectorKinematicsVerification,
)
from abaqus_ai_agent.contracts.evidence import build_evidence_manifest_v2
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import MaterialDefinition, ElasticProperties
from abaqus_ai_agent.planning.compiler import (
    compile_intent_to_actions,
    IntentGeometrySpec,
    IntentStepSpec,
    IntentMeshSpec,
)
from abaqus_ai_agent.actions import builders
from abaqus_ai_agent.validation.preflight import preflight_action, preflight_plan

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "machine_validation" / "connector_l4_manifest.json"


def test_connector_l4_evidence_manifest_integrity():
    """Verify that the certified Abaqus 2025 Kinematic Connector L4 manifest exists and is QUALIFIED."""
    assert MANIFEST_PATH.exists(), f"Connector L4 manifest missing at {MANIFEST_PATH}"
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert data["case_id"] == "MP_Connector_L4_Golden"
    assert data["status"] == "QUALIFIED"
    assert data["evidence_tier"] == "REAL_ABAQUS"
    assert data["solver"] == "Abaqus 2025"
    assert data["compiler_chain_verified"] is True

    wf = data["workflow"]
    assert wf["intent_connector_contract"] == "PASS"
    assert wf["canonical_compiler"] == "PASS"
    assert wf["preflight_checks"] == "PASS"
    assert wf["live_solver_execution"] == "PASS"
    assert wf["odb_extraction"] == "PASS"
    assert wf["connector_kinematics_gate"] == "PASS"
    assert wf["evidence_v2_manifest"] == "PASS"
    assert wf["acceptance"] == "PASS"

    probes = data["negative_probes"]
    for i in range(1, 10):
        key = [k for k in probes if f"probe_{i}_" in k][0]
        assert probes[key] == "PASS", f"Negative probe {key} failed verification"

    # Physics metrics check from real Abaqus solver
    metrics = data["metrics"]
    assert metrics["max_joint_drift_mm"] <= 1e-3
    assert metrics["max_joint_drift_mm"] > 0.0
    assert metrics["max_relative_rotation_rad"] >= 0.01
    assert metrics["max_relative_rotation_deg"] >= 2.0
    assert metrics["period_error_percent"] <= 5.0
    assert metrics["energy_loss_ratio"] <= 0.03
    assert metrics["frame_count"] >= 20

    # Real solver artifacts check (6 required roles)
    arts = data["artifacts"]
    for ext in ("inp", "odb", "sta", "msg", "dat", "log"):
        key = f"Job_Connector_L4.{ext}"
        assert key in arts, f"Missing artifact {key}"
        assert arts[key]["exists"] is True
        assert len(arts[key]["sha256"]) == 64
        assert arts[key]["size_bytes"] > 0

    acc = data["acceptance"]
    assert acc["passed"] is True
    assert acc["status"] == "PASS"
    assert acc["result_validity"] == "VALID"
    assert acc["gates"]["connector_kinematics"] == "PASS"
    assert acc["gates"]["evidence_sufficiency"] == "PASS"
    assert acc["gates"]["required_results"] == "PASS"


def test_connector_l4_intent_compilation_and_preflight():
    """Verify clean full-chain compilation from IntentConnectorSpec through Compiler to Preflight."""
    ep_a = ConnectorEndpointSpec(name="RP1", point_coords=(0.0, 0.0, 0.0), reference_point_name="RP1")
    ep_b = ConnectorEndpointSpec(name="RP2", point_coords=(0.0, 0.0, 10.0), reference_point_name="RP2")
    orient = ConnectorOrientationSpec(name="Csys_Hinge", point1=(0.0, 0.0, 1.0), point2=(1.0, 0.0, 0.0))
    behav = ConnectorBehaviorSpec(
        name="HingeBehav",
        elasticity=ConnectorElasticitySpec(components=(4,), stiffness=(5000.0,)),
        damping=ConnectorDampingSpec(components=(4,), damping_coefficient=(10.0,)),
    )
    conn_spec = IntentConnectorSpec(
        name="Joint1",
        connector_type="HINGE",
        endpoint_a=ep_a,
        endpoint_b=ep_b,
        orientation=orient,
        behavior=behav,
    )

    intent = EngineeringIntent(
        id="intent-test-conn",
        kind="mechanism_joint",
        description="Kinematic connector test",
        connectors=(conn_spec,),
    )
    assert len(intent.connectors) == 1

    plan = compile_intent_to_actions(
        model_name="Model_Test",
        part_name="Part1",
        job_name="Job_Test",
        geometry=IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0),
        material=MaterialDefinition(name="Steel", elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3)),
        connectors=intent.connectors,
    )

    # Check plan actions contain wire_connector and connector_section
    act_types = [a.action_type for a in plan.actions]
    assert "connector_section" in act_types
    assert "wire_connector" in act_types

    # Preflight check on plan
    pf_res = preflight_plan(plan.actions)
    assert pf_res.passed is True
    assert len(pf_res.blockers) == 0


def test_connector_negative_probe_1_missing_endpoint():
    """Negative Probe 1: Missing endpoint must trigger preflight blocker."""
    act = builders.wire_connector("M", "C1", "Sec1", point1_name="", point2_name="RP2")
    res = preflight_action(act)
    assert res.passed is False
    assert any("endpoints" in b["name"] for b in res.blockers)


def test_connector_negative_probe_2_self_connection():
    """Negative Probe 2: Self connection (A == B) must trigger preflight blocker."""
    act = builders.wire_connector("M", "C2", "Sec1", point1_name="RP_Same", point2_name="RP_Same")
    res = preflight_action(act)
    assert res.passed is False
    assert any("endpoints_distinct" in b["name"] for b in res.blockers)


def test_connector_negative_probe_3_undefined_section():
    """Negative Probe 3: Referencing undefined section must trigger preflight blocker."""
    actions = [
        builders.reference_point("M", "RP1", (0, 0, 0)),
        builders.reference_point("M", "RP2", (0, 0, 10)),
        builders.wire_connector("M", "C3", "NonExistentSection", point1_name="RP1", point2_name="RP2"),
    ]
    res = preflight_plan(actions)
    assert res.passed is False
    assert any("connector_section_defined" in b["name"] for b in res.blockers)


def test_connector_negative_probe_4_missing_orientation():
    """Negative Probe 4: HINGE connector missing orientation must trigger preflight blocker."""
    actions = [
        builders.reference_point("M", "RP1", (0, 0, 0)),
        builders.reference_point("M", "RP2", (0, 0, 10)),
        builders.connector_section("M", "HingeSec", assembled_type="HINGE"),
        builders.wire_connector("M", "C4", "HingeSec", point1_name="RP1", point2_name="RP2", orientation=None),
    ]
    res = preflight_plan(actions)
    assert res.passed is False
    assert any("connector_orientation_required" in b["name"] for b in res.blockers)


def test_connector_negative_probe_5_invalid_connector_type():
    """Negative Probe 5: Invalid assembled type must trigger preflight blocker."""
    act = builders.connector_section("M", "SecInv", assembled_type="INVALID_FREE_TYPE")
    res = preflight_action(act)
    assert res.passed is False
    assert any("assembled_type_valid" in b["name"] for b in res.blockers)


def test_connector_negative_probe_6_missing_required_odb_fields(tmp_path):
    """Negative Probe 6: Missing required ODB fields (CU/CTF) must cause Acceptance BLOCKED / RESULT_INVALID."""
    manifest = build_evidence_manifest_v2(
        run_id="run_p6",
        case_id="P6",
        artifacts_dir=str(tmp_path),
        artifact_filenames=[],
    )
    acc = evaluate_result_acceptance(
        result_status="completed",
        physics_domain="connector",
        connector_kinematics=ConnectorKinematicsVerification(passed=True, status="pass"),
        values={"connector_relative_motion": 0.1, "connector_force": 10.0},
        criteria=(),
        odb_fields=("U", "UR"), # Missing CU, CTF
        evidence_manifest=manifest,
    )
    assert acc.passed is False
    assert acc.result_validity == "RESULT_INVALID"
    assert "missing_required_field:CU" in acc.failures or "missing_required_field:CTF" in acc.failures


def test_connector_negative_probe_7_evidence_tampering(tmp_path):
    """Negative Probe 7: Evidence hash mismatch must fail closed at Gate 3."""
    # Create fake files
    fake_files = []
    for role in ("inp", "odb", "msg", "dat", "sta", "log"):
        fname = f"Job.{role}"
        (tmp_path / fname).write_text("valid", encoding="utf-8")
        fake_files.append(fname)

    manifest = build_evidence_manifest_v2(
        run_id="run_p7",
        case_id="P7",
        artifacts_dir=str(tmp_path),
        artifact_filenames=fake_files,
    )

    # Tamper with file
    (tmp_path / "Job.odb").write_text("tampered content", encoding="utf-8")

    acc = evaluate_result_acceptance(
        result_status="completed",
        physics_domain="connector",
        connector_kinematics=ConnectorKinematicsVerification(passed=True, status="pass"),
        values={"connector_relative_motion": 0.1, "connector_force": 10.0},
        criteria=(),
        odb_fields=("CU", "CTF"),
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        expected_run_id="run_p7",
        require_evidence=True,
    )
    assert acc.passed is False
    assert acc.gates["evidence_sufficiency"] == "FAIL"
    assert acc.result_validity == "RESULT_INVALID"


def test_connector_negative_probe_8_semantic_type_tampering():
    """Negative Probe 8: Semantic connector tampering (HINGE -> TRANSLATOR) fails closed."""
    actions = [
        builders.reference_point("M", "RP1", (0, 0, 0)),
        builders.reference_point("M", "RP2", (0, 0, 10)),
        builders.connector_section("M", "TransSec", translational_type="TRANSLATOR"),
        builders.wire_connector("M", "C8", "TransSec", point1_name="RP1", point2_name="RP2", orientation=None),
    ]
    res = preflight_plan(actions)
    assert res.passed is False
    assert any("connector_orientation_required" in b["name"] for b in res.blockers)


def test_connector_negative_probe_9_physical_criteria_violation():
    """Negative Probe 9: Physical criteria violation triggers acceptance FAIL."""
    criteria = (
        {
            "name": "strict_drift_gate",
            "value_key": "revolute_joint_drift",
            "operator": "<=",
            "limit": 1e-15,
            "unit": "mm",
        },
    )
    acc = evaluate_result_acceptance(
        result_status="completed",
        physics_domain="connector",
        connector_kinematics=ConnectorKinematicsVerification(passed=True, status="pass"),
        values={"revolute_joint_drift": 9.78e-6, "connector_relative_motion": 0.12, "connector_force": 10.0},
        criteria=criteria,
        odb_fields=("CU", "CTF"),
    )
    assert acc.passed is False
    assert acc.status == "FAIL"
    assert "criterion:strict_drift_gate" in acc.failures
