from abaqus_ai_agent.execution.runtime_smoke import (
    RuntimeSmokeResult,
    B28HarnessResult,
    build_runtime_smoke_script,
    build_b28_smoke_script,
    parse_smoke_output,
    parse_b28_output,
    execute_runtime_smoke,
    execute_b28_smoke,
)


def test_runtime_smoke_script_uses_portable_markers_and_apis():
    script = build_runtime_smoke_script("SmokeJob")
    assert "AIA_SMOKE_MARKER" in script
    assert "job.writeInput" in script
    assert "job.waitForCompletion()" in script
    assert "openOdb" in script
    assert 'f"' not in script
    assert "import regionToolset" in script
    assert "regionToolset.Region" in script
    assert "fieldOutputRequests" not in script
    assert "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in script
    assert "Abaqus JOB " in script


def test_b28_script_backward_compatibility_alias():
    script = build_b28_smoke_script("SmokeJob")
    assert "AIA_SMOKE_MARKER" in script


def test_runtime_smoke_parser_handles_new_marker_format():
    output = """
AIA_SMOKE_MARKER {"marker":"model_created"}
AIA_SMOKE_MARKER {"marker":"input_written"}
AIA_SMOKE_MARKER {"marker":"job_submitted"}
AIA_SMOKE_MARKER {"marker":"job_completed","status":"COMPLETED"}
AIA_SMOKE_MARKER {"marker":"odb_exists"}
AIA_SMOKE_MARKER {"marker":"odb_opened"}
AIA_SMOKE_MARKER {"marker":"required_outputs_present"}
AIA_SMOKE_MARKER {"marker":"script_completed","passed":true}
"""
    result = parse_smoke_output(output)
    assert isinstance(result, RuntimeSmokeResult)
    assert result.passed


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


def test_execute_b28_smoke_uses_existing_executor_and_parses_stdout():
    class FakeExecutor:
        def __init__(self):
            self.code = None
            self.timeout = None

        def execute(self, code, timeout=120):
            self.code = code
            self.timeout = timeout
            return {"stdout": '''
AIA_B28_MARKER {"marker":"model_created"}
AIA_B28_MARKER {"marker":"input_written"}
AIA_B28_MARKER {"marker":"job_submitted"}
AIA_B28_MARKER {"marker":"job_completed","status":"COMPLETED"}
AIA_B28_MARKER {"marker":"odb_exists"}
AIA_B28_MARKER {"marker":"odb_opened"}
AIA_B28_MARKER {"marker":"required_outputs_present"}
AIA_B28_MARKER {"marker":"script_completed","passed":true}
'''}

    executor = FakeExecutor()
    result = execute_b28_smoke(executor, job_name="RuntimeSmoke", timeout=77)

    assert result.passed
    assert executor.timeout == 77
    assert "JOB = 'RuntimeSmoke'" in executor.code


def test_execute_b28_smoke_does_not_upgrade_process_success_without_markers():
    class FakeExecutor:
        def execute(self, code, timeout=120):
            return {"stdout": "Process exited with code 0"}

    result = execute_b28_smoke(FakeExecutor())
    assert not result.passed
