from unittest.mock import MagicMock
import pytest
from pathlib import Path
import hashlib

from abaqus_ai_agent.validation.assembly_guard import AssemblyContractViolation
from abaqus_ai_agent.execution.input_modes import solve_user_inp


MISSING_PART_INP = """
*HEADING
Degraded single part handle
*PART, NAME=HANDLE
*NODE
1, 0.0, 0.0, 0.0
*ELEMENT, TYPE=C3D10M, ELSET=HANDLE_ELEMS
1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*END ASSEMBLY
*STEP
*STATIC
*END STEP
"""

COMPLIANT_MULTIPART_INP = """
*HEADING
Door handle assembly compliant
*PART, NAME=HANDLE
*NODE
1, 0.0, 0.0, 0.0
*ELEMENT, TYPE=C3D10M, ELSET=HANDLE_ELEMS
1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
*SURFACE, NAME=HANDLE_SURF
HANDLE_ELEMS, S1
*END PART
*PART, NAME=BASE
*NODE
100, 0.0, 0.0, 0.0
*ELEMENT, TYPE=C3D10M, ELSET=BASE_ELEMS
100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110
*SURFACE, NAME=BASE_SURF
BASE_ELEMS, S1
*END PART
*ASSEMBLY, NAME=ASSEMBLY
*INSTANCE, NAME=HANDLE_1, PART=HANDLE
*END INSTANCE
*INSTANCE, NAME=BASE_1, PART=BASE
*END INSTANCE
*CONTACT PAIR, INTERACTION=INT-1
HANDLE_1.HANDLE_SURF, BASE_1.BASE_SURF
*END ASSEMBLY
*BOUNDARY
BASE_1.HOLE_SET, ENCASTRE
*STEP
*STATIC
*END STEP
"""


def test_solve_user_inp_blocks_submission_on_assembly_violation(tmp_path: Path):
    inp_file = tmp_path / "test_degraded.inp"
    inp_file.write_text(MISSING_PART_INP, encoding="utf-8")

    executor = MagicMock()
    executor.workdir = str(tmp_path)
    executor.run_input = MagicMock()
    executor.execute = MagicMock()

    multipart_scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }

    # Solver execution MUST be blocked, throwing AssemblyContractViolation
    with pytest.raises(AssemblyContractViolation) as exc_info:
        solve_user_inp(
            executor=executor,
            inp_path=inp_file,
            assembly_scope=multipart_scope,
        )

    assert "Direct INP solve blocked prior to solver invocation" in str(exc_info.value)
    assert "BASE_1" in str(exc_info.value)

    # CRITICAL: Verify that the solver was NEVER invoked!
    assert executor.run_input.call_count == 0
    assert executor.execute.call_count == 0


def test_cae_pipeline_blocks_submission_on_assembly_violation(tmp_path: Path, monkeypatch):
    """Verify that CAE model pipeline dynamically triggers writeInput(), halts on assembly
    violation in the generated file, and the solver jobs.submit() is strictly zero."""
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
    from abaqus_ai_agent.execution.jobs import JobController

    workdir = tmp_path / "cae_run"
    workdir.mkdir()

    job_name = "DoorHandleJob"
    inp_file = workdir / f"{job_name}.inp"
    # CRITICAL: Verify file does NOT exist before pipeline run
    assert not inp_file.exists()

    executor = MagicMock()
    executor.workdir = str(workdir)
    executor.is_test_mode = True

    # Simulate Abaqus kernel executing writeInput() when requested
    def fake_execute(cmd: str):
        if "writeInput" in cmd:
            inp_file.write_text(MISSING_PART_INP, encoding="utf-8")
        return ""

    executor.execute = MagicMock(side_effect=fake_execute)

    mock_submit = MagicMock()
    monkeypatch.setattr(JobController, "submit", mock_submit)

    multipart_scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }

    class MockIntent:
        def __init__(self, scope):
            self.assembly_scope = scope

    runner = AnalysisRunner(executor=executor)

    run = runner.run(
        model_name="HandleModel",
        job_name=job_name,
        workdir=str(workdir),
        engineering_intent=MockIntent(multipart_scope),
    )

    # Verify that writeInput was indeed executed and generated the file
    assert inp_file.exists()
    assert any("writeInput" in str(c) for c in executor.execute.call_args_list)

    assert run.state.value == "failed"
    errors = [d.get("error", "") for d in run.diagnostics if isinstance(d, dict)]
    assert any("Pre-submission CAE model audit blocked solver launch" in err for err in errors)
    assert any("BASE_1" in err for err in errors)

    # CRITICAL: Assert solver submission was NEVER called!
    assert mock_submit.call_count == 0


