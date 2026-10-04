"""Regression & Negative Probes for Flexible Multibody Dynamics (FMBD) L4.

Validates:
1. Certified Evidence Manifest V2 integrity in `machine_validation/fmbd_l4_manifest.json`.
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
    IntentConnectorSpec,
)
from abaqus_ai_agent.contracts.fmbd import (
    RigidBodySpec,
    FlexibleInterfaceSpec,
    IntentFMBDSpec,
    FMBDKinematicsVerification,
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
MANIFEST_PATH = ROOT / "machine_validation" / "fmbd_l4_manifest.json"


def test_fmbd_l4_evidence_manifest_integrity():
    """Verify that the certified Abaqus 2025 FMBD L4 manifest exists and is QUALIFIED."""
    assert MANIFEST_PATH.exists(), f"FMBD L4 manifest missing at {MANIFEST_PATH}"
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert data["case_id"] == "MP_FMBD_L4_Golden"
    assert data["status"] == "QUALIFIED"
    assert data["evidence_tier"] == "REAL_ABAQUS"
    assert data["solver"] == "Abaqus 2025"
    assert data["compiler_chain_verified"] is True

    wf = data["workflow"]
    assert wf["intent_fmbd_contract"] == "PASS"
    assert wf["canonical_compiler"] == "PASS"
    assert wf["preflight_checks"] == "PASS"
    assert wf["live_solver_execution"] == "PASS"
    assert wf["odb_extraction"] == "PASS"
    assert wf["fmbd_dynamics_gate"] == "PASS"
    assert wf["evidence_v2_manifest"] == "PASS"
    assert wf["acceptance"] == "PASS"

    probes = data["negative_probes"]
    for i in range(1, 10):
        matching = [k for k in probes if f"probe_{i}_" in k]
        assert len(matching) == 1, f"Missing negative probe {i}"
        assert probes[matching[0]] == "PASS", f"Negative probe {matching[0]} failed verification"

    # Physics metrics check from real Abaqus solver
    metrics = data["metrics"]
    assert metrics["max_joint_drift_mm"] <= 1e-3
    assert metrics["max_joint_drift_mm"] > 0.0
    assert metrics["overall_max_mises_mpa"] >= 0.01
    assert metrics["strain_energy_ratio"] >= 0.01
    assert metrics["energy_dissipation_ratio"] <= 0.05
    assert metrics["frame_count"] >= 50

    # Real solver artifacts check (6 required roles)
    arts = data["artifacts"]
    for ext in ("inp", "odb", "sta", "msg", "dat", "log"):
        key = f"Job_FMBD_L4.{ext}"
        assert key in arts, f"Missing artifact {key}"
        assert arts[key]["exists"] is True
        assert len(arts[key]["sha256"]) == 64
        assert arts[key]["size_bytes"] > 0

    acc = data["acceptance"]
    assert acc["passed"] is True
    assert acc["status"] == "PASS"
    assert acc["result_validity"] == "VALID"
    assert acc["gates"]["fmbd_dynamics"] == "PASS"
    assert acc["gates"]["evidence_sufficiency"] == "PASS"
    assert acc["gates"]["required_results"] == "PASS"


def test_fmbd_l4_intent_compilation_and_preflight():
    """Verify clean full-chain compilation from IntentFMBDSpec through Compiler to Preflight."""
    ep_a = ConnectorEndpointSpec(name="RP_GROUND", point_coords=(0.0, 0.0, 10.0), reference_point_name="RP_GROUND")
    ep_b = ConnectorEndpointSpec(name="RP_PIVOT_CRANK", point_coords=(0.0, 0.0, 10.0), reference_point_name="RP_PIVOT_CRANK")
    orient = ConnectorOrientationSpec(name="Csys_HingeZ", point1=(0.0, 0.0, 1.0), point2=(1.0, 0.0, 0.0))

    conn_pivot = IntentConnectorSpec(
        name="Conn_Pivot",
        connector_type="HINGE",
        endpoint_a=ep_a,
        endpoint_b=ep_b,
        orientation=orient,
        section_name="Sec_Hinge",
    )

    rigid_crank = RigidBodySpec(
        name="RigidCrank",
        ref_point_name="RP_PIVOT_CRANK",
        body_region="a.sets['CrankCells']",
        tie_region="a.sets['RP_ELBOW_CRANK']",
        point_coords=(0.0, 0.0, 10.0),
    )

    flex_coupling = FlexibleInterfaceSpec(
        name="Coupling_Elbow_FlexLink",
        control_point_name="RP_ELBOW_FLEX",
        surface_region="a.instances['FlexLink-1'].surfaces['TopFace']",
        coupling_type="KINEMATIC",
        point_coords=(38.8, -144.9, 10.0),
    )

    fmbd_spec = IntentFMBDSpec(
        name="FMBD_Test",
        rigid_bodies=(rigid_crank,),
        flexible_interfaces=(flex_coupling,),
        connectors=(conn_pivot,),
        gravity=(0.0, -9810.0, 0.0),
        time_period=1.0,
        initial_inc=0.005,
        max_inc=0.01,
        nlgeom=True,
    )

    intent = EngineeringIntent(
        id="intent-test-fmbd",
        kind="rigid_flexible_coupled_dynamics",
        description="FMBD compilation test",
        connectors=(conn_pivot,),
        fmbd=fmbd_spec,
    )

    plan = compile_intent_to_actions(
        model_name="Model_Test_FMBD",
        part_name="Crank",
        job_name="Job_Test_FMBD",
        geometry=IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0),
        material=MaterialDefinition(name="Steel", elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3)),
        connectors=intent.connectors,
        fmbd=intent.fmbd,
    )

    act_types = [a.action_type for a in plan.actions]
    assert "rigid_body" in act_types
    assert "coupling_constraint" in act_types
    assert "connector_section" in act_types
    assert "wire_connector" in act_types
    assert "gravity" in act_types

    pf_res = preflight_plan(plan.actions)
    assert pf_res.passed is True
    assert len(pf_res.blockers) == 0


def test_fmbd_negative_probe_1_missing_control_point():
    """Negative Probe 1: Missing coupling control point must trigger preflight blocker."""
    act = builders.coupling_constraint("M", "BadC", control_point_name="", surface_expression="a.surfaces['Top']")
    res = preflight_action(act)
    assert res.passed is False
    assert any("control_point" in b["name"] for b in res.blockers)


def test_fmbd_negative_probe_2_missing_surface():
    """Negative Probe 2: Missing coupling surface must trigger preflight blocker."""
    act = builders.coupling_constraint("M", "BadC", control_point_name="RP1", surface_expression="")
    res = preflight_action(act)
    assert res.passed is False
    assert any("surface" in b["name"] for b in res.blockers)


def test_fmbd_negative_probe_3_identical_coupling_endpoints():
    """Negative Probe 3: Identical control point and surface in coupling must trigger blocker."""
    act = builders.coupling_constraint("M", "BadC", control_point_name="Node1", surface_expression="Node1")
    res = preflight_action(act)
    assert res.passed is False
    assert any("distinct" in b["name"] for b in res.blockers)


def test_fmbd_negative_probe_4_undefined_section():
    """Negative Probe 4: Connector referencing undefined section must trigger plan blocker."""
    bad_plan = [
        builders.reference_point("M", "RP1", (0, 0, 0)),
        builders.reference_point("M", "RP2", (0, 0, 10)),
        builders.wire_connector("M", "Conn_Bad", "NonExistentSection", "RP1", "RP2"),
    ]
    res = preflight_plan(bad_plan)
    assert res.passed is False
    assert any("connector_section_defined" in b["name"] for b in res.blockers)


def test_fmbd_negative_probe_5_missing_orientation():
    """Negative Probe 5: HINGE connector without local orientation must trigger plan blocker."""
    bad_plan = [
        builders.reference_point("M", "RP1", (0, 0, 0)),
        builders.reference_point("M", "RP2", (0, 0, 10)),
        builders.connector_section("M", "Sec_Hinge", assembled_type="HINGE"),
        builders.wire_connector("M", "Conn_Bad", "Sec_Hinge", "RP1", "RP2", orientation=None),
    ]
    res = preflight_plan(bad_plan)
    assert res.passed is False
    assert any("connector_orientation_required" in b["name"] for b in res.blockers)


def test_fmbd_negative_probe_6_missing_mandatory_gate():
    """Negative Probe 6: Missing mandatory gate fmbd_dynamics must mark acceptance BLOCKED."""
    criteria = (
        {"name": "joint_drift", "value_key": "joint_drift", "operator": "<=", "limit": 1e-3, "unit": "mm"},
    )
    acc = evaluate_result_acceptance(
        result_status="completed",
        values={"joint_drift": 1e-5, "max_mises_stress": 50.0, "strain_energy_ratio": 0.5, "energy_dissipation_ratio": 0.01},
        criteria=criteria,
        physics_domain="fmbd",
        fmbd_dynamics=None, # Missing mandatory gate
    )
    assert acc.passed is False
    assert acc.gates["fmbd_dynamics"] == "BLOCKED"
    assert "missing_mandatory_gate:fmbd_dynamics" in acc.failures


def test_fmbd_negative_probe_7_evidence_tampering():
    """Negative Probe 7: Tampered manifest artifact hash must trigger acceptance FAIL."""
    manifest_data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tampered_data = dict(manifest_data)
    tampered_arts = dict(tampered_data["artifacts"])
    tampered_arts["Job_FMBD_L4.odb"] = dict(tampered_arts["Job_FMBD_L4.odb"])
    tampered_arts["Job_FMBD_L4.odb"]["sha256"] = "bad" * 21 + "a"
    tampered_data["artifacts"] = tampered_arts

    verification = FMBDKinematicsVerification(
        status="pass",
        joint_drift_max_mm=3.13e-10,
        max_mises_stress_mpa=0.0435,
        strain_energy_ratio=0.999,
        energy_dissipation_ratio=0.0056,
        frame_count=336,
    )
    acc = evaluate_result_acceptance(
        result_status="completed",
        values={
            "joint_drift": 3.13e-10,
            "max_mises_stress": 0.0435,
            "strain_energy_ratio": 0.999,
            "energy_dissipation_ratio": 0.0056,
        },
        criteria=({"name": "joint_drift", "value_key": "joint_drift", "operator": "<=", "limit": 1e-3, "unit": "mm"},),
        physics_domain="fmbd",
        fmbd_dynamics=verification,
        evidence_manifest=tampered_data,
        require_evidence=True,
    )
    assert acc.passed is False
    assert acc.gates["evidence_sufficiency"] == "FAIL"
    assert acc.result_validity == "RESULT_INVALID"


def test_fmbd_negative_probe_8_rigid_body_self_tie():
    """Negative Probe 8: Rigid body where ref point is identical to tie region must be blocked."""
    act = builders.rigid_body("M", "BadRB", ref_point_expression="a.sets['RP1']", tie_region="a.sets['RP1']")
    res = preflight_action(act)
    assert res.passed is False
    assert any("distinct" in b["name"] for b in res.blockers)


def test_fmbd_negative_probe_9_physical_drift_violation():
    """Negative Probe 9: Joint drift exceeding strict threshold must fail engineering criteria."""
    verification = FMBDKinematicsVerification(
        status="pass",
        joint_drift_max_mm=0.05, # Exceeds 1e-3 mm
        max_mises_stress_mpa=0.0435,
        strain_energy_ratio=0.999,
        energy_dissipation_ratio=0.0056,
        frame_count=336,
    )
    criteria_strict = (
        {"name": "joint_drift_limit", "value_key": "joint_drift", "operator": "<=", "limit": 1e-3, "unit": "mm"},
    )
    acc = evaluate_result_acceptance(
        result_status="completed",
        values={
            "joint_drift": 0.05,
            "max_mises_stress": 0.0435,
            "strain_energy_ratio": 0.999,
            "energy_dissipation_ratio": 0.0056,
        },
        criteria=criteria_strict,
        physics_domain="fmbd",
        fmbd_dynamics=verification,
    )
    assert acc.passed is False
    assert acc.gates["criteria"] == "FAIL"
