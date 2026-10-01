import pytest

from abaqus_ai_agent.contracts.correction import CorrectionPolicy, RepairCandidate
from abaqus_ai_agent.correction import execute_authorized_correction


class Run:
    state = "accepted"
    diagnostics = ()


class Runner:
    def __init__(self):
        self.calls = []

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return Run()


def test_authorized_correction_executes_existing_action_then_analysis_runner(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "abaqus_ai_agent.actions.runner.execute",
        lambda executor, action: calls.append((executor, action)) or {"ok": True},
    )
    action = object()
    candidate = RepairCandidate(
        "add_output", "missing_output_request", {"action": action}
    )
    runner = Runner()
    result = execute_authorized_correction(
        "executor", runner, candidate, "Model-1", "Job-1", confirmed=True
    )
    assert calls == [("executor", action)]
    assert runner.calls == [(("Model-1", "Job-1"), {})]
    assert result["attempt"].status == "completed"
    assert result["attempt"].confirmed is True


def test_correction_is_fail_closed_without_confirmation():
    candidate = RepairCandidate(
        "add_output", "missing_output_request", {"action": object()}
    )
    with pytest.raises(PermissionError):
        execute_authorized_correction(
            "executor", Runner(), candidate, "Model-1", "Job-1", confirmed=False
        )


def test_correction_rejects_disallowed_diagnostic():
    candidate = RepairCandidate(
        "fix_solver", "solver_failed", {"action": object()}
    )
    with pytest.raises(ValueError):
        execute_authorized_correction(
            "executor", Runner(), candidate, "Model-1", "Job-1", confirmed=True
        )


def test_correction_does_not_retry_beyond_policy():
    candidate = RepairCandidate(
        "add_output", "missing_output_request", {"action": object()}
    )
    with pytest.raises(ValueError):
        execute_authorized_correction(
            "executor", Runner(), candidate, "Model-1", "Job-1",
            attempt=1, confirmed=True, policy=CorrectionPolicy(max_attempts=1)
        )


def test_failed_repair_does_not_start_analysis(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("repair failed")
    monkeypatch.setattr("abaqus_ai_agent.actions.runner.execute", fail)
    candidate = RepairCandidate(
        "add_output", "missing_output_request", {"action": object()}
    )
    runner = Runner()
    result = execute_authorized_correction(
        "executor", runner, candidate, "Model-1", "Job-1", confirmed=True
    )
    assert result["attempt"].status == "failed"
    assert result["run"] is None
    assert runner.calls == []
