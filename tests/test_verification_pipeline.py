from unittest.mock import patch

from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
from abaqus_ai_agent.contracts.numerical import NumericalVerificationResult
from abaqus_ai_agent.contracts.results import ResultExtraction, ResultRequirement
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
        extraction = ResultExtraction(
            ResultRequirement(
                name="tip_displacement",
                value_key="tip_displacement",
                field="U",
                step="Step-1",
            ),
            0.5,
        )
        with patch(
            "abaqus_ai_agent.execution.results.extract_requirements",
            return_value=((extraction,), ()),
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


def test_mesh_quality_and_convergence_gate_acceptance():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    from abaqus_ai_agent.contracts.mesh_quality import MeshQualityResult
    from abaqus_ai_agent.contracts.convergence import MeshConvergenceResult

    quality = MeshQualityResult("warning", warnings=("bad_transition",))
    convergence = MeshConvergenceResult(
        "quality_gate_failed", (), 0.001, False,
        warnings=("mesh_quality_gate_not_passed",),
        quality_gate_passed=False,
    )
    result = evaluate_result_acceptance(
        "completed",
        mesh_quality=quality,
        convergence=convergence,
        values={},
        criteria=(),
    )
    assert not result.passed
    assert "mesh_quality_failed" in result.failures
    assert "mesh_convergence_failed" in result.failures


def test_fatigue_verification_is_first_class_acceptance_gate():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    from abaqus_ai_agent.contracts.fatigue import FatigueResult

    fatigue = FatigueResult(
        "warning", life_cycles=1.0e5,
        warnings=("missing_material_curve_evidence",),
    )
    result = evaluate_result_acceptance(
        "completed", fatigue=fatigue, values={}, criteria=(),
    )
    assert not result.passed
    assert "fatigue_verification_failed" in result.failures
    assert "fatigue_warning" in result.warnings


def test_singularity_warning_is_distinct_from_mesh_nonconvergence():
    from abaqus_ai_agent.contracts.convergence import (
        MeshConvergencePoint, MeshConvergencePolicy, evaluate_mesh_convergence,
    )

    points = (
        MeshConvergencePoint(4.0, 100.0, quantity="max_mises"),
        MeshConvergencePoint(2.0, 100.5, quantity="max_mises", singularity_suspected=True),
        MeshConvergencePoint(1.0, 100.4, quantity="max_mises", singularity_suspected=True),
    )
    result = evaluate_mesh_convergence(
        points, MeshConvergencePolicy(tolerance=0.01),
    )
    assert result.converged
    assert result.status == "converged_with_singularity_warning"
    assert result.singularity_suspected
    assert "stress_singularity_suspected" in result.warnings


def test_contact_diagnostics_gate_supplied_contact_verification():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    from abaqus_ai_agent.contracts.contact import ContactDiagnostic, ContactDiagnosticReport

    report = ContactDiagnosticReport((
        ContactDiagnostic("contact_state", "fail", message="expected contact was open"),
    ))
    result = evaluate_result_acceptance(
        "completed", contact_diagnostics=report, values={}, criteria=(),
    )
    assert not result.passed
    assert "contact_diagnostics_failed" in result.failures


def test_contact_not_applicable_is_not_silent_pass():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    from abaqus_ai_agent.contracts.contact import ContactDiagnostic, ContactDiagnosticReport

    report = ContactDiagnosticReport((
        ContactDiagnostic("contact_state", "not_applicable"),
    ))
    result = evaluate_result_acceptance(
        "completed", contact_diagnostics=report, values={}, criteria=(),
    )
    assert result.passed
    assert "contact_diagnostics_not_applicable" in result.warnings


def test_agent_analysis_run_exposes_all_verification_domains():
    from abaqus_ai_agent.agent import AbaqusAIAgent
    import inspect

    signature = inspect.signature(AbaqusAIAgent.analysis_run)
    for name in (
        "mesh_quality", "mesh_convergence", "fatigue",
        "contact_diagnostics", "sensitivity", "uncertainty",
    ):
        assert name in signature.parameters


def test_agent_analysis_run_exposes_runner_timeout():
    from abaqus_ai_agent.agent import AbaqusAIAgent
    import inspect

    signature = inspect.signature(AbaqusAIAgent.analysis_run)
    assert "timeout" in signature.parameters
    assert signature.parameters["timeout"].default == 3600
