import pytest

from abaqus_ai_agent.contracts.correction import CorrectionPolicy, RepairCandidate
from abaqus_ai_agent.correction import execute_authorized_correction


class Run:
    state = "accepted"
    acceptance_passed = True
    diagnostics = ()


class PendingRun:
    state = "odb_validated"
    acceptance_passed = None
    diagnostics = ()


class FailedRun:
    state = "results_extracted"
    acceptance_passed = False
    diagnostics = ({"reason": "criterion_failed"},)


class Runner:
    def __init__(self, run=None):
        self.calls = []
        self.result = run or Run()

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def candidate():
    return RepairCandidate(
        "add_output", "missing_output_request", {"action": object()}
    )


def test_authorized_correction_requires_acceptance(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "abaqus_ai_agent.actions.runner.execute",
        lambda executor, action: calls.append((executor, action)) or {"ok": True},
    )
    runner = Runner()
    result = execute_authorized_correction(
        "executor", runner, candidate(), "Model-1", "Job-1", confirmed=True
    )
    assert calls
    assert result["attempt"].status == "completed"
    assert result["attempt"].confirmed is True


def test_correction_is_fail_closed_without_confirmation():
    with pytest.raises(PermissionError):
        execute_authorized_correction(
            "executor", Runner(), candidate(), "Model-1", "Job-1", confirmed=False
        )


def test_correction_rejects_disallowed_diagnostic():
    bad = RepairCandidate("fix_solver", "solver_failed", {"action": object()})
    with pytest.raises(ValueError):
        execute_authorized_correction(
            "executor", Runner(), bad, "Model-1", "Job-1", confirmed=True
        )


def test_correction_does_not_retry_beyond_policy():
    with pytest.raises(ValueError):
        execute_authorized_correction(
            "executor", Runner(), candidate(), "Model-1", "Job-1",
            attempt=1, confirmed=True, policy=CorrectionPolicy(max_attempts=1)
        )


def test_failed_repair_does_not_start_analysis(monkeypatch):
    monkeypatch.setattr(
        "abaqus_ai_agent.actions.runner.execute",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("repair failed")),
    )
    runner = Runner()
    result = execute_authorized_correction(
        "executor", runner, candidate(), "Model-1", "Job-1", confirmed=True
    )
    assert result["attempt"].status == "failed"
    assert result["run"] is None
    assert runner.calls == []


def test_correction_does_not_claim_success_without_acceptance(monkeypatch):
    monkeypatch.setattr(
        "abaqus_ai_agent.actions.runner.execute",
        lambda executor, action: {"ok": True},
    )
    pending = execute_authorized_correction(
        "executor", Runner(PendingRun()), candidate(), "Model-1", "Job-1",
        confirmed=True,
    )
    assert pending["attempt"].status == "verification_pending"

    failed = execute_authorized_correction(
        "executor", Runner(FailedRun()), candidate(), "Model-1", "Job-1",
        confirmed=True,
    )
    assert failed["attempt"].status == "failed"
