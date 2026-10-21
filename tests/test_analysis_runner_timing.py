"""AnalysisRunner records T4a/T4b without changing the run it returns.

Scope: the timing hook added around ``jobs.submit``. These tests do not exercise
the production acceptance gate, ODB extraction, or reporting -- those have their
own suites. What is protected here is narrower:

* passing no profiler leaves the run identical to before the hook existed;
* a supplied profiler receives the wait (T4a) and the log-derived solver time
  (T4b) under different keys;
* a missing or unparseable log is recorded as not-measured, never as 0.0;
* a failure inside the timing hook cannot turn a completed job into a failed run.
"""

from __future__ import annotations

import os

import pytest

from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
from abaqus_ai_agent.execution.jobs import JobState
from abaqus_ai_agent.telemetry.phase_profile import (
    PhaseProfiler,
    PhaseStatus,
    PipelinePhase,
)


_HEADER = "Analysis initiated from SIMULIA established products\nAbaqus JOB {job}\nAbaqus 2025\n"
_SOLVER_BLOCK = (
    "Begin Abaqus/Standard Analysis\n"
    "{t0}\n"
    "Run standard.exe\n"
    "{t1}\n"
    "End Abaqus/Standard Analysis\n"
)


class _TimingExecutor:
    """Just enough of an executor for ``AnalysisRunner.run`` to reach submit.

    ``submit`` calls ``execute`` twice: once for ``mdb.jobs[...].submit`` and once,
    via ``wait``, for ``waitForCompletion``. Both must succeed for the run to be
    treated as completed.
    """

    def __init__(self, workdir, job_name, log_text):
        self.workdir = workdir
        self._job_name = job_name
        self.commands = []
        os.makedirs(workdir, exist_ok=True)
        with open(os.path.join(workdir, f"{job_name}.log"), "w", encoding="utf-8") as handle:
            handle.write(log_text)
        with open(os.path.join(workdir, f"{job_name}.sta"), "w", encoding="utf-8") as handle:
            handle.write("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")

    def execute(self, code, timeout=120):
        self.commands.append(code)
        if "waitForCompletion" in code or "status" in code:
            return "COMPLETED"
        return ""

    def snapshot(self):
        return None


def _solver_log(job_name):
    return (
        _HEADER.format(job=job_name)
        + _SOLVER_BLOCK.format(t0="10/21/2026 9:27:53 AM", t1="10/21/2026 9:28:00 AM")
        + f"Abaqus JOB {job_name} COMPLETED\n"
    )


def _run(tmp_path, job_name, log_text, profiler):
    workdir = str(tmp_path / job_name)
    executor = _TimingExecutor(workdir, job_name, log_text)
    runner = AnalysisRunner(executor)
    run = runner.run(
        model_name="M",
        job_name=job_name,
        workdir=workdir,
        require_production=False,
        phase_profiler=profiler,
    )
    return run


def test_no_profiler_leaves_run_unchanged(tmp_path):
    run = _run(tmp_path, "JobPlain", _solver_log("JobPlain"), profiler=None)
    assert run.job_status.state is JobState.COMPLETED


def test_profiler_receives_wait_and_solver_time(tmp_path, monkeypatch):
    profiler = PhaseProfiler(run_id="wired", strict=False)
    _stub_submit(monkeypatch, wait_seconds=12.5)

    run = _run(tmp_path, "JobTimed", _solver_log("JobTimed"), profiler)

    assert run.job_status.state is JobState.COMPLETED
    record = profiler.finalize().get(PipelinePhase.SOLVER)
    assert record.status is PhaseStatus.MEASURED
    assert record.duration_s == pytest.approx(12.5)
    assert record.detail["scope"] == "wait"
    assert record.detail["t4b"]["solver_seconds"] == pytest.approx(7.0)
    assert record.detail["t4b"]["scope"] == "solver_only"
    # The two numbers answer different questions and must not collapse into one.
    assert record.duration_s != record.detail["t4b"]["solver_seconds"]


def test_unparseable_log_is_not_measured_as_zero(tmp_path, monkeypatch):
    profiler = PhaseProfiler(run_id="nolog", strict=False)
    _stub_submit(monkeypatch, wait_seconds=8.0)

    run = _run(tmp_path, "JobNoLog", "this is not an abaqus log\n", profiler)

    assert run.job_status.state is JobState.COMPLETED
    record = profiler.finalize().get(PipelinePhase.SOLVER)
    assert record.duration_s == pytest.approx(8.0)  # T4a still recorded
    assert record.detail["t4b"]["solver_seconds"] is None
    assert record.detail["t4b"]["measured"] is False


def test_timing_failure_does_not_fail_the_run(tmp_path, monkeypatch):
    """A clock that fails after submit must not fail the job."""
    profiler = PhaseProfiler(run_id="broken", strict=False)
    calls = {"n": 0}
    real = time_module().monotonic

    def _clock():
        calls["n"] += 1
        # The first call is the one before submit; the second is the one after,
        # and that is the one allowed to fail without sinking the run.
        if calls["n"] >= 2:
            raise RuntimeError("clock unavailable")
        return real()

    monkeypatch.setattr(time_module(), "monotonic", _clock)
    run = _run(tmp_path, "JobBroken", _solver_log("JobBroken"), profiler)

    assert run.job_status.state is JobState.COMPLETED
    assert any("clock unavailable" in note for note in profiler.internal_errors)


def _stub_submit(monkeypatch, wait_seconds):
    """Replace ``_submit_and_time`` with one that reports a fixed wait.

    The real function reads ``time.monotonic``, which ``run()`` also calls for
    unrelated reasons. Stubbing here tests the recording contract directly
    instead of depending on how many times the clock happens to be read.
    """
    import abaqus_ai_agent.execution.analysis_run as mod
    from abaqus_ai_agent.execution.jobs import JobState, JobStatus

    def _fake(jobs, job_name, timeout, profiler):
        status = jobs.submit(job_name, wait=True, timeout=timeout)
        return status, (wait_seconds if profiler is not None else None)

    monkeypatch.setattr(mod, "_submit_and_time", _fake)
    return JobStatus, JobState


def time_module():
    import abaqus_ai_agent.execution.analysis_run as mod
    return mod.time
