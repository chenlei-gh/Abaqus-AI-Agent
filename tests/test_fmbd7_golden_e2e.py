"""Tests for the Flexible Multi-Body Dynamics 7 (FMBD-7) Golden E2E Case."""

import json
from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.golden_evidence import normalize_golden_evidence, validate_golden_evidence_dict
from tools.fmbd7_dual_flexible_four_bar_golden_e2e import (
    build_fmbd7_golden_script,
    _extract_report,
    parse_evidence_status_from_output,
    generate_mock_evidence,
)


def test_fmbd7_golden_script_uses_mechanism_graph_compiler():
    script = build_fmbd7_golden_script()
    # Verify that FMBD-7 strictly relies on MechanismGraph compiler
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

    # Verify closed-loop multi-flexible connectivity
    assert "interface_a_name='IFace_Coupler_C'" in script
    assert "interface_b_name='IFace_Rocker_C'" in script
    assert "interface_a_name='IFace_Rocker_D'" in script


def test_fmbd7_golden_script_has_no_direct_process_solver_bypass():
    script = build_fmbd7_golden_script()
    assert "subprocess" not in script
    assert "run_input(" not in script
    assert "run_nogui(" not in script


def test_fmbd7_golden_report_parser():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    stdout = (
        "preamble noise\n"
        "AIAgent_FMBD7_GOLDEN_RESULT_BEGIN\n"
        + json.dumps(report)
        + "\nAIAgent_FMBD7_GOLDEN_RESULT_END\n"
        "trailing noise\n"
    )
    assert _extract_report(stdout) == report
    assert parse_evidence_status_from_output(stdout) == "PASS"


def test_fmbd7_golden_report_parser_with_rpy_prefixes():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    raw_json = json.dumps(report, indent=2)
    rpy_lines = ["#: " + line for line in raw_json.splitlines()]
    stdout = (
        "AIAgent_FMBD7_GOLDEN_RESULT_BEGIN\n"
        + "\n".join(rpy_lines)
        + "\nAIAgent_FMBD7_GOLDEN_RESULT_END\n"
    )
    assert _extract_report(stdout) == report
    assert parse_evidence_status_from_output(stdout) == "PASS"


def test_fmbd7_acceptance_dual_gates_nominal_pass_strict_fail():
    criteria_nominal = (
        {"name": "pivot_drift_max", "value_key": "max_pivot_drift", "operator": "<=", "limit": 1e-3, "unit": "mm"},
        {"name": "elbow_drift_max", "value_key": "max_elbow_drift", "operator": "<=", "limit": 1e-3, "unit": "mm"},
        {"name": "knee_direct_ff_drift_max", "value_key": "max_knee_drift", "operator": "<=", "limit": 1e-3, "unit": "mm"},
        {"name": "anchor_return_drift_max", "value_key": "max_anchor_drift", "operator": "<=", "limit": 1e-3, "unit": "mm"},
        {"name": "kinematic_closure_error_max", "value_key": "max_closure_error", "operator": "<=", "limit": 1e-3, "unit": "mm"},
        {"name": "coupler_mises_lower", "value_key": "max_coupler_mises", "operator": ">=", "limit": 0.001, "unit": "MPa"},
        {"name": "coupler_mises_upper", "value_key": "max_coupler_mises", "operator": "<=", "limit": 250.0, "unit": "MPa"},
        {"name": "rocker_mises_lower", "value_key": "max_rocker_mises", "operator": ">=", "limit": 0.001, "unit": "MPa"},
        {"name": "rocker_mises_upper", "value_key": "max_rocker_mises", "operator": "<=", "limit": 250.0, "unit": "MPa"},
        {"name": "elastic_strain_energy_ratio", "value_key": "se_ie_ratio", "operator": ">=", "limit": 0.80, "unit": ""},
        {"name": "algorithmic_damping_dissipation_bound", "value_key": "damping_dissipation_ratio", "operator": "<=", "limit": 0.50, "unit": ""},
    )
    criteria_strict = (
        {"name": "impossible_knee_drift", "value_key": "max_knee_drift", "operator": "<=", "limit": 1e-15, "unit": "mm"},
    )

    actual_values = {
        "max_pivot_drift": 1.25e-8,
        "max_elbow_drift": 2.45e-8,
        "max_knee_drift": 3.12e-8,
        "max_anchor_drift": 1.88e-8,
        "max_closure_error": 3.12e-8,
        "max_coupler_mises": 14.85,
        "max_rocker_mises": 9.62,
        "se_ie_ratio": 0.988,
        "damping_dissipation_ratio": 0.279,
    }

    acc_nom = evaluate_result_acceptance(result_status="completed", values=actual_values, criteria=criteria_nominal)
    assert acc_nom.passed is True
    assert len(acc_nom.failures) == 0

    acc_strict = evaluate_result_acceptance(result_status="completed", values=actual_values, criteria=criteria_strict)
    assert acc_strict.passed is False
    assert len(acc_strict.failures) == 1
    assert "impossible_knee_drift" in acc_strict.failures[0]


def test_fmbd7_golden_evidence_normalization_and_validation():
    mock_data = generate_mock_evidence()
    envelope = normalize_golden_evidence(mock_data)
    envelope_dict = envelope.to_dict()

    errors = validate_golden_evidence_dict(envelope_dict)
    assert len(errors) == 0, f"Evidence validation errors: {errors}"
    assert envelope.case_id == "fmbd7_dual_flexible_four_bar"
    assert envelope.solver == "standard"
    assert envelope.passed is True
