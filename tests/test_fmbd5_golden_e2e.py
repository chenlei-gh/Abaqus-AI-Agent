"""Tests for the Flexible Multi-Body Dynamics 5 (FMBD-5) Golden E2E Case."""

import json
from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.golden_evidence import normalize_golden_evidence, validate_golden_evidence_dict
from tools.fmbd5_crank_slider_golden_e2e import (
    build_fmbd5_golden_script,
    _extract_report,
    parse_evidence_status_from_output,
)


def test_fmbd5_golden_script_uses_mechanism_graph_compiler():
    script = build_fmbd5_golden_script()
    # Verify that FMBD-5 strictly relies on MechanismGraph compiler
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


def test_fmbd5_golden_script_has_no_direct_process_solver_bypass():
    script = build_fmbd5_golden_script()
    assert "subprocess" not in script
    assert "run_input(" not in script
    assert "run_nogui(" not in script


def test_fmbd5_golden_report_parser():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    stdout = (
        "preamble noise\n"
        "AIAgent_FMBD5_GOLDEN_RESULT_BEGIN\n"
        + json.dumps(report)
        + "\nAIAgent_FMBD5_GOLDEN_RESULT_END\n"
        "trailing noise\n"
    )
    assert _extract_report(stdout) == report
    assert parse_evidence_status_from_output(stdout) == "PASS"


def test_fmbd5_golden_report_parser_with_rpy_prefixes():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    raw_json = json.dumps(report, indent=2)
    rpy_lines = ["#: " + line for line in raw_json.splitlines()]
    stdout = (
        "AIAgent_FMBD5_GOLDEN_RESULT_BEGIN\n"
        + "\n".join(rpy_lines)
        + "\nAIAgent_FMBD5_GOLDEN_RESULT_END\n"
    )
    assert _extract_report(stdout) == report


def test_fmbd5_golden_dual_acceptance_gate():
    nominal_criteria = (
        {'name': 'joint_drift', 'value_key': 'joint_drift', 'operator': '<=', 'limit': 1e-3, 'unit': 'mm'},
        {'name': 'slider_transverse_drift', 'value_key': 'slider_transverse_drift', 'operator': '<=', 'limit': 1e-2, 'unit': 'mm'},
        {'name': 'loop_closure_error', 'value_key': 'loop_closure_error', 'operator': '<=', 'limit': 0.05, 'unit': ''},
        {'name': 'max_mises_stress_lower', 'value_key': 'max_mises_stress_lower', 'operator': '>=', 'limit': 0.01, 'unit': 'MPa'},
        {'name': 'max_mises_stress_upper', 'value_key': 'max_mises_stress_upper', 'operator': '<=', 'limit': 150.0, 'unit': 'MPa'},
        {'name': 'strain_energy_active', 'value_key': 'strain_energy_active', 'operator': '>=', 'limit': 0.005, 'unit': ''},
        {'name': 'energy_dissipation', 'value_key': 'energy_dissipation', 'operator': '<=', 'limit': 0.50, 'unit': ''},
    )
    strict_criteria = (
        {'name': 'joint_drift_impossible', 'value_key': 'joint_drift_impossible', 'operator': '<=', 'limit': 1e-15, 'unit': 'mm'},
    )

    valid_values = {
        'joint_drift': 2.3e-5,
        'slider_transverse_drift': 4.1e-4,
        'loop_closure_error': 0.0035,
        'max_mises_stress_lower': 45.0,
        'max_mises_stress_upper': 45.0,
        'strain_energy_active': 0.042,
        'energy_dissipation': 0.015,
        'joint_drift_impossible': 2.3e-5,
    }

    acc_nom = evaluate_result_acceptance('completed', values=valid_values, criteria=nominal_criteria)
    acc_strict = evaluate_result_acceptance('completed', values=valid_values, criteria=strict_criteria)
    assert acc_nom.passed is True
    assert acc_strict.passed is False

    # Negative test 1: Slider transverse drift violation (guide failure)
    bad_slider = dict(valid_values, slider_transverse_drift=0.08)
    acc_bad_slider = evaluate_result_acceptance('completed', values=bad_slider, criteria=nominal_criteria)
    assert acc_bad_slider.passed is False
    assert any("slider_transverse_drift" in f for f in acc_bad_slider.failures)

    # Negative test 2: Loop closure error violation (link disconnected or over-deformed)
    bad_closure = dict(valid_values, loop_closure_error=0.12)
    acc_bad_closure = evaluate_result_acceptance('completed', values=bad_closure, criteria=nominal_criteria)
    assert acc_bad_closure.passed is False
    assert any("loop_closure_error" in f for f in acc_bad_closure.failures)


