"""Tests for T-P3: unified solver terminal-state classification.

Contract under test:
- COMPLETED requires sufficient solver-authored positive evidence;
- ABORTED requires clear evidence of abnormal termination;
- UNKNOWN covers insufficient, contradictory, or incomplete evidence;
- exit code 0 and ODB existence are auxiliary evidence only, never decisive.
"""

import json
import os
import subprocess

import pytest

from abaqus_ai_agent.engineering_status import EngineeringStatus
from abaqus_ai_agent.execution.artifacts import inspect_job_diagnostics
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
from abaqus_ai_agent.execution.batch import BatchResult
from abaqus_ai_agent.execution.jobs import JobState, JobStatus
from abaqus_ai_agent.execution.solver import (
    AbaqusBatchJob,
    AbaqusJobResult,
    SolverTerminalState,
    classify_solver_terminal_state,
    execute_abaqus_batch_job,
)
from abaqus_ai_agent.execution.watchdog import (
    SolverProcessStalledError,
    WatchedProcessResult,
)


class _ExecutingDiagnosticsExecutor:
    """Run the diagnostics probe locally without starting Abaqus."""

    def __init__(self, workdir):
        self.workdir = str(workdir)

    def execute(self, code, timeout=120):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<diagnostics>", "exec"), {"__name__": "__test__"})
        return buf.getvalue()


# ------------------------------------------------------------------ classifier

def test_completed_requires_solver_authored_evidence():
    verdict = classify_solver_terminal_state(
        sta_completed=True, returncode=0, odb_present=True, odb_valid=True)
    assert verdict.state is SolverTerminalState.COMPLETED
    assert verdict.evidence


def test_exit_code_zero_alone_is_unknown():
    """Counter-case: returncode 0 without completion evidence is not success."""
    verdict = classify_solver_terminal_state(returncode=0)
    assert verdict.state is SolverTerminalState.UNKNOWN


def test_odb_existence_alone_is_unknown():
    """Counter-case: a valid ODB without solver completion evidence is not success."""
    verdict = classify_solver_terminal_state(returncode=0, odb_present=True, odb_valid=True)
    assert verdict.state is SolverTerminalState.UNKNOWN


def test_odb_present_but_log_aborted_is_aborted():
    """Counter-case: ODB exists but the solver log reports abnormal termination."""
    verdict = classify_solver_terminal_state(
        returncode=0, odb_present=True, odb_valid=True, sta_not_completed=True)
    assert verdict.state is SolverTerminalState.ABORTED


def test_conflicting_completion_and_failure_markers_are_unknown():
    """Counter-case: completion and failure evidence in the logs conflict."""
    verdict = classify_solver_terminal_state(
        sta_completed=True, sta_not_completed=True, returncode=0)
    assert verdict.state is SolverTerminalState.UNKNOWN
    assert "contradictory" in verdict.evidence[0]


def test_kernel_completed_but_sta_aborted_is_unknown():
    """Counter-case: the kernel layer and the solver log disagree."""
    verdict = classify_solver_terminal_state(kernel_completed=True, sta_not_completed=True)
    assert verdict.state is SolverTerminalState.UNKNOWN


def test_kernel_aborted_but_sta_completed_is_unknown():
    verdict = classify_solver_terminal_state(kernel_aborted=True, sta_completed=True)
    assert verdict.state is SolverTerminalState.UNKNOWN


def test_nonzero_returncode_is_aborted_unless_solver_claims_completion():
    assert classify_solver_terminal_state(returncode=2).state is SolverTerminalState.ABORTED
    verdict = classify_solver_terminal_state(returncode=2, sta_completed=True)
    assert verdict.state is SolverTerminalState.UNKNOWN


def test_watchdog_kill_is_decisive_abort():
    """A stall/timeout kill aborts the process even against stale log markers."""
    verdict = classify_solver_terminal_state(process_killed=True, sta_completed=True)
    assert verdict.state is SolverTerminalState.ABORTED


def test_monitor_lost_but_solver_reports_completion_is_completed():
    """Monitoring losing the thread says nothing about the solve; the solver's
    own completion record carries the decision."""
    verdict = classify_solver_terminal_state(sta_completed=True)
    assert verdict.state is SolverTerminalState.COMPLETED


