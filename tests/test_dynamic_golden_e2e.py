import json
from tools.dynamic_golden_e2e import build_dynamic_golden_script, _extract_report
from abaqus_ai_agent.acceptance import evaluate_result_acceptance


def test_dynamic_golden_script_uses_existing_pipeline():
    script = build_dynamic_golden_script()
    for marker in (
        "tabular_amplitude(",
        "implicit_dynamic_step(",
        "field_output(",
        "material_density(",
        "AnalysisRunner(executor).run(",
        "extract_field(",
        "extract_history(",
        "energy_ratio_from_history_evidence(",
        "evaluate_result_acceptance(",
        "seed_part(",
        "generate_mesh(",
    ):
        assert marker in script


def test_dynamic_golden_script_has_no_direct_process_solver_bypass():
    script = build_dynamic_golden_script()
    assert "subprocess" not in script
    assert "run_input(" not in script
    assert "run_nogui(" not in script


def test_dynamic_golden_report_parser():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    stdout = (
        "noise\n"
        "AIAgent_DYNAMIC_GOLDEN_RESULT_BEGIN\n"
        + json.dumps(report)
        + "\nAIAgent_DYNAMIC_GOLDEN_RESULT_END\n"
    )
    assert _extract_report(stdout) == report


def test_dynamic_golden_report_parser_with_rpy_prefixes():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    raw_json = json.dumps(report, indent=2)
    rpy_lines = ["#: " + line for line in raw_json.splitlines()]
    stdout = (
        "AIAgent_DYNAMIC_GOLDEN_RESULT_BEGIN\n"
        + "\n".join(rpy_lines)
        + "\nAIAgent_DYNAMIC_GOLDEN_RESULT_END\n"
    )
    assert _extract_report(stdout) == report


def test_dynamic_golden_report_parser_rejects_missing_markers():
    assert _extract_report("{}") is None


def test_dynamic_golden_acceptance_gate_pass_and_fail():
    result_values = {
        "peak_displacement": 2.85,
        "end_displacement": 2.10,
        "frame_count": 22,
    }
    normal_criteria = (
        {
            "name": "peak_displacement_bound",
            "value_key": "peak_displacement",
            "operator": "<=",
            "limit": 5.0,
            "unit": "mm",
        },
        {
            "name": "multi_frame_count",
            "value_key": "frame_count",
            "operator": ">=",
            "limit": 10,
            "unit": "frames",
        },
    )
    pass_res = evaluate_result_acceptance(
        result_status="completed",
        values=result_values,
        criteria=normal_criteria,
    )
    assert pass_res.passed is True

    strict_criteria = (
        {
            "name": "peak_displacement_unphysical_strict",
            "value_key": "peak_displacement",
            "operator": "<=",
            "limit": 0.0001,
            "unit": "mm",
        },
    )
    fail_res = evaluate_result_acceptance(
        result_status="completed",
        values=result_values,
        criteria=strict_criteria,
    )
    assert fail_res.passed is False
    assert "criterion:peak_displacement_unphysical_strict" in fail_res.failures
