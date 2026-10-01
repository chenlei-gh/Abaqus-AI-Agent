from unittest.mock import patch

from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
from abaqus_ai_agent.contracts.numerical import NumericalVerificationResult
from abaqus_ai_agent.contracts.engineering_checks import (
    EngineeringCheck,
    EngineeringCheckReport,
)
from abaqus_ai_agent.execution.jobs import JobState, JobStatus


class FakeExecutor:
    def snapshot(self):
        return None

    def execute(self, code, timeout=None):
        return {"status": "COMPLETED"}

    def inspect_odb(self, path):
        return {"status": "available", "steps": ("Step-1",)}


def _run(result_values=True, **kwargs):
    executor = FakeExecutor()
    with patch(
        "abaqus_ai_agent.execution.analysis_run._collect_artifacts",
        return_value=(),
    ), patch(
        "abaqus_ai_agent.execution.analysis_run._collect_diagnostics",
        return_value={},
    ), patch(
        "abaqus_ai_agent.execution.analysis_run.discover_odb",
        return_value="/tmp/Job.odb",
    ), patch(
        "abaqus_ai_agent.execution.analysis_run.summarize_odb",
        return_value={"status": "available", "steps": ("Step-1",)},
    ), patch(
        "abaqus_ai_agent.planning.output.plan_outputs",
        return_value=(),
    ), patch(
        "abaqus_ai_agent.planning.output.actions_from_output_plan",
        return_value=(),
    ), patch(
        "abaqus_ai_agent.validation.actions.validate_action",
    ), patch(
        "abaqus_ai_agent.actions.runner.execute",
    ), patch(
        "abaqus_ai_agent.execution.analysis_run.JobController.submit",
        return_value=JobStatus("Job", JobState.COMPLETED),
    ):
        call = {
            "model_name": "Model",
            "job_name": "Job",
            "criteria": ({"value_key": "tip_displacement", "operator": "<=", "limit": 1.0},),
        }
        if result_values is not False:
            call["result_values"] = {"tip_displacement": 0.5}
            return AnalysisRunner(executor).run(**call, **kwargs)
        with patch(
            "abaqus_ai_agent.execution.analysis_run.extract_criteria",
            return_value=({"tip_displacement": 0.5}, ()),
        ):
            return AnalysisRunner(executor).run(**call, **kwargs)


def test_failed_numerical_verification_blocks_acceptance():
    numerical = NumericalVerificationResult(
        name="mesh", status="not_converged", error=0.2, tolerance=0.05,
        points=(1.0, 1.2),
    )
    run = _run(numerical_verification=numerical)
    assert run.acceptance_passed is False
    assert run.state.value == "results_extracted"
    assert any(e.kind == "numerical_verification" for e in run.evidence.items)


def test_failed_engineering_check_blocks_acceptance():
    engineering = EngineeringCheckReport((
        EngineeringCheck(
            name="reaction_balance",
            passed=False,
            actual=10.0,
            expected=0.0,
            tolerance=0.01,
        ),
    ))
    run = _run(engineering_checks=engineering)
    assert run.acceptance_passed is False
    assert run.state.value == "results_extracted"
    assert any(e.kind == "engineering_checks" for e in run.evidence.items)


def test_passing_verification_allows_odb_backed_acceptance():
    numerical = NumericalVerificationResult(
        name="mesh", status="converged", error=0.01, tolerance=0.05,
        points=(1.0, 1.01),
    )
    engineering = EngineeringCheckReport((
        EngineeringCheck(
            name="reaction_balance",
            passed=True,
            actual=0.001,
            expected=0.0,
            tolerance=0.01,
        ),
    ))
    run = _run(
        result_values=False,
        numerical_verification=numerical,
        engineering_checks=engineering,
    )
    assert run.acceptance_passed is True
    assert run.state.value == "accepted"
    assert run.engineering_status == "RESULT_VALID"


def test_verification_runs_without_explicit_acceptance_criteria():
    numerical = NumericalVerificationResult(
        name="mesh", status="not_converged", error=0.2, tolerance=0.05,
        points=(1.0, 1.2),
    )
    run = _run(result_values=False, numerical_verification=numerical)
    assert run.acceptance_passed is False
    assert run.state.value == "results_extracted"
