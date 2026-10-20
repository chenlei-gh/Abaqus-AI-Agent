"""End-to-end wiring tests for the life-cycle ledger written by AnalysisRunner.

The reconciliation primitives are covered in test_run_reconciliation.py; these
tests assert that a real run actually leaves a usable ledger behind, because a
snapshot API nobody calls would satisfy the unit tests while leaving cross-session
resumption broken.
"""

from pathlib import Path

import pytest

from abaqus_ai_agent.execution.analysis_run import AnalysisRunState, AnalysisRunner
from abaqus_ai_agent.execution.reconciliation import (
    ReconciliationAction,
    default_ledger_path,
    load_snapshot,
    resume_from_ledger,
)


class _PassingExecutor:
    """Executor stub whose job reports COMPLETED without a real solver."""

    def __init__(self):
        self.workdir = None
        self.commands = []

    def snapshot(self):
        return None

    def execute(self, code, timeout=120):
        self.commands.append(code)
        return ""


def _run_with_stub(monkeypatch, workdir: Path, job_name: str):
    """Run AnalysisRunner against a stubbed job controller that completes cleanly."""
    from abaqus_ai_agent.execution import jobs as jobs_module

    runner = AnalysisRunner(_PassingExecutor())

    # The ledger is written against the resolved workdir, which the runner may
    # relocate; pin it explicitly so the assertion target is unambiguous.
    def fake_submit(self, name, wait=False, timeout=3600):
        return jobs_module.JobStatus(name, jobs_module.JobState.COMPLETED, None)

    monkeypatch.setattr(jobs_module.JobController, "submit", fake_submit)

    return runner.run(
        model_name="Model-Ledger",
        job_name=job_name,
        result_values={"max_stress": 120.0},
        workdir=str(workdir),
        require_production=False,
    )


def test_runner_persists_ledger_and_it_is_resumable(tmp_path, monkeypatch):
    """A completed run leaves .state/run_lifecycle.json and it can be resumed."""
    monkeypatch.setenv("ABAQUS_AGENT_TEST_MODE", "1")
    workdir = tmp_path / "solver"
    workdir.mkdir()

    run = _run_with_stub(monkeypatch, workdir, "Job-Ledger")

    assert run.state == AnalysisRunState.FAILED

    ledger = default_ledger_path(workdir)
    assert ledger.is_file(), f"ledger was not written at {ledger}"

    snapshot = load_snapshot(ledger)
    assert snapshot is not None
    assert snapshot.job_name == "Job-Ledger"
    assert snapshot.run_id
    # The stub produces no ODB, so the run must end FAILED rather than claiming
    # a completion the artifacts do not support.
    assert snapshot.phase == "FAILED"

    # The ledger must route back to the physical workdir it describes.
    assert Path(snapshot.sandbox_dir).resolve() == workdir.resolve()

    report = resume_from_ledger(ledger, allow_git_drift=True)
    assert report.action in set(ReconciliationAction)
    assert report.snapshot is not None
    assert report.snapshot.run_id == snapshot.run_id


def test_ledger_write_failure_never_breaks_execution(tmp_path, monkeypatch):
    """A read-only workspace must not turn a healthy solve into a failure."""
    monkeypatch.setenv("ABAQUS_AGENT_TEST_MODE", "1")
    workdir = tmp_path / "solver"
    workdir.mkdir()

    def explode(*args, **kwargs):
        raise OSError("simulated read-only workspace")

    monkeypatch.setattr(
        "abaqus_ai_agent.execution.reconciliation.write_snapshot", explode
    )

    run = _run_with_stub(monkeypatch, workdir, "Job-NoLedger")

    # Execution outcome must be unaffected by the snapshot failure.
    assert run.id
    assert not default_ledger_path(workdir).exists()
