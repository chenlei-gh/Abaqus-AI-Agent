from abaqus_ai_agent.execution.b28_harness import (
    B28HarnessResult,
    build_b28_smoke_script,
    parse_b28_output,
)


def test_b28_script_uses_python27_compatible_markers_and_apis():
    script = build_b28_smoke_script("SmokeJob")
    assert "AIA_B28_MARKER" in script
    assert "job.writeInput" in script
    assert "job.waitForCompletion()" in script
    assert "openOdb" in script
    assert "f"" not in script
    assert "regionToolset.Region" in script


def test_b28_parser_requires_all_evidence():
    output = """
AIA_B28_MARKER {"marker":"model_created"}
AIA_B28_MARKER {"marker":"input_written"}
AIA_B28_MARKER {"marker":"job_submitted"}
AIA_B28_MARKER {"marker":"job_completed","status":"COMPLETED"}
AIA_B28_MARKER {"marker":"odb_exists"}
AIA_B28_MARKER {"marker":"odb_opened"}
AIA_B28_MARKER {"marker":"required_outputs_present"}
AIA_B28_MARKER {"marker":"script_completed","passed":true}
"""
    result = parse_b28_output(output)
    assert isinstance(result, B28HarnessResult)
    assert result.passed


def test_b28_parser_does_not_treat_exit_without_markers_as_success():
    result = parse_b28_output("Process exited with code 0")
    assert not result.passed
    assert not result.script_completed


def test_b28_parser_distinguishes_solver_failure():
    output = """
AIA_B28_MARKER {"marker":"model_created"}
AIA_B28_MARKER {"marker":"input_written"}
AIA_B28_MARKER {"marker":"job_submitted"}
AIA_B28_MARKER {"marker":"job_completed","status":"ABORTED"}
AIA_B28_MARKER {"marker":"error","error_class":"solver_job","error_message":"ABORTED"}
AIA_B28_MARKER {"marker":"script_completed","passed":false}
"""
    result = parse_b28_output(output)
    assert not result.passed
    assert result.error_class == "solver_job"
