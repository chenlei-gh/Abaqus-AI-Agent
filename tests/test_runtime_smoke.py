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
    assert "job.waitForCompletion(timeOut=WAIT_TIMEOUT)" in script
    # The unbounded form lets the script hang where a host transport timeout
    # cannot stop the kernel job.
    assert "job.waitForCompletion()" not in script
    assert "openOdb" in script
    assert 'f"' not in script
    assert "import regionToolset" in script
    assert "regionToolset.Region" in script
    assert "fieldOutputRequests" not in script
    assert "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in script
    assert "Abaqus JOB " in script


def test_runtime_smoke_script_binds_wait_timeout():
    script = build_runtime_smoke_script("SmokeJob", wait_timeout=42)
    compile(script, "<smoke>", "exec")
    assert "WAIT_TIMEOUT = 42" in script
    assert "job.waitForCompletion(timeOut=WAIT_TIMEOUT)" in script


def test_wait_expiry_alongside_a_clean_pass_is_invalid():
    """A bounded wait that expired must not be silently absorbed by the
    artifact fallback: the run has no timeout-free evidence."""
    output = """
AIA_SMOKE_MARKER {"marker":"model_created"}
AIA_SMOKE_MARKER {"marker":"input_written"}
AIA_SMOKE_MARKER {"marker":"job_submitted"}
AIA_SMOKE_MARKER {"marker":"job_wait_timed_out","error_message":"AbaqusException: timeOut = 60"}
AIA_SMOKE_MARKER {"marker":"job_completed","status":"COMPLETED"}
AIA_SMOKE_MARKER {"marker":"odb_exists"}
AIA_SMOKE_MARKER {"marker":"odb_opened"}
AIA_SMOKE_MARKER {"marker":"required_outputs_present"}
AIA_SMOKE_MARKER {"marker":"script_completed","passed":true}
"""
    result = parse_smoke_output(output)
    assert not result.passed
    assert "job_wait_timed_out_with_success" in result.invalid_reasons


def test_wait_expiry_without_a_clean_pass_reports_the_timeout():
    output = """
AIA_SMOKE_MARKER {"marker":"model_created"}
AIA_SMOKE_MARKER {"marker":"input_written"}
AIA_SMOKE_MARKER {"marker":"job_submitted"}
AIA_SMOKE_MARKER {"marker":"job_wait_timed_out","error_message":"AbaqusException: timeOut = 60"}
AIA_SMOKE_MARKER {"marker":"error","error_class":"solver_job","error_message":"RUNNING"}
"""
    result = parse_smoke_output(output)
    assert not result.passed
    # The expiry is the more specific cause; it must not be masked by the
    # generic job-status error.
    assert "timeOut" in (result.error_message or "")


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


def test_all_legacy_b28_aliases_are_merged_into_runtime_smoke():
    from abaqus_ai_agent.execution import runtime_smoke

    assert runtime_smoke.B28HarnessResult is runtime_smoke.RuntimeSmokeResult
    assert runtime_smoke.build_b28_smoke_script is runtime_smoke.build_runtime_smoke_script
    assert runtime_smoke.classify_b28_markers is runtime_smoke.classify_smoke_markers
    assert runtime_smoke.execute_b28_smoke is runtime_smoke.execute_runtime_smoke
    assert runtime_smoke.parse_b28_output is runtime_smoke.parse_smoke_output
def _passing_stream(run_id=None):
    stages = [
        {"marker": "model_created"},
        {"marker": "input_written"},
        {"marker": "job_submitted"},
        {"marker": "job_completed", "status": "COMPLETED"},
        {"marker": "odb_exists"},
        {"marker": "odb_opened"},
        {"marker": "required_outputs_present"},
        {"marker": "script_completed", "passed": True},
    ]
    import json as _json
    lines = []
    for m in stages:
        if run_id:
            m = dict(m, run_id=run_id)
        lines.append("AIA_SMOKE_MARKER " + _json.dumps(m, sort_keys=True))
    return "\n".join(lines)


def test_duplicate_identical_marker_is_invalid():
    out = _passing_stream() + "\nAIA_SMOKE_MARKER {\"marker\":\"model_created\"}"
    result = parse_smoke_output(out)
    assert not result.passed
    assert any(r.startswith("duplicate_marker:") for r in result.invalid_reasons)


def test_conflicting_duplicate_marker_is_invalid():
    out = (
        _passing_stream()
        + "\nAIA_SMOKE_MARKER {\"marker\":\"job_completed\",\"status\":\"ABORTED\"}"
    )
    result = parse_smoke_output(out)
    assert not result.passed
    assert any(r.startswith("conflicting_marker:") for r in result.invalid_reasons)


def test_error_plus_success_is_contradiction():
    out = _passing_stream() + "\nAIA_SMOKE_MARKER {\"marker\":\"error\",\"error_class\":\"x\"}"
    result = parse_smoke_output(out)
    assert not result.passed
    assert "contradictory_markers:error_and_success" in result.invalid_reasons


def test_out_of_order_markers_are_invalid():
    out = (
        "AIA_SMOKE_MARKER {\"marker\":\"input_written\"}\n"
        "AIA_SMOKE_MARKER {\"marker\":\"model_created\"}\n"
        "AIA_SMOKE_MARKER {\"marker\":\"job_submitted\"}\n"
        "AIA_SMOKE_MARKER {\"marker\":\"job_completed\",\"status\":\"COMPLETED\"}\n"
        "AIA_SMOKE_MARKER {\"marker\":\"odb_exists\"}\n"
        "AIA_SMOKE_MARKER {\"marker\":\"odb_opened\"}\n"
        "AIA_SMOKE_MARKER {\"marker\":\"required_outputs_present\"}\n"
        "AIA_SMOKE_MARKER {\"marker\":\"script_completed\",\"passed\":true}"
    )
    result = parse_smoke_output(out)
    assert not result.passed
    assert "out_of_order_markers" in result.invalid_reasons


def test_run_id_binding_accepts_only_the_expected_run():
    assert parse_smoke_output(_passing_stream("run-a"), expected_run_id="run-a").passed
    foreign = parse_smoke_output(_passing_stream("run-b"), expected_run_id="run-a")
    assert not foreign.passed
    assert "no_markers_for_run:run-a" in foreign.invalid_reasons
    unbound = parse_smoke_output(_passing_stream(), expected_run_id="run-a")
    assert not unbound.passed
    assert "no_markers_for_run:run-a" in unbound.invalid_reasons


def test_builder_embeds_run_id_in_markers():
    script = build_runtime_smoke_script("SmokeJob", run_id="abc123")
    assert "RUN_ID = 'abc123'" in script
    assert "payload[\"run_id\"] = RUN_ID" in script
    legacy = build_runtime_smoke_script("SmokeJob")
    assert "RUN_ID = None" in legacy
