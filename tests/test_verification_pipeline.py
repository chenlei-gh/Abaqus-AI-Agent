from unittest.mock import patch

from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
from abaqus_ai_agent.contracts.numerical import NumericalVerificationResult
from abaqus_ai_agent.contracts.contact import ExpectedContactBehavior
from abaqus_ai_agent.contracts.engineering_checks import (
    EngineeringCheck,
    EngineeringCheckReport,
)
from abaqus_ai_agent.execution.jobs import JobState, JobStatus
from abaqus_ai_agent.contracts.version import AbaqusRuntimeInfo


class FakeExecutor:
    def snapshot(self):
        return None

    def execute(self, code, timeout=None):
        return {"status": "COMPLETED"}

    def inspect_odb(self, path):
        return {"status": "available", "steps": ("Step-1",)}

    def runtime_info(self):
        return AbaqusRuntimeInfo(
            version="B28",
            python_version="2.7",
            metadata={"runtime_source": "test"},
        )


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
            "abaqus_ai_agent.execution.results.extract_criteria",
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
    acceptance = next(e.value for e in run.evidence.items if e.kind == "acceptance")
    assert acceptance.passed, acceptance.failures
    assert run.acceptance_passed is True
    assert run.state.value == "accepted"
    assert run.engineering_status == "RESULT_VALID"
    assert run.provenance.abaqus_version == "B28"
    assert run.provenance.python_version == "2.7"
    assert run.provenance.executor == "FakeExecutor"
    assert run.provenance.metadata["content_hash_scope"] == "not_captured"


def test_verification_runs_without_explicit_acceptance_criteria():
    numerical = NumericalVerificationResult(
        name="mesh", status="not_converged", error=0.2, tolerance=0.05,
        points=(1.0, 1.2),
    )
    run = _run(result_values=False, numerical_verification=numerical)
    assert run.acceptance_passed is False
    assert run.state.value == "results_extracted"


def test_contact_failure_blocks_the_analysis_acceptance_chain():
    expected = ExpectedContactBehavior(
        contact_required=True,
        expected_state="contact",
        required_outputs=("CSTATUS",),
    )
    contact_evidence = {
        "step": "Step-1",
        "frame": -1,
        "region": None,
        "fields": {
            "CSTATUS": {
                "status": "available",
                "values": [{"data": "open"}],
            },
        },
        "history": {"status": "available"},
    }
    with patch(
        "abaqus_ai_agent.execution.odb.extract_contact_evidence",
        return_value=contact_evidence,
    ):
        run = _run(contact_expected=expected)
    assert run.acceptance_passed is False
    assert run.state.value == "results_extracted"
    acceptance = next(e.value for e in run.evidence.items if e.kind == "acceptance")
    assert "contact:expected_contact_state:fail" in acceptance.failures
    assert any(e.kind == "contact_evidence" for e in run.evidence.items)
    assert any(e.kind == "contact_diagnostics" for e in run.evidence.items)


def test_contact_warning_does_not_block_the_analysis_acceptance_chain():
    expected = ExpectedContactBehavior(
        contact_required=True,
        expected_state="contact",
        expected_separation=0.02,
        required_outputs=("CSTATUS", "COPEN"),
    )
    contact_evidence = {
        "step": "Step-1",
        "frame": -1,
        "region": None,
        "fields": {
            "CSTATUS": {
                "status": "available",
                "values": [{"data": "closed"}],
            },
            "COPEN": {
                "status": "available",
                "values": [{"data": -0.01}],
            },
        },
        "history": {"status": "available"},
    }
    with patch(
        "abaqus_ai_agent.execution.odb.extract_contact_evidence",
        return_value=contact_evidence,
    ):
        run = _run(contact_expected=expected)
    assert run.acceptance_passed is True
    acceptance = next(e.value for e in run.evidence.items if e.kind == "acceptance")
    assert not acceptance.failures
    assert any(item.startswith("contact:unexpected_overclosure:warning") for item in acceptance.warnings)
