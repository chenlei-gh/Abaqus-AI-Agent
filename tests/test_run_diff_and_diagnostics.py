import pytest
from abaqus_ai_agent.analysis_run_diff import diff_analysis_runs, AnalysisRunDiff
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.metrics import EngineeringMetric
from abaqus_ai_agent.contracts.provenance import AnalysisProvenance
from abaqus_ai_agent.contracts.model_snapshot import ModelSnapshot
from abaqus_ai_agent.diagnostics.solver_patterns import (
    diagnose_solver_artifacts,
    DiagnosticIssue,
)
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
from abaqus_ai_agent.execution.errors import (
    AbaqusExecutionError,
    normalize_runtime_error,
    NormalizedExecutionError,
)


def test_diff_analysis_runs_metrics_and_state():
    base_metric = EngineeringMetric(name="tip_disp", value=1.0, unit="mm")
    cand_metric = EngineeringMetric(name="tip_disp", value=1.2, unit="mm")
    new_metric = EngineeringMetric(name="max_stress", value=200.0, unit="MPa")

    base_run = AnalysisRun(
        id="run-base",
        model_name="Cantilever",
        job_name="JobBase",
        state=AnalysisRunState.ACCEPTED,
        solver="standard",
        engineering_status="result_valid",
        acceptance_passed=True,
        metrics=(base_metric,),
        assumptions=("linear",),
        artifacts=("JobBase.odb", "JobBase.sta"),
        provenance=AnalysisProvenance(
            run_id="run-base",
            model_name="Cantilever",
            job_name="JobBase",
            model_hash="hash-1",
        ),
    )

    cand_run = AnalysisRun(
        id="run-cand",
        model_name="Cantilever",
        job_name="JobCand",
        state=AnalysisRunState.FAILED,
        solver="explicit",
        engineering_status="diverged",
        acceptance_passed=False,
        metrics=(cand_metric, new_metric),
        assumptions=("linear", "large_strain"),
        artifacts=("JobCand.odb", "JobCand.sta", "JobCand.msg"),
        provenance=AnalysisProvenance(
            run_id="run-cand",
            model_name="Cantilever",
            job_name="JobCand",
            model_hash="hash-2",
        ),
    )

    diff = diff_analysis_runs(base_run, cand_run)
    assert isinstance(diff, AnalysisRunDiff)
    assert diff.baseline_id == "run-base"
    assert diff.candidate_id == "run-cand"
    assert diff.solver_changed is True
    assert diff.acceptance_changed is True

    # Assumptions diff
    assert "large_strain" in diff.assumptions_added
    assert len(diff.assumptions_removed) == 0

    # Metrics diff
    tip_delta = diff.metrics_diff["tip_disp"]
    assert pytest.approx(tip_delta.delta, abs=1e-6) == 0.2
    assert pytest.approx(tip_delta.relative_change, abs=1e-6) == 0.2

    stress_delta = diff.metrics_diff["max_stress"]
    assert stress_delta.baseline_value is None
    assert stress_delta.candidate_value == 200.0

    # Provenance diff
    assert "model_hash" in diff.provenance_diff
    assert diff.provenance_diff["model_hash"]["baseline"] == "hash-1"
    assert diff.provenance_diff["model_hash"]["candidate"] == "hash-2"

    d = diff.to_dict()
    assert d["solver_changed"] is True
    assert "tip_disp" in d["metrics_diff"]


def test_diagnose_solver_artifacts_patterns():
    sample_msg = """
    ***WARNING: SOLVER PROBLEM. NUMERICAL SINGULARITY WHEN PROCESSING NODE 104 D.O.F. 2
    ***ERROR: ZERO PIVOT ENCOUNTERED AT NODE 12 D.O.F. 1
    ***WARNING: NEGATIVE EIGENVALUE DETECTED
    ***ERROR: TIME INCREMENT REQUIRED IS LESS THAN THE MINIMUM SPECIFIED
    """
    issues = diagnose_solver_artifacts(msg_text=sample_msg)
    assert len(issues) >= 3

    diag_ids = {iss.diagnosis_id for iss in issues}
    assert "ZERO_PIVOT" in diag_ids
    assert "NEGATIVE_EIGENVALUE" in diag_ids
    assert "TIME_INCREMENT_LESS_THAN_MINIMUM" in diag_ids

    zero_pivot = next(iss for iss in issues if iss.diagnosis_id == "ZERO_PIVOT")
    assert zero_pivot.severity == "ERROR"
    assert "NODE 12" in zero_pivot.supporting_evidence[0]
    assert "displacement/rotation constraints" in zero_pivot.suggested_remediation


def test_normalize_runtime_error():
    exec_err = AbaqusExecutionError(
        "Abaqus license server connection failed: License server is down",
        category="license",
        traceback="Traceback ... line 42",
        source_line=42,
    )
    norm = normalize_runtime_error(exec_err, execution_id="exec-001")
    assert isinstance(norm, NormalizedExecutionError)
    assert norm.execution_id == "exec-001"
    assert norm.category == "license"
    assert "license" in norm.recovery_hint.lower()
    assert norm.source_line == 42

    d = norm.to_dict()
    assert d["category"] == "license"
    assert d["execution_id"] == "exec-001"
