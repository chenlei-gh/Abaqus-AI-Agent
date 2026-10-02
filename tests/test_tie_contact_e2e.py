import json
from tools.tie_contact_e2e import build_tie_contact_script, _extract_report


def test_tie_contact_script_uses_existing_pipeline():
    script = build_tie_contact_script()
    for marker in (
        "tie(",
        "AnalysisRunner(executor).run(",
        "extract_field(",
        "reaction_balance_from_field_evidence(",
        "evaluate_result_acceptance(",
        "seed_part(",
        "generate_mesh(",
        "ContactDiagnosticReport(",
    ):
        assert marker in script


def test_tie_contact_script_has_no_direct_process_solver_bypass():
    script = build_tie_contact_script()
    assert "subprocess" not in script
    assert "run_input(" not in script
    assert "run_nogui(" not in script


def test_tie_contact_report_parser():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    stdout = (
        "noise\n"
        "AIAgent_TIE_CONTACT_RESULT_BEGIN\n"
        + json.dumps(report)
        + "\nAIAgent_TIE_CONTACT_RESULT_END\n"
    )
    assert _extract_report(stdout) == report


def test_tie_contact_report_parser_with_rpy_prefixes():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    raw_json = json.dumps(report, indent=2)
    rpy_lines = ["#: " + line for line in raw_json.splitlines()]
    stdout = (
        "AIAgent_TIE_CONTACT_RESULT_BEGIN\n"
        + "\n".join(rpy_lines)
        + "\nAIAgent_TIE_CONTACT_RESULT_END\n"
    )
    assert _extract_report(stdout) == report


def test_tie_contact_report_parser_rejects_missing_markers():
    assert _extract_report("{}") is None
