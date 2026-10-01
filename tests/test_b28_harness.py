from abaqus_ai_agent.execution.b28_harness import (
    B28HarnessResult,
    build_b28_smoke_script,
    parse_b28_output,
    execute_b28_smoke,
)


def test_b28_script_uses_python27_compatible_markers_and_apis():
    script = build_b28_smoke_script("SmokeJob")
    assert "AIA_B28_MARKER" in script
    assert "job.writeInput" in script
    assert "job.waitForCompletion()" in script
    assert "openOdb" in script
    assert 'f"' not in script
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