def test_no_evidence_at_all_is_unknown():
    """Counter-case: missing logs prove nothing in either direction."""
    assert classify_solver_terminal_state().state is SolverTerminalState.UNKNOWN


def test_msg_error_marker_is_aborted():
    assert classify_solver_terminal_state(returncode=0, msg_error=True).state is SolverTerminalState.ABORTED


def test_completion_claim_contradicted_by_artifact_is_unknown():
    assert classify_solver_terminal_state(
        sta_completed=True, returncode=0, odb_present=False).state is SolverTerminalState.UNKNOWN
    assert classify_solver_terminal_state(
        sta_completed=True, returncode=0, odb_present=True, odb_valid=False
    ).state is SolverTerminalState.UNKNOWN


# ------------------------------------------------------------- diagnostics range

def test_diagnostics_scan_full_msg_for_early_errors(tmp_path):
    """An early ***ERROR must be visible even when it is outside the tail."""
    workdir = tmp_path / "diag"
    workdir.mkdir()
    msg = workdir / "Job_EARLY.msg"
    msg.write_text(
        "***ERROR: early solver failure\n"
        + "\n".join(f"iteration line {i}" for i in range(120))
        + "\nTHE ANALYSIS HAS BEEN COMPLETED\n",
        encoding="utf-8",
    )

    diags = inspect_job_diagnostics(
        _ExecutingDiagnosticsExecutor(workdir), "Job_EARLY",
        workdir=str(workdir), tail_lines=10,
    )
    assert diags[".msg"]["has_error"] is True
    assert "***ERROR" not in diags[".msg"]["tail"]


def test_infrastructure_states_are_not_solver_success(tmp_path):
    """Document the public boundary: infrastructure outcomes are not solves."""
    odb = tmp_path / "Job.odb"
    odb.write_bytes(b"odb")

    for state in ("DRY_RUN", "ERROR", "UNKNOWN", "ABORTED"):
        result = AbaqusJobResult(
            job_name="Job", state=state, returncode=0,
            workdir=tmp_path, is_live=True, odb_path=odb,
        )
        assert result.is_success is False

    process = BatchResult(command=("abaqus", "job=Job"), return_code=0)
    assert process.succeeded is True  # process-level only; not a solver verdict


# ------------------------------------------------------- execute_abaqus_batch_job

# Built without escape sequences so the bytes are exactly what the authenticity
# pre-filter sees: a structured head/tail passes; a uniform zero fill fails.
_VALID_ODB = bytes([0x7F]) + b"SIMULIA" + bytes([0x00, 0x01, 0x02, 0x03]) + bytes(4084) + bytes([0x01, 0x02])
_ZERO_FILL_ODB = bytes(8192)


def _batch_job(tmp_path, name="Job_TP3"):
    inp = tmp_path / f"{name}.inp"
    inp.write_text("*HEADING\\n", encoding="utf-8")
    return AbaqusBatchJob(job_name=name, inp_path=inp, workdir=tmp_path, timeout_seconds=10)


def _mock_watchdog_return(monkeypatch, tmp_path, returncode):
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.watchdog.run_with_watchdog",
        lambda *a, **k: WatchedProcessResult(
            command=("abaqus",), returncode=returncode, stdout="", stderr="",
            duration=0.1, workdir=str(tmp_path)),
    )
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.solver.find_abaqus_executable", lambda x: "dummy_abaqus")


def test_batch_job_completed_baseline(tmp_path, monkeypatch):
    """Baseline: rc0 + valid ODB + sta completion marker -> COMPLETED."""
    job = _batch_job(tmp_path)
    (tmp_path / f"{job.job_name}.odb").write_bytes(_VALID_ODB)
    (tmp_path / f"{job.job_name}.sta").write_text(
        "THE ANALYSIS HAS COMPLETED SUCCESSFULLY\\n", encoding="utf-8")
    _mock_watchdog_return(monkeypatch, tmp_path, 0)

    result = execute_abaqus_batch_job(job)
    assert result.state == "COMPLETED"
    assert result.is_success
    assert any(d.startswith("TERMINAL_EVIDENCE:") for d in result.diagnostics)


