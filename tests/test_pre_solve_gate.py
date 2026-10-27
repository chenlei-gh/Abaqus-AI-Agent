"""Integration tests for the pre-solve approval gate at the submission points.

These cover the gate wiring (plan step 3) with fake executors: the gate must
block every unapproved production submission, admit exactly the approved
content version, and fail closed again when content drifts after approval.
"""

import json
from pathlib import Path

import pytest

from abaqus_ai_agent.contracts.approval import (
    CandidateStatus,
    ExecutionCandidate,
    load_candidate,
)
from abaqus_ai_agent.execution.analysis_run import AnalysisRunState, AnalysisRunner
from abaqus_ai_agent.execution.approval_service import (
    PreSolveApprovalRequired,
    approve_current_candidate,
)

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _production_policy_env(monkeypatch):
    monkeypatch.delenv("ABAQUS_AGENT_TEST_MODE", raising=False)
    monkeypatch.delenv("ABAQUS_AI_AGENT_APPROVAL", raising=False)


DECK_V1 = "*Heading\n*Node\n1, 0., 0., 0.\n"
DECK_V2 = "*Heading\n*Node\n1, 0., 0., 1.\n"


class RecordingExecutor:
    """Executor stand-in with a production-looking class name.

    The name deliberately avoids Mock/Fake/Stub/Dummy so the approval policy
    resolver treats it as a real executor and the gate engages.
    """

    def __init__(self):
        self.workdir = None
        self.commands = []

    def snapshot(self):
        return None

    def execute(self, code, timeout=120):
        self.commands.append(code)
        return ""


def _plant_deck(workdir: Path, job_name: str, text: str = DECK_V1):
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / f"{job_name}.inp").write_text(text, encoding="utf-8")


def _run(runner, workdir, job_name, policy):
    return runner.run(
        model_name="Model-Gate",
        job_name=job_name,
        result_values={"max_stress": 120.0},
        workdir=str(workdir),
        require_production=False,
        approval_policy=policy,
    )


def test_runner_blocks_unapproved_submission(tmp_path):
    executor = RecordingExecutor()
    _plant_deck(tmp_path, "Job-Gate")

    run = _run(AnalysisRunner(executor), tmp_path, "Job-Gate", "required")

    assert run.state == AnalysisRunState.FAILED
    assert run.engineering_status == "SUBMISSION_BLOCKED"
    diag = run.diagnostics[0]
    assert diag["pre_solve_approval_required"] is True
    assert diag["candidate_status"] == "PROPOSED"
    # No submission command ever reached the executor.
    assert not any(".submit(" in cmd for cmd in executor.commands)
    # Phase A artifacts exist: candidate record and review report.
    candidate = load_candidate(tmp_path)
    assert candidate is not None and candidate.status is CandidateStatus.PROPOSED
    report = tmp_path / "pre_solve_review.html"
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "PRE-SOLVE REVIEW" in text
    assert candidate.execution_manifest_hash in text


def test_runner_admits_exact_approved_version(tmp_path, monkeypatch):
    from abaqus_ai_agent.execution import jobs as jobs_module

    executor = RecordingExecutor()
    _plant_deck(tmp_path, "Job-Gate")
    runner = AnalysisRunner(executor)

    blocked = _run(runner, tmp_path, "Job-Gate", "required")
    assert blocked.diagnostics[0]["pre_solve_approval_required"] is True

    approved = approve_current_candidate(tmp_path, approved_by="tester")
    assert approved.approval.review_report_hash  # bound to the review HTML

    submitted = []

    def fake_submit(self, name, wait=False, timeout=3600):
        submitted.append(name)
        return jobs_module.JobStatus(name, jobs_module.JobState.COMPLETED, None)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(jobs_module.JobController, "submit", fake_submit)
    try:
        run = _run(runner, tmp_path, "Job-Gate", "required")
    finally:
        monkeypatch.undo()

    assert submitted == ["Job-Gate"], "the approved candidate must reach submission"
    assert not any(
        isinstance(d, dict) and d.get("pre_solve_approval_required")
        for d in (run.diagnostics or ())
    )


