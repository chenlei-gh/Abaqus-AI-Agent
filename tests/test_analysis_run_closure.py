import pytest
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
from abaqus_ai_agent.contracts.provenance import AnalysisProvenance
from abaqus_ai_agent.contracts.metrics import EngineeringMetric


def test_analysis_run_canonical_structure_and_serialization():
    prov = AnalysisProvenance(
        run_id="run-123",
        model_name="Cantilever",
        job_name="StaticJob",
        model_hash="hash-model-1",
        input_hash="hash-inp-1",
        output_hash="hash-odb-1",
        intent_hash="hash-intent-1",
        action_plan_hash="hash-plan-1",
        abaqus_version="2025",
        python_version="3.10",
        executor="LiveAbaqusExecutor",
    )
    metric = EngineeringMetric(
        name="max_mises",
        value=250.5,
        unit="MPa",
        location="Root",
    )
    run = AnalysisRun(
        id="run-123",
        model_name="Cantilever",
        job_name="StaticJob",
        state=AnalysisRunState.ACCEPTED,
        solver="standard",
        engineering_status="result_valid",
        acceptance_passed=True,
        provenance=prov,
        metrics=(metric,),
        assumptions=("small_strain", "linear_elastic"),
        report_reference="reports/cantilever_static.md",
    )

    # Metric lookup
    assert run.get_metric("max_mises") == 250.5
    assert run.get_metric("non_existent") is None

    # Canonical dict
    d = run.to_dict()
    assert d["id"] == "run-123"
    assert d["solver"] == "standard"
    assert d["engineering_status"] == "result_valid"
    assert d["acceptance_passed"] is True
    assert "small_strain" in d["assumptions"]
    assert d["provenance"]["intent_hash"] == "hash-intent-1"
    assert d["provenance"]["action_plan_hash"] == "hash-plan-1"
    assert d["report_reference"] == "reports/cantilever_static.md"

    # Evidence package
    pkg = run.to_evidence_package()
    assert pkg["run_id"] == "run-123"
    assert pkg["solver"] == "standard"
    assert pkg["acceptance_passed"] is True
    assert len(pkg["metrics"]) == 1
    assert pkg["provenance"]["run_id"] == "run-123"