def test_batch_job_rc0_and_odb_without_sta_marker_is_unknown(tmp_path, monkeypatch):
    """Core counter-case: exit 0 + valid ODB but no solver completion statement."""
    job = _batch_job(tmp_path)
    (tmp_path / f"{job.job_name}.odb").write_bytes(_VALID_ODB)
    (tmp_path / f"{job.job_name}.sta").write_text("  STEP 1  INCREMENT 3\\n", encoding="utf-8")
    _mock_watchdog_return(monkeypatch, tmp_path, 0)

    result = execute_abaqus_batch_job(job)
    assert result.state == "UNKNOWN"
    assert not result.is_success


def test_batch_job_rc0_odb_but_sta_aborted(tmp_path, monkeypatch):
    """Counter-case: ODB exists but the solver log shows abnormal termination."""
    job = _batch_job(tmp_path)
    (tmp_path / f"{job.job_name}.odb").write_bytes(_VALID_ODB)
    (tmp_path / f"{job.job_name}.sta").write_text(
        "THE ANALYSIS HAS NOT BEEN COMPLETED\\n", encoding="utf-8")
    _mock_watchdog_return(monkeypatch, tmp_path, 0)

    result = execute_abaqus_batch_job(job)
    assert result.state == "ABORTED"
    assert not result.is_success


def test_batch_job_nonzero_returncode_is_aborted(tmp_path, monkeypatch):
    job = _batch_job(tmp_path)
    _mock_watchdog_return(monkeypatch, tmp_path, 2)

    result = execute_abaqus_batch_job(job)
    assert result.state == "ABORTED"


def test_batch_job_timeout_kill_unifies_to_aborted(tmp_path, monkeypatch):
    """Watchdog hard-timeout kill: ABORTED under the unified contract."""
    job = _batch_job(tmp_path)

    def mock_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd=("abaqus",), timeout=10)

    monkeypatch.setattr("abaqus_ai_agent.execution.watchdog.run_with_watchdog", mock_timeout)
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.solver.find_abaqus_executable", lambda x: "dummy_abaqus")

    result = execute_abaqus_batch_job(job)
    assert result.state == "ABORTED"
    assert any("SOLVER_TIMEOUT_KILL" in d for d in result.diagnostics)


def test_batch_job_completed_claim_with_invalid_odb_is_unknown(tmp_path, monkeypatch):
    """Counter-case: sta claims completion but the ODB is a corrupt artifact."""
    job = _batch_job(tmp_path)
    (tmp_path / f"{job.job_name}.odb").write_bytes(_ZERO_FILL_ODB)
    (tmp_path / f"{job.job_name}.sta").write_text(
        "THE ANALYSIS HAS COMPLETED SUCCESSFULLY\\n", encoding="utf-8")
    _mock_watchdog_return(monkeypatch, tmp_path, 0)

    result = execute_abaqus_batch_job(job)
    assert result.state == "UNKNOWN"
    assert not result.is_success


# ------------------------------------------------------------- analysis_run gate

class _TerminalExecutor:
    """Executor answering kernel status and the diagnostics script from disk."""

    def __init__(self, workdir, job_name, kernel_status,
                 sta_text="", msg_text="", log_text=""):
        self.workdir = str(workdir)
        self.job_name = job_name
        self.kernel_status = kernel_status
        os.makedirs(self.workdir, exist_ok=True)
        if sta_text:
            with open(os.path.join(self.workdir, f"{job_name}.sta"), "w", encoding="utf-8") as fh:
                fh.write(sta_text)
        if msg_text:
            with open(os.path.join(self.workdir, f"{job_name}.msg"), "w", encoding="utf-8") as fh:
                fh.write(msg_text)
        if log_text:
            with open(os.path.join(self.workdir, f"{job_name}.log"), "w", encoding="utf-8") as fh:
                fh.write(log_text)

    def execute(self, code, timeout=120):
        if "result[suffix]" in code:
            result = {}
            for suffix in (".msg", ".sta", ".dat", ".log"):
                path = os.path.join(self.workdir, self.job_name + suffix)
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                    upper = text.upper()
                    result[suffix] = {
                        "path": path,
                        "tail": text,
                        "has_completed": "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in upper,
                        "has_not_completed": "THE ANALYSIS HAS NOT BEEN COMPLETED" in upper,
                        "has_error": "***ERROR" in upper or "***FATAL" in upper,
                    }
            return json.dumps(result)
        if "waitForCompletion" in code or "print(mdb.jobs" in code:
            return self.kernel_status
        return ""

    def snapshot(self):
        return None


