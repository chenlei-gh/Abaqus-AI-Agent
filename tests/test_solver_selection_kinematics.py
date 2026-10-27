"""Tests for T-P1: kinematic evidence tiers in solver selection.

Frozen contracts under test:
- D2: a user-chosen solver conflicting with a declared kinematic requirement
  blocks submission with structured reasons; the solver is never switched
  silently, and a hard block is not a pending confirmation.
- D3: keyword-only separation cues trigger review; they never force a solver
  switch or a hard block on their own.
- separation_required=True alone never forces Explicit.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.solver_selection import (
    SolverSelection,
    SolverSelectionBlocked,
    select_solver,
)
from abaqus_ai_agent.contracts.task import TaskStatus
from abaqus_ai_agent.execution.client import AbaqusExecutor
from abaqus_ai_agent.validation.condition_fidelity import kinematic_evidence


def _intent(description="static bracket", analysis_type="static", metadata=None):
    return EngineeringIntent("REQ-TP1", "structural", description,
                             analysis_type=analysis_type, metadata=metadata or {})


# ---------------------------------------------------------------- evidence tiers

def test_kinematic_evidence_separates_declared_from_keyword():
    declared = kinematic_evidence(_intent(metadata={"separation_required": True}))
    assert declared["separation"]["declared"] is True
    assert declared["separation"]["keyword"] is False
    assert any("separation_required" in s for s in declared["separation"]["evidence"])

    keyword = kinematic_evidence(_intent(description="snap-fit unclip force"))
    assert keyword["separation"]["declared"] is False
    assert keyword["separation"]["keyword"] is True

    contact_declared = kinematic_evidence(
        _intent(), contacts=({"expected_state": "open"},))
    assert contact_declared["separation"]["declared"] is True


# ---------------------------------------------------------------- decision rules

def test_declared_separation_with_user_standard_is_hard_blocked():
    """D2 core: user-chosen Standard + declared separation -> blocked record."""
    sel = select_solver(_intent(metadata={"solver": "standard", "separation_required": True}))
    assert sel.blocked is True
    assert sel.blocking_reasons
    assert "user_solver_conflicts_with_declared_separation_requirement" in sel.blocking_reasons[0]
    assert "separation_required" in sel.blocking_reasons[0]
    # A hard block is a refusal, not a pending confirmation.
    assert sel.requires_user_confirmation is False
    # The refused solver stays on the record; it is not switched silently.
    assert sel.solver == "STANDARD"


def test_dynamic_implicit_analysis_type_counts_as_user_standard():
    """analysis_type=dynamic-implicit is itself a user Standard declaration."""
    sel = select_solver(_intent(analysis_type="dynamic_implicit",
                                metadata={"separation_required": True}))
    assert sel.blocked is True
    assert sel.blocking_reasons


def test_declared_separation_alone_never_forces_explicit():
    """Hard constraint: separation_required=True is not an Explicit mandate."""
    sel = select_solver(_intent(metadata={"separation_required": True}))
    assert sel.blocked is False
    assert sel.solver == "STANDARD"
    assert sel.strategy == "STATIC_GENERAL"
    assert sel.requires_user_confirmation is True
    assert any("separation" in w for w in sel.warnings)


def test_keyword_only_separation_never_blocks_user_standard():
    """D3: keyword-only cues trigger review, not a hard block."""
    sel = select_solver(_intent(description="snap-fit unclip force",
                                metadata={"solver": "standard"}))
    assert sel.blocked is False
    assert sel.solver == "STANDARD"
    assert sel.requires_user_confirmation is True
    assert any("keyword-inferred" in w for w in sel.warnings)


def test_keyword_only_separation_keeps_default_standard_with_review():
    """Amended contract (2026-10): a keyword event cue such as snap-fit /
    pull-out / slip-out no longer leaves an unspecified solver choice at
    Standard. It steers the selection to the Explicit quasi-static procedure,
    which always carries requires_user_confirmation=True, so the switch is
    never silent. D3 still holds for user-declared solvers: keyword cues can
    neither override nor block them (see the neighbouring tests)."""
    sel = select_solver(_intent(description="snap-fit unclip force"))
    assert sel.blocked is False
    assert sel.solver == "EXPLICIT"
    assert sel.strategy == "QUASI_STATIC_EXPLICIT"
    assert sel.requires_user_confirmation is True


def test_declared_separation_with_user_explicit_proceeds():
    sel = select_solver(_intent(metadata={"solver": "explicit", "separation_required": True}))
    assert sel.blocked is False
    assert sel.solver == "EXPLICIT"
    assert any("separation" in r for r in sel.reasons)


def test_plain_static_selection_is_unchanged():
    sel = select_solver(_intent())
    assert sel.solver == "STANDARD" and sel.strategy == "STATIC_GENERAL"
    assert sel.blocked is False
    assert sel.requires_user_confirmation is False
    assert sel.confidence == "high"
    assert sel.warnings == ()


# ---------------------------------------------------------------- record contract

def test_blocked_record_requires_reasons_and_excludes_confirmation():
    with pytest.raises(ValueError):
        SolverSelection("STANDARD", "static", "BLOCKED", blocked=True)
    with pytest.raises(ValueError):
        SolverSelection("STANDARD", "static", "STATIC_GENERAL",
                        blocking_reasons=("orphan reason",))
    with pytest.raises(ValueError):
        SolverSelection("STANDARD", "static", "BLOCKED", blocked=True,
                        blocking_reasons=("x",), requires_user_confirmation=True)


def test_solver_selection_blocked_carries_the_record():
    sel = select_solver(_intent(metadata={"solver": "standard", "separation_required": True}))
    err = SolverSelectionBlocked(sel)
    assert err.selection is sel
    assert "user_solver_conflicts" in str(err)


# ---------------------------------------------------------------- execution gate

def _runner(tmp_path):
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
    workdir = tmp_path / "tp1_run"
    workdir.mkdir(exist_ok=True)
    executor = MagicMock()
    executor.workdir = str(workdir)
    executor.is_test_mode = True
    executor.execute = MagicMock(return_value="")
    return AnalysisRunner(executor=executor), str(workdir)


def test_submission_gate_blocks_conflicting_run_before_submit(tmp_path, monkeypatch):
    """The gate fires before jobs.submit; the run is FAILED/SUBMISSION_BLOCKED."""
    from abaqus_ai_agent.execution.jobs import JobController
    runner, workdir = _runner(tmp_path)
    mock_submit = MagicMock()
    monkeypatch.setattr(JobController, "submit", mock_submit)

    run = runner.run(model_name="M", job_name="Job_TP1", workdir=workdir,
                     engineering_intent=_intent(metadata={"solver": "standard",
                                                          "separation_required": True}))

    assert run.state.value == "failed"
    assert run.engineering_status == "SUBMISSION_BLOCKED"
    assert mock_submit.call_count == 0
    blocking = [d for d in run.diagnostics
                if isinstance(d, dict) and d.get("solver_selection_blocked")]
    assert blocking, "structured blocking diagnostic missing"
    assert any("user_solver_conflicts" in r for r in blocking[0]["blocking_reasons"])


def test_gate_enforces_blocked_record_even_if_upstream_bypassed(tmp_path, monkeypatch):
    """Defence: whatever the record says is enforced, even if selection is replaced."""
    from abaqus_ai_agent.execution.jobs import JobController
    import abaqus_ai_agent.contracts.solver_selection as sel_mod
    runner, workdir = _runner(tmp_path)
    mock_submit = MagicMock()
    monkeypatch.setattr(JobController, "submit", mock_submit)

    fabricated = SolverSelection("STANDARD", "static", "BLOCKED", blocked=True,
                                 blocking_reasons=("fabricated_conflict_for_bypass_test",))
    monkeypatch.setattr(sel_mod, "select_solver", lambda intent: fabricated)

    run = runner.run(model_name="M", job_name="Job_TP1_BYPASS", workdir=workdir,
                     engineering_intent=_intent())

    assert run.engineering_status == "SUBMISSION_BLOCKED"
    assert mock_submit.call_count == 0


def test_unconflicted_intent_passes_the_gate(tmp_path, monkeypatch):
    from abaqus_ai_agent.execution.jobs import JobController, JobState, JobStatus
    runner, workdir = _runner(tmp_path)
    job_name = "Job_TP1_OK"
    mock_submit = MagicMock(return_value=JobStatus(job_name, JobState.COMPLETED, {}))
    monkeypatch.setattr(JobController, "submit", mock_submit)

    run = runner.run(model_name="M", job_name=job_name, workdir=workdir,
                     engineering_intent=_intent(metadata={"separation_required": True}))

    assert run.engineering_status != "SUBMISSION_BLOCKED"
    assert mock_submit.call_count == 1


# ---------------------------------------------------------------- agent level

class _MockRunExecutor(AbaqusExecutor):
    def __init__(self):
        self.workdir = None

    def execute(self, code, timeout=120):
        return {"status": "COMPLETED", "output": "COMPLETED"}

    def monitor_job(self, name, timeout=3600, poll_seconds=2.0):
        return {"status": "COMPLETED", "output": "COMPLETED"}

    def snapshot(self):
        return None


def test_agent_blocked_run_never_enters_self_healing(monkeypatch):
    """A policy block is not a solver failure: the healing chain must stay out."""
    from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
    from abaqus_ai_agent.diagnostics import orchestrator as orch_mod
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec
    healing_calls = []
    monkeypatch.setattr(orch_mod.SelfHealingOrchestrator, "attempt_healing",
                        lambda *a, **k: healing_calls.append((a, k)))

    agent = AbaqusAIAgent(_MockRunExecutor())
    result = agent.solve_requirement(
        requirement=_intent(description="static clip housing check",
                            metadata={"solver": "standard", "separation_required": True}),
        geometry=IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0),
        material=MaterialDefinition(
            name="Steel_Q235", unit_system="MM_N_MPA",
            elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
            density=7.85e-9,
        ),
    )

    assert healing_calls == []
    assert result.status == TaskStatus.FAILED
    assert result.summary_card["engineering_status"] == "SUBMISSION_BLOCKED"