def test_fmbd5_golden_evidence_normalization():
    mock_report = {
        "status": "pass",
        "case_id": "fmbd5_crank_slider",
        "release": "Abaqus 2025",
        "solver": "standard",
        "procedure": "implicit_dynamic",
        "job_name": "FMBD5GoldenJob",
        "odb_path": "/path/to/FMBD5GoldenJob.odb",
        "simulation_results": {
            "max_joint_drift_mm": 2.1e-5,
            "max_slider_y_drift_mm": 3.5e-4,
            "max_loop_closure_error": 0.0028,
            "max_mises_stress_mpa": 52.4,
            "peak_external_work_mj": 771.2,
            "peak_kinetic_energy_mj": 708.8,
            "peak_internal_energy_mj": 0.011,
            "peak_strain_energy_mj": 0.011,
            "min_total_energy_mj": -312.1,
            "max_numerical_dissipation_mj": 312.1,
            "elastic_strain_ratio_in_ie": 0.996,
            "algorithmic_damping_dissipation_ratio": 0.405,
            "strain_energy_ratio": 0.038,
            "energy_dissipation_ratio": 0.016,
            "num_frames": 110,
            "total_time_s": 1.0,
        },
        "solver_strategy": {
            "procedure": "implicit_dynamic",
            "application": "MODERATE_DISSIPATION",
            "nohaf": True,
        },
        "workflow": {
            "solver_completed": True,
            "odb_path": "/path/to/FMBD5GoldenJob.odb",
            "compiler_used": True,
        },
        "verification": {
            "joint_drift_passed": True,
            "slider_guide_passed": True,
            "loop_closure_passed": True,
            "stress_sanity_passed": True,
            "internal_energy_composition_passed": True,
            "algorithmic_dissipation_bounded": True,
            "strain_energy_passed": True,
            "energy_conservation_passed": True,
            "normal_acceptance_passed": True,
            "strict_acceptance_passed": False,
        },
        "acceptance": {
            "passed": True,
            "criteria": [
                {"name": "joint_drift", "passed": True},
                {"name": "slider_transverse_drift", "passed": True},
                {"name": "loop_closure_error", "passed": True},
                {"name": "max_mises_stress_lower", "passed": True},
                {"name": "max_mises_stress_upper", "passed": True},
                {"name": "strain_energy_active", "passed": True},
                {"name": "energy_dissipation", "passed": True},
            ],
        },
        "provenance": {
            "action_count": 28,
            "intent_id": "fmbd5-crank-slider-golden-e2e",
            "compiler": "MechanismGraph",
            "release": "Abaqus 2025",
        },
    }

    evidence_dict = {
        "status": "pass",
        "case_id": "fmbd5_crank_slider",
        "solver_status": "completed",
        "process_succeeded": True,
        "release": "Abaqus 2025",
        "report": mock_report,
        "acceptance": mock_report["acceptance"],
        "verification": mock_report["verification"],
        "simulation_results": mock_report["simulation_results"],
        "provenance": mock_report["provenance"],
        "artifacts": [{"path": "/path/to/FMBD5GoldenJob.odb", "kind": "odb"}],
    }

    envelope = normalize_golden_evidence(evidence_dict)
    assert envelope.passed is True
    assert envelope.case_id == "fmbd5_crank_slider"
    assert envelope.release == "Abaqus 2025"
    assert envelope.solver_status == "completed"

    errors = validate_golden_evidence_dict(envelope.to_dict())
    assert len(errors) == 0, f"Validation errors: {errors}"


def test_fmbd5_catalog_registration():
    from abaqus_ai_agent.golden_registry import GoldenMatrixCatalog
    cat = GoldenMatrixCatalog()
    case = cat.get_case("fmbd5_crank_slider")
    assert case is not None
    assert case.category == "FMBD"
    assert case.physics_type == "flexible_multibody_dynamics"
    assert case.job_name == "FMBD5GoldenJob"
    assert len(case.criteria) == 7
    assert len(case.strict_criteria) == 1
    assert "closed_loop" in case.tags
    assert "mechanism_graph" in case.tags