def test_cae_pipeline_binds_hash_and_submits_compliant_assembly(tmp_path: Path, monkeypatch):
    """Verify that CAE model pipeline dynamically generates compliant deck via writeInput(),
    binds its SHA-256 hash to provenance, verifies consistency, and successfully submits."""
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
    from abaqus_ai_agent.execution.jobs import JobController, JobStatus, JobState

    workdir = tmp_path / "cae_run_compliant"
    workdir.mkdir()

    job_name = "DoorHandleCompliantJob"
    inp_file = workdir / f"{job_name}.inp"
    # CRITICAL: Verify file does NOT exist before pipeline run
    assert not inp_file.exists()

    executor = MagicMock()
    executor.workdir = str(workdir)
    executor.is_test_mode = True

    def fake_execute(cmd: str):
        if "writeInput" in cmd:
            inp_file.write_text(COMPLIANT_MULTIPART_INP, encoding="utf-8")
        return ""

    executor.execute = MagicMock(side_effect=fake_execute)

    mock_submit = MagicMock(return_value=JobStatus(job_name, JobState.COMPLETED, {}))
    monkeypatch.setattr(JobController, "submit", mock_submit)

    multipart_scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }

    class MockIntent:
        def __init__(self, scope):
            self.assembly_scope = scope

    runner = AnalysisRunner(executor=executor)

    run = runner.run(
        model_name="HandleModel",
        job_name=job_name,
        workdir=str(workdir),
        engineering_intent=MockIntent(multipart_scope),
    )

    # 1. Verify file was created dynamically by writeInput()
    assert inp_file.exists()
    assert any("writeInput" in str(c) for c in executor.execute.call_args_list)

    # 2. Verify solver submit was invoked exactly once
    assert mock_submit.call_count == 1

    # 3. Verify cryptographic deck hash binding to provenance
    expected_sha256 = hashlib.sha256(COMPLIANT_MULTIPART_INP.encode("utf-8")).hexdigest()
    assert run.provenance.input_hash == expected_sha256
    assert run.provenance.metadata.get("audited_inp_sha256") == expected_sha256
    assert run.provenance.metadata.get("audited_inp_path") == str(inp_file)


def test_cae_pipeline_aborts_on_post_audit_tampering(tmp_path: Path, monkeypatch):
    """Verify that if solver deck is modified after audit but before submission,
    pre-submission consistency check fails closed and blocks solver invocation."""
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
    from abaqus_ai_agent.execution.jobs import JobController
    from abaqus_ai_agent.validation import assembly_guard

    workdir = tmp_path / "cae_run_tampered"
    workdir.mkdir()

    job_name = "DoorHandleTamperedJob"
    inp_file = workdir / f"{job_name}.inp"
    assert not inp_file.exists()

    executor = MagicMock()
    executor.workdir = str(workdir)
    executor.is_test_mode = True

    def fake_execute(cmd: str):
        if "writeInput" in cmd:
            inp_file.write_text(COMPLIANT_MULTIPART_INP, encoding="utf-8")
        return ""

    executor.execute = MagicMock(side_effect=fake_execute)

    # Hook into audit_inp_assembly_contract: after audit passes, tamper with the file on disk
    original_audit = assembly_guard.audit_inp_assembly_contract

    def audit_and_tamper(deck, **kwargs):
        res = original_audit(deck, **kwargs)
        # Tamper with file on disk right after audit
        inp_file.write_text(MISSING_PART_INP, encoding="utf-8")
        return res

    monkeypatch.setattr(assembly_guard, "audit_inp_assembly_contract", audit_and_tamper)

    mock_submit = MagicMock()
    monkeypatch.setattr(JobController, "submit", mock_submit)

    multipart_scope = {
        "parts": [
            {"instance_name": "HANDLE_1"},
            {"instance_name": "BASE_1"},
        ],
        "contacts": [{"master": "HANDLE_1", "slave": "BASE_1"}],
    }

    class MockIntent:
        def __init__(self, scope):
            self.assembly_scope = scope

    runner = AnalysisRunner(executor=executor)

    run = runner.run(
        model_name="HandleModel",
        job_name=job_name,
        workdir=str(workdir),
        engineering_intent=MockIntent(multipart_scope),
    )

    # Consistency mismatch must fail the run and prevent solver submit
    assert run.state.value == "failed"
    errors = [d.get("error", "") for d in run.diagnostics if isinstance(d, dict)]
    assert any("Pre-submission consistency mismatch" in err for err in errors)
    assert mock_submit.call_count == 0