def test_drift_after_approval_blocks_and_supersedes(tmp_path):
    executor = RecordingExecutor()
    _plant_deck(tmp_path, "Job-Gate")
    runner = AnalysisRunner(executor)

    _run(runner, tmp_path, "Job-Gate", "required")
    approved = approve_current_candidate(tmp_path, approved_by="tester")

    # Content changes after approval: the old approval must not transfer.
    _plant_deck(tmp_path, "Job-Gate", DECK_V2)
    blocked = _run(runner, tmp_path, "Job-Gate", "required")

    assert blocked.diagnostics[0]["pre_solve_approval_required"] is True
    current = load_candidate(tmp_path)
    assert current.status is CandidateStatus.PROPOSED
    assert current.candidate_id != approved.candidate_id
    assert not any(".submit(" in cmd for cmd in executor.commands)
    archive = tmp_path / f"execution_candidate.{approved.candidate_id}.json"
    assert archive.is_file()
    archived = ExecutionCandidate.from_dict(json.loads(archive.read_text(encoding="utf-8")))
    assert archived.status is CandidateStatus.SUPERSEDED
    assert archived.superseded_by == current.candidate_id


def test_policy_disabled_never_creates_candidate(tmp_path, monkeypatch):
    from abaqus_ai_agent.execution import jobs as jobs_module

    executor = RecordingExecutor()
    _plant_deck(tmp_path, "Job-Gate")

    def fake_submit(self, name, wait=False, timeout=3600):
        return jobs_module.JobStatus(name, jobs_module.JobState.COMPLETED, None)

    monkeypatch.setattr(jobs_module.JobController, "submit", fake_submit)
    _run(AnalysisRunner(executor), tmp_path, "Job-Gate", "disabled")
    assert load_candidate(tmp_path) is None


# --- user-INP batch path (S3) -------------------------------------------------


class RecordingBatchRunner:
    """Batch-style executor (run_input interface), production-looking name."""

    def __init__(self):
        self.workdir = None
        self.calls = []

    def run_input(self, input_path, job_name=None, timeout=None, **kwargs):
        self.calls.append((input_path, job_name))
        raise RuntimeError("sentinel: reached submission")


def test_user_inp_path_blocks_before_submission(tmp_path):
    from abaqus_ai_agent.execution.input_modes import solve_user_inp

    inp = tmp_path / "user_case.inp"
    inp.write_text(DECK_V1, encoding="utf-8")
    executor = RecordingBatchRunner()

    with pytest.raises(PreSolveApprovalRequired):
        solve_user_inp(executor, inp)
    assert executor.calls == []
    candidate = load_candidate(tmp_path)
    assert candidate is not None and candidate.status is CandidateStatus.PROPOSED


def test_user_inp_path_admits_after_approval(tmp_path):
    from abaqus_ai_agent.execution.input_modes import solve_user_inp

    inp = tmp_path / "user_case.inp"
    inp.write_text(DECK_V1, encoding="utf-8")
    executor = RecordingBatchRunner()

    with pytest.raises(PreSolveApprovalRequired):
        solve_user_inp(executor, inp)
    approve_current_candidate(tmp_path, approved_by="tester")

    # solve_user_inp captures executor failures into its result dict, so the
    # proof of admission is that the batch submission was actually invoked.
    solve_user_inp(executor, inp)
    assert executor.calls, "approved candidate must reach the batch submission"


# --- bare agent.submit (E4) -----------------------------------------------------


def test_agent_submit_passes_through_gate(tmp_path):
    from abaqus_ai_agent.agent import AbaqusAIAgent

    executor = RecordingExecutor()
    executor.workdir = str(tmp_path)
    _plant_deck(tmp_path, "Job-Bare")
    agent = AbaqusAIAgent(executor=executor)

    with pytest.raises(PreSolveApprovalRequired):
        agent.submit("Job-Bare")
    assert not any(".submit(" in cmd for cmd in executor.commands)

    approve_current_candidate(tmp_path, approved_by="tester")
    status = agent.submit("Job-Bare")
    assert any(".submit(" in cmd for cmd in executor.commands)
    assert status.state.value == "SUBMITTED"
# --- solve_requirement Phase A report (E1 product entry) -----------------------