def _run_terminal_case(tmp_path, kernel_status, sta_text="", msg_text=""):
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
    workdir = tmp_path / "term_run"
    job_name = "Job_TP3_TERM"
    executor = _TerminalExecutor(workdir, job_name, kernel_status,
                                 sta_text=sta_text, msg_text=msg_text)
    runner = AnalysisRunner(executor)
    return runner.run(model_name="M", job_name=job_name, workdir=str(workdir))


def _terminal_diag(run):
    return [d for d in run.diagnostics
            if isinstance(d, dict) and d.get("reason") == "job_terminal_not_completed"]


def test_runner_kernel_completed_with_sta_marker_proceeds(tmp_path):
    run = _run_terminal_case(
        tmp_path, "COMPLETED", sta_text="THE ANALYSIS HAS COMPLETED SUCCESSFULLY\\n")
    assert run.job_status.state is JobState.COMPLETED
    assert not _terminal_diag(run)
    assert run.engineering_status != EngineeringStatus.TERMINAL_UNKNOWN.value


def test_runner_early_msg_error_with_tail_completion_is_terminal_unknown(tmp_path):
    """Regression: an early ***ERROR contradicts a later completion marker.

    The completion marker is present in the bounded tail and in .sta, but the
    full .msg contains a solver error outside that tail. The frozen contract
    requires UNKNOWN for contradictory evidence.
    """
    early_error = (
        "***ERROR: early solver failure\n"
        + "\n".join(f"iteration line {i}" for i in range(120))
        + "\nTHE ANALYSIS HAS BEEN COMPLETED\n"
    )
    run = _run_terminal_case(
        tmp_path, "COMPLETED",
        sta_text="THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n",
        msg_text=early_error,
    )
    assert run.state.value == "failed"
    assert run.engineering_status == EngineeringStatus.TERMINAL_UNKNOWN.value
    diag = _terminal_diag(run)
    assert diag and diag[0]["terminal_state"] == "UNKNOWN"
    assert any("***ERROR" in evidence for evidence in diag[0]["terminal_evidence"])


def test_runner_kernel_completed_but_sta_aborted_is_terminal_unknown(tmp_path):
    """Regression guard: kernel COMPLETED contradicted by the solver log must not
    proceed as success (previously trusted unconditionally)."""
    run = _run_terminal_case(
        tmp_path, "COMPLETED", sta_text="THE ANALYSIS HAS NOT BEEN COMPLETED\\n")
    assert run.state.value == "failed"
    assert run.engineering_status == EngineeringStatus.TERMINAL_UNKNOWN.value
    diag = _terminal_diag(run)
    assert diag and diag[0]["terminal_state"] == "UNKNOWN"
    assert any("contradictory" in e for e in diag[0]["terminal_evidence"])


def test_runner_monitor_timeout_with_sta_marker_proceeds(tmp_path):
    """The monitoring layer losing the thread does not contradict the solver's
    own completion record (rescue preserved, log line no longer required)."""
    run = _run_terminal_case(
        tmp_path, "TIMEOUT", sta_text="THE ANALYSIS HAS COMPLETED SUCCESSFULLY\\n")
    assert not _terminal_diag(run)
    assert run.engineering_status != EngineeringStatus.TERMINAL_UNKNOWN.value
    # The proven completion is promoted into job_status so downstream layers
    # (acceptance, reporting) read the evidence-backed state, not the lost
    # monitor string.
    assert run.job_status.state is JobState.COMPLETED


def test_runner_unparseable_kernel_status_with_sta_marker_promotes(tmp_path):
    """Kernel status strings that fail to parse (UNKNOWN) are corrected to
    COMPLETED when solver-authored evidence proves completion."""
    run = _run_terminal_case(
        tmp_path, "gibberish-unparseable",
        sta_text="THE ANALYSIS HAS COMPLETED SUCCESSFULLY\\n")
    assert not _terminal_diag(run)
    assert run.job_status.state is JobState.COMPLETED


