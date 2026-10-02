"""Tests for the Multi-Body Dynamics 2 (MBD-2) Double Pendulum Golden E2E Case."""

import json
from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.engineering_checks import (
    check_revolute_joint_kinematics,
    check_double_pendulum_kinematics,
    check_mechanical_energy_conservation,
)
from abaqus_ai_agent.engineering_evidence import (
    revolute_joint_kinematics_from_evidence,
    double_pendulum_kinematics_from_evidence,
    mechanical_energy_conservation_from_evidence,
)
from abaqus_ai_agent.workflow.mbd import build_double_pendulum_plan
from tools.mbd2_revolute_golden_e2e import (
    build_mbd2_golden_script,
    _extract_report,
    parse_evidence_status_from_output,
)


def test_mbd2_golden_script_uses_existing_pipeline():
    script = build_mbd2_golden_script()
    for marker in (
        "reference_point(",
        "rigid_body(",
        "connector_section(",
        "wire_connector(",
        "displacement_bc(",
        "implicit_dynamic_step(",
        "gravity(",
        "material_density(",
        "field_output(",
        "history_output(",
        "AnalysisRunner(executor).run(",
        "revolute_joint_kinematics_from_evidence(",
        "double_pendulum_kinematics_from_evidence(",
        "mechanical_energy_conservation_from_evidence(",
        "evaluate_result_acceptance(",
        "seed_part(",
        "generate_mesh(",
    ):
        assert marker in script, "Missing expected marker in script: %s" % marker


def test_mbd2_golden_script_has_no_direct_process_solver_bypass():
    script = build_mbd2_golden_script()
    assert "subprocess" not in script
    assert "run_input(" not in script
    assert "run_nogui(" not in script


def test_build_double_pendulum_plan_integration():
    plan = build_double_pendulum_plan(
        model_name="TestMBD2Model",
        arm1_part_name="Arm1",
        arm2_part_name="Arm2",
        material={"name": "Steel", "youngs_modulus": 210000.0, "poisson": 0.3, "density": 7.85e-9},
        pivot_coords=(0.0, 0.0, 10.0),
        elbow_coords=(52.09, -295.44, 10.0),
        arm1_body_expression="mdb.models['TestMBD2Model'].rootAssembly.sets['Arm1Cells']",
        arm2_body_expression="mdb.models['TestMBD2Model'].rootAssembly.sets['Arm2Cells']",
    )
    assert len(plan.actions) > 0
    types = [a.action_type for a in plan.actions]
    assert "reference_point" in types
    assert "rigid_body" in types
    assert "connector_section" in types
    assert "wire_connector" in types
    assert "displacement_bc" in types
    assert "implicit_dynamic_step" in types
    assert "gravity" in types


def test_mbd2_golden_report_parser():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    stdout = (
        "preamble noise\n"
        "AIAgent_MBD2_GOLDEN_RESULT_BEGIN\n"
        + json.dumps(report)
        + "\nAIAgent_MBD2_GOLDEN_RESULT_END\n"
        "trailing noise\n"
    )
    assert _extract_report(stdout) == report


def test_mbd2_golden_report_parser_with_rpy_prefixes():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    raw_json = json.dumps(report, indent=2)
    rpy_lines = ["#: " + line for line in raw_json.splitlines()]
    stdout = (
        "AIAgent_MBD2_GOLDEN_RESULT_BEGIN\n"
        + "\n".join(rpy_lines)
        + "\nAIAgent_MBD2_GOLDEN_RESULT_END\n"
    )
    assert _extract_report(stdout) == report


def test_mbd2_golden_acceptance_gate_pass_and_fail():
    result_values = {
        "revolute_joint_drift": 1e-6,
        "revolute_relative_articulation": 0.08,
        "double_pendulum_fundamental_period": 1.285,
        "energy_loss_ratio": 0.01,
        "frame_count": 60,
    }
    normal_criteria = (
        {
            "name": "revolute_joint_drift_bound",
            "value_key": "revolute_joint_drift",
            "operator": "<=",
            "limit": 1e-3,
            "unit": "mm",
        },
        {
            "name": "revolute_relative_articulation_bound",
            "value_key": "revolute_relative_articulation",
            "operator": ">=",
            "limit": 0.01,
            "unit": "rad",
        },
        {
            "name": "double_pendulum_fundamental_period_check",
            "value_key": "double_pendulum_fundamental_period",
            "operator": "<=",
            "limit": 1.35,
            "unit": "s",
        },
        {
            "name": "energy_loss_bound",
            "value_key": "energy_loss_ratio",
            "operator": "<=",
            "limit": 0.03,
            "unit": "",
        },
    )
    res_normal = evaluate_result_acceptance(result_status="completed", criteria=normal_criteria, values=result_values)
    assert res_normal.passed, "Normal criteria should pass for valid double pendulum kinematics"

    strict_criteria = (
        {
            "name": "strict_drift_gate",
            "value_key": "revolute_joint_drift",
            "operator": "<=",
            "limit": 1e-15,
            "unit": "mm",
        },
    )
    res_strict = evaluate_result_acceptance(result_status="completed", criteria=strict_criteria, values=result_values)
    assert not res_strict.passed, "Artificial strict gate should fail to ensure verification rigor"


def test_revolute_joint_kinematics_checks():
    report = revolute_joint_kinematics_from_evidence(
        joint_drift_max=5e-7,
        joint_drift_tolerance=1e-3,
        relative_rotation_max=0.05,
        min_relative_rotation=0.01,
    )
    assert report.passed
    assert len(report.checks) == 2

    # Test failure when joint drift exceeds tolerance
    bad_drift_report = revolute_joint_kinematics_from_evidence(
        joint_drift_max=0.05,
        joint_drift_tolerance=1e-3,
    )
    assert not bad_drift_report.passed

    # Test failure when joint does not articulate (locked joint)
    locked_report = revolute_joint_kinematics_from_evidence(
        joint_drift_max=1e-6,
        relative_rotation_max=0.0001,
        min_relative_rotation=0.01,
    )
    assert not locked_report.passed


def test_double_pendulum_kinematics_checks():
    report = double_pendulum_kinematics_from_evidence(
        actual_period=1.285,
        expected_period=1.2843,
        period_tolerance=0.05,
    )
    assert report.passed

    bad_report = double_pendulum_kinematics_from_evidence(
        actual_period=1.50,
        expected_period=1.2843,
        period_tolerance=0.05,
    )
    assert not bad_report.passed
