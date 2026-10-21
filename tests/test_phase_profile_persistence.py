"""Production entry persists T4 without changing the run it returns.

These tests cover the wiring the optional ``phase_profiler`` argument does not:
``AbaqusAIAgent.analysis_run`` creates the profiler, ``AnalysisRunner.run`` writes
T4a/T4b into it, and the agent finalizes that profile into the evidence directory
the run already owns.

What they do not prove: a real Abaqus job produced these numbers, T1/T2/T3/T5/T6
were measured, or the persisted file has been read back by a later production step.
"""

from __future__ import annotations

import json
import os

import pytest

from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.execution.jobs import JobState
from abaqus_ai_agent.paths import create_external_project_context


_HEADER = "Analysis initiated from SIMULIA established products\nAbaqus JOB {job}\nAbaqus 2025\n"
_SOLVER_BLOCK = (
    "Begin Abaqus/Standard Analysis\n"
    "{t0}\n"
    "Run standard.exe\n"
    "{t1}\n"
    "End Abaqus/Standard Analysis\n"
)


class _PersistExecutor:
    """Enough of an executor for ``analysis_run`` to reach submit and return."""

    def __init__(self, job_name, log_text):
        self.job_name = job_name
        self.log_text = log_text
        self.workdir = None
        self.commands = []

    def execute(self, code, timeout=120):
        self.commands.append(code)
        if self.workdir and "waitForCompletion" in code:
            os.makedirs(self.workdir, exist_ok=True)
            with open(os.path.join(self.workdir, f"{self.job_name}.log"), "w", encoding="utf-8") as handle:
                handle.write(self.log_text)
            with open(os.path.join(self.workdir, f"{self.job_name}.sta"), "w", encoding="utf-8") as handle:
                handle.write("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")
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


def _agent(job_name, log_text=None):
    return AbaqusAIAgent(_PersistExecutor(job_name, log_text if log_text is not None else _solver_log(job_name)))


def _stub_submit(monkeypatch, wait_seconds):
    import abaqus_ai_agent.execution.analysis_run as mod

    def _fake(jobs, job_name, timeout, profiler):
        status = jobs.submit(job_name, wait=True, timeout=timeout)
        return status, (wait_seconds if profiler is not None else None)

    monkeypatch.setattr(mod, "_submit_and_time", _fake)


def _profile_path(run):
    evidence = run.provenance.environment["evidence_dir"]
    return os.path.join(evidence, "phase_profile.json")


def test_production_entry_persists_t4_into_the_runs_evidence_dir(tmp_path, monkeypatch):
    ctx = create_external_project_context(tmp_path / "customer", enforce_outside_repo=False)
    _stub_submit(monkeypatch, wait_seconds=12.5)
    agent = _agent("JobPersist")

    run = agent.analysis_run(
        model_name="M",
        job_name="JobPersist",
        project_context=ctx,
        require_production=False,
    )

    assert run.job_status.state is JobState.COMPLETED
    target = _profile_path(run)
    assert os.path.isfile(target)
    # The job name is a different identifier. Writing there would split one run's
    # evidence across two directories and leave the recorded evidence_dir empty.
    assert not (ctx.evidence_dir / "JobPersist" / "phase_profile.json").exists()
    assert not (ctx.evidence_dir / ".phase_profile.json.tmp").exists()

    with open(target, encoding="utf-8") as handle:
        payload = json.loads(handle.read())
    assert payload["schema"] == "phase_profile_v1"
    assert payload["run_id"] == run.id
    solver = next(phase for phase in payload["phases"] if phase["phase"] == "T4_solver")
    assert solver["status"] == "measured"
    assert solver["duration_s"] == pytest.approx(12.5)
    assert solver["detail"]["scope"] == "wait"
    assert solver["detail"]["t4b"]["solver_seconds"] == pytest.approx(7.0)
    assert solver["detail"]["t4b"]["scope"] == "solver_only"
    assert solver["duration_s"] != solver["detail"]["t4b"]["solver_seconds"]
    not_run = set(payload["not_run"])
    assert {
        "T1_cad_parsing",
        "T2_mesh_compilation",
        "T3_license_queue",
        "T5_data_extraction",
        "T6_report_generation",
    } <= not_run


def test_missing_project_context_does_not_persist_or_fail(tmp_path, monkeypatch):
    _stub_submit(monkeypatch, wait_seconds=4.0)
    agent = _agent("JobNoCtx")

    run = agent.analysis_run(
        model_name="M",
        job_name="JobNoCtx",
        workdir=str(tmp_path / "scratch"),
        require_production=False,
    )

    assert run.job_status.state is JobState.COMPLETED
    assert run.provenance.environment.get("evidence_dir") is None
    assert not list((tmp_path / "scratch").glob("phase_profile.json"))


def test_finalize_failure_does_not_change_the_run(tmp_path, monkeypatch):
    ctx = create_external_project_context(tmp_path / "customer", enforce_outside_repo=False)
    _stub_submit(monkeypatch, wait_seconds=3.0)

    def _boom(self):
        raise RuntimeError("finalize refused")

    monkeypatch.setattr(
        "abaqus_ai_agent.telemetry.phase_profile.PhaseProfiler.finalize",
        _boom,
    )
    agent = _agent("JobFinalize")

    run = agent.analysis_run(
        model_name="M",
        job_name="JobFinalize",
        project_context=ctx,
        require_production=False,
    )

    assert run.job_status.state is JobState.COMPLETED
    assert not os.path.exists(_profile_path(run))


def test_unwritable_evidence_dir_does_not_change_the_run(tmp_path, monkeypatch):
    ctx = create_external_project_context(tmp_path / "customer", enforce_outside_repo=False)
    _stub_submit(monkeypatch, wait_seconds=3.0)
    real_replace = os.replace

    def _refuse(src, dst):
        if str(dst).endswith("phase_profile.json"):
            raise PermissionError("evidence dir is read-only")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _refuse)
    agent = _agent("JobLocked")

    run = agent.analysis_run(
        model_name="M",
        job_name="JobLocked",
        project_context=ctx,
        require_production=False,
    )

    assert run.job_status.state is JobState.COMPLETED
    assert not os.path.exists(_profile_path(run))
    assert not os.path.exists(os.path.join(run.provenance.environment["evidence_dir"], ".phase_profile.json.tmp"))


def test_direct_runner_without_profiler_writes_no_profile(tmp_path):
    """Callers that bypass the agent entry must not grow a profile as a side effect."""
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

    ctx = create_external_project_context(tmp_path / "customer", enforce_outside_repo=False)
    executor = _PersistExecutor("JobDirect", _solver_log("JobDirect"))
    run = AnalysisRunner(executor).run(
        model_name="M",
        job_name="JobDirect",
        project_context=ctx,
        require_production=False,
    )

    assert run.job_status.state is JobState.COMPLETED
    assert not os.path.exists(_profile_path(run))