def test_runner_kernel_aborted_with_sta_marker_is_unknown(tmp_path):
    """Counter-case: kernel ABORTED conflicting with a sta completion marker."""
    run = _run_terminal_case(
        tmp_path, "ABORTED", sta_text="THE ANALYSIS HAS COMPLETED SUCCESSFULLY\\n")
    assert run.state.value == "failed"
    assert run.engineering_status == EngineeringStatus.TERMINAL_UNKNOWN.value


def test_runner_kernel_aborted_without_markers_is_solver_failed(tmp_path):
    run = _run_terminal_case(tmp_path, "ABORTED", sta_text="  STEP 1  INCREMENT 2\\n")
    assert run.state.value == "failed"
    assert run.engineering_status == EngineeringStatus.SOLVER_FAILED.value


def test_runner_no_evidence_either_way_is_unknown(tmp_path):
    """Counter-case: kernel reports neither completion nor failure and the logs
    carry no markers (missing/truncated evidence)."""
    run = _run_terminal_case(tmp_path, "RUNNING", sta_text="  STEP 1  INCREMENT 1\\n")
    assert run.state.value == "failed"
    assert run.engineering_status == EngineeringStatus.TERMINAL_UNKNOWN.value


# ------------------------------------------------- public result semantics

def test_failed_run_with_kernel_completed_does_not_report_solver_completed():
    """A kernel COMPLETED claim contradicted by solver logs is UNKNOWN.

    The raw job_status may still carry the kernel's COMPLETED string, but the
    public run view must not translate that into solver success.
    """
    run = AnalysisRun(
        id="RUN-TP3-UNKNOWN",
        model_name="m",
        job_name="j",
        state=AnalysisRunState.FAILED,
        job_status=JobStatus("j", JobState.COMPLETED, "kernel says COMPLETED"),
        engineering_status=EngineeringStatus.TERMINAL_UNKNOWN.value,
    )
    assert run.solver_completed is False
    assert run.to_dict()["solver_completed"] is False
    assert run.to_evidence_package()["solver_status"] == "failed"
    assert run.to_dict()["engineering_status"] == "TERMINAL_UNKNOWN"


def test_solver_failed_run_with_kernel_completed_is_not_solver_completed():
    run = AnalysisRun(
        id="RUN-TP3-ABORTED",
        model_name="m",
        job_name="j",
        state=AnalysisRunState.FAILED,
        job_status=JobStatus("j", JobState.COMPLETED, "kernel says COMPLETED"),
        engineering_status=EngineeringStatus.SOLVER_FAILED.value,
    )
    assert run.solver_completed is False
    assert run.to_evidence_package()["solver_status"] == "failed"


def test_completed_run_still_reports_solver_completed():
    """Counter-case: a genuine completion must not be over-corrected."""
    run = AnalysisRun(
        id="RUN-TP3-COMPLETED",
        model_name="m",
        job_name="j",
        state=AnalysisRunState.COMPLETED,
        job_status=JobStatus("j", JobState.COMPLETED, "THE ANALYSIS HAS COMPLETED SUCCESSFULLY"),
        engineering_status=EngineeringStatus.RESULT_SUSPICIOUS.value,
    )
    assert run.solver_completed is True


def test_acceptance_cannot_remap_unknown_run_to_solver_success():
    """A direct acceptance call must not re-read the kernel COMPLETED string
    after the unified classifier marked the run TERMINAL_UNKNOWN."""
    from abaqus_ai_agent.acceptance import evaluate_production_acceptance

    run = AnalysisRun(
        id="RUN-TP3-UNKNOWN-ACC",
        model_name="m",
        job_name="j",
        state=AnalysisRunState.FAILED,
        job_status=JobStatus("j", JobState.COMPLETED, "kernel says COMPLETED"),
        engineering_status=EngineeringStatus.TERMINAL_UNKNOWN.value,
    )
    decision = evaluate_production_acceptance(analysis_run=run, result_status="completed")
    assert decision.deliverable is False
    assert decision.acceptance_status != "PASS"
    assert any("job_not_completed" in reason for reason in decision.blocked)