def test_solve_requirement_phase_a_returns_review_report(tmp_path, monkeypatch):
    """The product entry must surface AWAITING_APPROVAL with a review report."""
    from unittest.mock import MagicMock

    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.approval import propose_candidate, write_candidate
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import (
        IntentBoundarySpec,
        IntentGeometrySpec,
        IntentLoadSpec,
    )
    from abaqus_ai_agent.contracts.task import TaskStatus
    from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState

    candidate = propose_candidate(
        candidate_id="Job-PhaseA-abcdef123456",
        run_id="run-phase-a",
        inp_sha256="a" * 64,
        solver_config={"solver": "STANDARD", "strategy": "static"},
        generator_version="test",
    )
    write_candidate(tmp_path, candidate)

    blocked_run = MagicMock(spec=AnalysisRun)
    blocked_run.state = AnalysisRunState.FAILED
    blocked_run.engineering_status = "SUBMISSION_BLOCKED"
    blocked_run.acceptance_passed = False
    blocked_run.metadata = {}
    blocked_run.diagnostics = ({
        "pre_solve_approval_required": True,
        "candidate_id": candidate.candidate_id,
        "execution_manifest_hash": candidate.execution_manifest_hash,
        "workdir": str(tmp_path),
        "review_report": str(tmp_path / "pre_solve_review.html"),
        "error": "solver submission blocked: awaiting approval",
    },)
    monkeypatch.setattr(
        AbaqusAIAgent, "analysis_run", lambda self, *a, **k: blocked_run
    )

    from abaqus_ai_agent.execution.client import AbaqusExecutor

    class PhaseAExecutor(AbaqusExecutor):
        _is_mock = True

        def snapshot(self):
            return None

        def execute(self, code, timeout=120):
            return ""

    agent = AbaqusAIAgent(executor=PhaseAExecutor())
    intent = EngineeringIntent(
        id="intent-phase-a",
        kind="linear_static",
        description="Cantilever Phase A",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "Steel", "youngs_modulus": 210000.0, "poisson_ratio": 0.3},
        metadata={"geometry": IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)},
        boundary_conditions=(IntentBoundarySpec(name="FixedRoot", bc_type="ENCASTRE", region="RootFace"),),
        loads=(IntentLoadSpec(name="TipLoad", load_type="concentrated_force", region="TipFace", magnitude=-1000.0),),
    )

    res = agent.solve_requirement(intent)

    assert res.status == TaskStatus.BLOCKED
    assert res.summary_card["status"] == "AWAITING_APPROVAL"
    assert res.summary_card["candidate_id"] == candidate.candidate_id
    report = tmp_path / "pre_solve_review.html"
    assert report.is_file()
    html_text = report.read_text(encoding="utf-8")
    assert "PRE-SOLVE REVIEW" in html_text
    assert candidate.execution_manifest_hash in html_text
    # Rich sections from the product entry (not just the runner fallback).
    assert "Model &amp; mesh" in html_text
    assert "FixedRoot" in html_text
    assert "TipLoad" in html_text
# --- duplicate-submission guard (crash window between submit and ledger write) ---


def _write_ledger(workdir: Path, job_name: str, phase: str, pid: int):
    from abaqus_ai_agent.execution.reconciliation import (
        RunSnapshot,
        default_ledger_path,
        write_snapshot,
    )

    write_snapshot(
        RunSnapshot(
            task_id="prior-run",
            run_id="prior-run",
            phase=phase,
            job_name=job_name,
            sandbox_dir=str(workdir),
            pid=pid,
        ),
        default_ledger_path(workdir),
    )
    return default_ledger_path(workdir)


def test_live_prior_submission_blocks_resubmit(tmp_path):
    """A ledger claiming a live solve must stop a blind resubmission."""
    import os

    executor = RecordingExecutor()
    _plant_deck(tmp_path, "Job-Gate")
    ledger = _write_ledger(tmp_path, "Job-Gate", "SOLVING", pid=os.getpid())

    run = _run(AnalysisRunner(executor), tmp_path, "Job-Gate", "required")

    assert run.engineering_status == "SUBMISSION_BLOCKED"
    diag = run.diagnostics[0]
    assert diag["duplicate_submission_blocked"] is True
    assert diag["reconciliation_action"] == "reconnect_live"
    assert not any(".submit(" in cmd for cmd in executor.commands)
    # The prior ledger is evidence of the live submission: it must survive.
    from abaqus_ai_agent.execution.reconciliation import load_snapshot

    assert load_snapshot(ledger).phase == "SOLVING"


def test_dead_prior_submission_allows_resubmit(tmp_path):
    """A crashed solve (dead pid, no lock, no ODB) reconciles to resubmit."""
    executor = RecordingExecutor()
    _plant_deck(tmp_path, "Job-Gate")
    # pid 2**22-3 is essentially never a live process on the test host.
    _write_ledger(tmp_path, "Job-Gate", "SOLVING", pid=4194301)

    run = _run(AnalysisRunner(executor), tmp_path, "Job-Gate", "required")

    # The duplicate-submission guard passed; the run must now stop at the
    # approval gate instead.
    diag = run.diagnostics[0]
    assert diag.get("pre_solve_approval_required") is True
    assert not diag.get("duplicate_submission_blocked")
