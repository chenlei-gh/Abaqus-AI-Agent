"""Tests for the Flexible Multi-Body Dynamics 6 (FMBD-6) Golden E2E Case."""

import json
from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.golden_evidence import normalize_golden_evidence, validate_golden_evidence_dict
from tools.fmbd6_flexible_to_flexible_golden_e2e import (
    build_fmbd6_golden_script,
    _extract_report,
    parse_evidence_status_from_output,
)


def test_fmbd6_golden_script_uses_mechanism_graph_compiler():
    script = build_fmbd6_golden_script()
    # Verify that FMBD-6 strictly relies on MechanismGraph compiler
    assert "MechanismGraph(" in script
    assert "m.compile_to_actions(" in script
    assert "m.add_body(" in script
    assert "m.add_flexible_interface(" in script
    assert "m.add_joint(" in script
    assert "m.add_load(" in script

    # Verify existing execution and acceptance pipelines are invoked
    for marker in (
        "AnalysisRunner(executor).run(",
        "evaluate_result_acceptance(",
        "extract_history(",
    ):
        assert marker in script, "Missing expected marker in script: %s" % marker

    # Verify direct flexible-to-flexible joint connectivity
    assert "interface_a_name='Coupling_Arm1_Tip'" in script
    assert "interface_b_name='Coupling_Arm2_Root'" in script


def test_fmbd6_golden_script_has_no_direct_process_solver_bypass():
    script = build_fmbd6_golden_script()
    assert "subprocess" not in script
    assert "run_input(" not in script
    assert "run_nogui(" not in script


def test_fmbd6_golden_report_parser():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    stdout = (
        "preamble noise\n"
        "AIAgent_FMBD6_GOLDEN_RESULT_BEGIN\n"
        + json.dumps(report)
        + "\nAIAgent_FMBD6_GOLDEN_RESULT_END\n"
        "trailing noise\n"
    )
    assert _extract_report(stdout) == report
    assert parse_evidence_status_from_output(stdout) == "PASS"


def test_fmbd6_golden_report_parser_with_rpy_prefixes():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    raw_json = json.dumps(report, indent=2)
    rpy_lines = ["#: " + line for line in raw_json.splitlines()]
    stdout = (
        "AIAgent_FMBD6_GOLDEN_RESULT_BEGIN\n"
        + "\n".join(rpy_lines)
        + "\nAIAgent_FMBD6_GOLDEN_RESULT_END\n"
    )
    assert _extract_report(stdout) == report
    assert parse_evidence_status_from_output(stdout) == "PASS"


def test_fmbd6_acceptance_dual_gates_nominal_pass_strict_fail():
    criteria_nominal = (
        {"name": "pivot_drift", "value_key": "pivot_drift", "operator": "<=", "limit": 1e-3, "unit": "mm"},
        {"name": "elbow_flex_drift", "value_key": "elbow_flex_drift", "operator": "<=", "limit": 1e-3, "unit": "mm"},
        {"name": "arm1_mises_stress", "value_key": "arm1_mises_stress", "operator": ">=", "limit": 0.01, "unit": "MPa"},
        {"name": "arm2_mises_stress", "value_key": "arm2_mises_stress", "operator": ">=", "limit": 0.01, "unit": "MPa"},
        {"name": "overall_mises_upper", "value_key": "overall_mises_upper", "operator": "<=", "limit": 200.0, "unit": "MPa"},
        {"name": "strain_energy_ratio", "value_key": "strain_energy_ratio", "operator": ">=", "limit": 0.80, "unit": ""},
        {"name": "energy_dissipation", "value_key": "energy_dissipation", "operator": "<=", "limit": 0.50, "unit": ""},
    )
    criteria_strict = (
        {"name": "elbow_drift_impossible", "value_key": "elbow_drift_impossible", "operator": "<=", "limit": 1e-15, "unit": "mm"},
    )

    actual_values = {
        "pivot_drift": 2.15e-8,
        "elbow_flex_drift": 4.82e-8,
        "arm1_mises_stress": 12.45,
        "arm2_mises_stress": 8.76,
        "overall_mises_upper": 12.45,
        "strain_energy_ratio": 0.984,
        "energy_dissipation": 0.268,
        "elbow_drift_impossible": 4.82e-8,
    }

    acc_nom = evaluate_result_acceptance(result_status="completed", values=actual_values, criteria=criteria_nominal)
    assert acc_nom.passed is True
    assert len(acc_nom.failures) == 0

    acc_strict = evaluate_result_acceptance(result_status="completed", values=actual_values, criteria=criteria_strict)
    assert acc_strict.passed is False
    assert len(acc_strict.failures) == 1
    assert "elbow_drift_impossible" in acc_strict.failures[0]


def test_fmbd6_golden_evidence_normalization():
    evidence_dict = {
        "status": "pass",
        "case_id": "fmbd6_flexible_to_flexible",
        "title": "FMBD-6 Direct Flexible-to-Flexible Mechanism Dynamics E2E",
        "release": "Abaqus 2025",
        "solver": "standard",
        "job_name": "FMBD6GoldenJob",
        "odb_path": "FMBD6GoldenJob.odb",
        "simulation_results": {
            "max_pivot_drift_mm": 2.15e-8,
            "max_elbow_drift_mm": 4.82e-8,
            "max_joint_drift_mm": 4.82e-8,
            "max_mises_arm1_mpa": 12.45,
            "max_mises_arm2_mpa": 8.76,
            "overall_max_mises_mpa": 12.45,
            "peak_external_work_mj": 450.2,
            "peak_kinetic_energy_mj": 412.5,
            "peak_internal_energy_mj": 38.4,
            "peak_strain_energy_mj": 37.8,
            "min_total_energy_mj": -120.5,
            "max_numerical_dissipation_mj": 120.5,
            "max_artificial_energy_allae_mj": 0.05,
            "max_viscous_dissipation_allvd_mj": 0.0,
            "artificial_to_strain_energy_ratio": 0.0013,
            "elastic_strain_ratio_in_ie": 0.984,
            "algorithmic_damping_dissipation_ratio": 0.268,
            "num_frames": 51,
            "total_time_s": 0.5,
        },
        "workflow": {
            "solver_completed": True,
            "job_status": "COMPLETED",
            "odb_path": "FMBD6GoldenJob.odb",
            "compiler_used": True,
        },
        "acceptance": {
            "passed": True,
            "failures": [],
            "criteria_count": 7,
        },
        "verification": {
            "pivot_drift_passed": True,
            "elbow_drift_passed": True,
            "normal_acceptance_passed": True,
            "strict_acceptance_passed": False,
        },
        "provenance": {
            "action_count": 25,
            "intent_id": "fmbd6-flexible-to-flexible-golden-e2e",
            "compiler": "MechanismGraph",
            "release": "Abaqus 2025",
            "mechanism_type": "direct_flexible_to_flexible",
        },
    }

    envelope = normalize_golden_evidence(evidence_dict)
    assert envelope.passed is True
    assert envelope.case_id == "fmbd6_flexible_to_flexible"
    assert envelope.release == "Abaqus 2025"
    assert envelope.solver == "standard"
    assert envelope.job == "FMBD6GoldenJob"

    envelope_dict = envelope.to_dict()
    errors = validate_golden_evidence_dict(envelope_dict)
    assert len(errors) == 0, f"Envelope validation errors: {errors}"
