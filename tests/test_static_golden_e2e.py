from tools.static_golden_e2e import build_static_golden_script, _extract_report


def test_static_golden_script_uses_existing_pipeline():
    script = build_static_golden_script()
    for marker in (
        "build_static_plan(",
        "AnalysisRunner(executor).run(",
        "extract_field(",
        "reaction_balance_from_field_evidence(",
        "evaluate_result_acceptance(",
        "seed_part(",
        "generate_mesh(",
        "plan.actions[-1]",
    ):
        assert marker in script


def test_static_golden_script_has_no_direct_process_solver_bypass():
    script = build_static_golden_script()
    assert "subprocess" not in script
    assert "run_input(" not in script
    assert "run_nogui(" not in script


def test_static_golden_report_parser():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    import json
    stdout = (
        "noise\n"
        "AIAgent_STATIC_GOLDEN_RESULT_BEGIN\n"
        + json.dumps(report)
        + "\nAIAgent_STATIC_GOLDEN_RESULT_END\n"
    )
    assert _extract_report(stdout) == report


def test_static_golden_report_parser_rejects_missing_markers():
    assert _extract_report("{}") is None
