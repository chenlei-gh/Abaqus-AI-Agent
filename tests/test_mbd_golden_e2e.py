"""Tests for the Multi-Body Dynamics (MBD) Golden E2E Case."""

import json
from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.engineering_checks import (
    check_pendulum_kinematics,
    check_mechanical_energy_conservation,
)
from abaqus_ai_agent.engineering_evidence import (
    pendulum_kinematics_from_evidence,
    mechanical_energy_conservation_from_evidence,
)
from abaqus_ai_agent.workflow.mbd import build_mbd_plan
from tools.mbd_golden_e2e import (
    build_mbd_golden_script,
    _extract_report,
    parse_evidence_status_from_output,
)


def test_mbd_golden_script_uses_existing_pipeline():
    script = build_mbd_golden_script()
    for marker in (
        "reference_point(",
        "rigid_body(",
        "displacement_bc(",
        "implicit_dynamic_step(",
        "gravity(",
        "material_density(",
        "field_output(",
        "history_output(",
        "AnalysisRunner(executor).run(",
        "pendulum_kinematics_from_evidence(",
        "mechanical_energy_conservation_from_evidence(",
        "evaluate_result_acceptance(",
        "seed_part(",
        "generate_mesh(",
    ):
        assert marker in script, "Missing expected marker in script: %s" % marker


def test_mbd_golden_script_has_no_direct_process_solver_bypass():
    script = build_mbd_golden_script()
    assert "subprocess" not in script
    assert "run_input(" not in script
    assert "run_nogui(" not in script


def test_build_mbd_plan_integration():
    plan = build_mbd_plan(
        model_name="TestMBDModel",
        part_name="TestArm",
        material={"name": "Steel", "youngs_modulus": 210000.0, "poisson": 0.3, "density": 7.85e-9},
        pivot_coords=(0.0, 0.0, 10.0),
        body_set_expression="mdb.models['TestMBDModel'].rootAssembly.sets['AllArmCells']",
    )
    assert len(plan.actions) > 0
    types = [a.action_type for a in plan.actions]
    assert "reference_point" in types
    assert "rigid_body" in types
    assert "displacement_bc" in types
    assert "implicit_dynamic_step" in types
    assert "gravity" in types


def test_mbd_golden_report_parser():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    stdout = (
        "preamble noise\n"
        "AIAgent_MBD_GOLDEN_RESULT_BEGIN\n"
        + json.dumps(report)
        + "\nAIAgent_MBD_GOLDEN_RESULT_END\n"
        "trailing noise\n"
    )
    assert _extract_report(stdout) == report


def test_mbd_golden_report_parser_with_rpy_prefixes():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    raw_json = json.dumps(report, indent=2)
    rpy_lines = ["#: " + line for line in raw_json.splitlines()]
    stdout = (
        "AIAgent_MBD_GOLDEN_RESULT_BEGIN\n"
        + "\n".join(rpy_lines)
        + "\nAIAgent_MBD_GOLDEN_RESULT_END\n"
    )
    assert _extract_report(stdout) == report


def test_mbd_golden_acceptance_gate_pass_and_fail():
    result_values = {
        "oscillation_period": 1.2705,
        "max_angular_velocity": 0.864,
        "energy_loss_ratio": 0.005,
        "frame_count": 55,
    }
    normal_criteria = (
        {
            "name": "period_bound",
            "value_key": "oscillation_period",
            "operator": "<=",
            "limit": 1.30,
            "unit": "s",
        },
        {
            "name": "max_omega_bound",
            "value_key": "max_angular_velocity",
            "operator": "<=",
            "limit": 0.90,
            "unit": "rad/s",
        },
        {
            "name": "energy_loss_bound",
            "value_key": "energy_loss_ratio",
            "operator": "<=",
            "limit": 0.03,
            "unit": "",
        },
    )
    pass_res = evaluate_result_acceptance(result_status="completed", criteria=normal_criteria, values=result_values)
    assert pass_res.passed is True

    strict_criteria = (
        {
            "name": "strict_period_gate",
            "value_key": "oscillation_period",
            "operator": "<=",
            "limit": 0.0001,
            "unit": "s",
        },
    )
    fail_res = evaluate_result_acceptance(result_status="completed", criteria=strict_criteria, values=result_values)
    assert fail_res.passed is False


def test_pendulum_kinematics_and_energy_conservation_checks():
    kin_rep = pendulum_kinematics_from_evidence(
        actual_period=1.271,
        expected_period=1.2713,
        actual_max_omega=0.863,
        expected_max_omega=0.8631,
        period_tolerance=0.03,
        omega_tolerance=0.05,
    )
    assert kin_rep.passed is True

    # Out of tolerance should fail
    kin_rep_bad = pendulum_kinematics_from_evidence(
        actual_period=1.500,
        expected_period=1.2713,
        actual_max_omega=0.863,
        expected_max_omega=0.8631,
        period_tolerance=0.03,
        omega_tolerance=0.05,
    )
    assert kin_rep_bad.passed is False

    nrg_rep = mechanical_energy_conservation_from_evidence(
        energy_loss=0.8,
        initial_energy=84.26,
        tolerance=0.03,
        unit="mJ",
    )
    assert nrg_rep.passed is True

    nrg_rep_bad = mechanical_energy_conservation_from_evidence(
        energy_loss=5.0,
        initial_energy=84.26,
        tolerance=0.03,
        unit="mJ",
    )
    assert nrg_rep_bad.passed is False


def test_parse_evidence_status_from_output():
    out = "some output\nAIAgent_MBD_E2E_EVIDENCE_STATUS: pass\nmore output"
    assert parse_evidence_status_from_output(out) == "pass"
    out_fail = "some output\nAIAgent_MBD_E2E_EVIDENCE_STATUS: fail\nmore output"
    assert parse_evidence_status_from_output(out_fail) == "fail"
    out_rpy = "#: AIAgent_MBD_E2E_EVIDENCE_STATUS: pass"
    assert parse_evidence_status_from_output(out_rpy) == "pass"
