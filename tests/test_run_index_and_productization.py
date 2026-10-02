import pytest
from abaqus_ai_agent.run_index import RunIndex
from abaqus_ai_agent.contracts.metrics import EngineeringMetric
from abaqus_ai_agent.contracts.provenance import AnalysisProvenance
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
from abaqus_ai_agent.reporting.renderer import render_analysis_report


def test_run_index_search_compare_and_evidence():
    index = RunIndex()

    run1 = AnalysisRun(
        id="run-001",
        model_name="Beam",
        job_name="StaticJob",
        state=AnalysisRunState.ACCEPTED,
        solver="standard",
        engineering_status="result_valid",
        acceptance_passed=True,
        metrics=(EngineeringMetric("max_mises", 220.0, "MPa"),),
        provenance=AnalysisProvenance(run_id="run-001", model_name="Beam", job_name="StaticJob"),
    )

    run2 = AnalysisRun(
        id="run-002",
        model_name="Beam",
        job_name="DynamicJob",
        state=AnalysisRunState.ACCEPTED,
        solver="explicit",
        engineering_status="result_valid",
        acceptance_passed=True,
        metrics=(EngineeringMetric("max_mises", 280.0, "MPa"),),
        provenance=AnalysisProvenance(run_id="run-002", model_name="Beam", job_name="DynamicJob"),
    )

    index.add_run(run1)
    index.add_run(run2)

    # Search by solver
    res_std = index.search_runs(solver="standard")
    assert len(res_std) == 1
    assert res_std[0].id == "run-001"

    # Search by metric threshold
    res_high_stress = index.search_runs(has_metric="max_mises", min_metric_value=250.0)
    assert len(res_high_stress) == 1
    assert res_high_stress[0].id == "run-002"

    # Compare runs
    diff = index.compare_runs("run-001", "run-002")
    assert diff.solver_changed is True
    assert diff.metrics_diff["max_mises"].candidate_value == 280.0

    # Browse evidence
    ev = index.browse_evidence("run-001")
    assert ev["run_id"] == "run-001"
    assert ev["solver"] == "standard"
    assert len(ev["metrics"]) == 1


def test_render_analysis_report_markdown_and_html():
    run = AnalysisRun(
        id="run-report-1",
        model_name="Bracket",
        job_name="ReportJob",
        state=AnalysisRunState.ACCEPTED,
        solver="standard",
        engineering_status="result_valid",
        acceptance_passed=True,
        metrics=(
            EngineeringMetric("tip_deflection", 1.45, "mm"),
            EngineeringMetric("peak_mises", 185.0, "MPa"),
        ),
        assumptions=("small_displacement", "linear_material"),
        provenance=AnalysisProvenance(run_id="run-report-1", model_name="Bracket", job_name="ReportJob"),
    )

    res = render_analysis_report(run, title="Bracket Structural Verification", objective="Validate bracket under 5kN tip load")
    md = res["markdown"]
    html_out = res["html"]

    assert "# Bracket Structural Verification" in md
    assert "Validate bracket under 5kN tip load" in md
    assert "1.45" in md
    assert "| Metric Name" in md
    assert "| tip_deflection" in md
    assert "<!doctype html>" in html_out
    assert "Bracket Structural Verification" in html_out


def test_run_index_persistence_and_manifest(tmp_path):
    index = RunIndex()

    run1 = AnalysisRun(
        id="run-persist-1",
        model_name="Beam",
        job_name="JobBeam",
        state=AnalysisRunState.ACCEPTED,
        solver="standard",
        engineering_status="result_valid",
        acceptance_passed=True,
        metrics=(EngineeringMetric("peak_mises", 210.5, "MPa"),),
        assumptions=("linear",),
        provenance=AnalysisProvenance(run_id="run-persist-1", model_name="Beam", job_name="JobBeam"),
    )

    run2 = AnalysisRun(
        id="run-persist-2",
        model_name="Plate",
        job_name="JobPlate",
        state=AnalysisRunState.FAILED,
        solver="explicit",
        engineering_status="diverged",
        acceptance_passed=False,
        metrics=(EngineeringMetric("energy_ratio", 1.8, "ratio"),),
        diagnostics=("abnormal energy growth",),
        provenance=AnalysisProvenance(run_id="run-persist-2", model_name="Plate", job_name="JobPlate"),
    )

    index.add_run(run1)
    index.add_run(run2)

    save_dir = tmp_path / "case_memory"
    saved_count = index.save_to_directory(save_dir)
    assert saved_count == 2
    assert (save_dir / "run-persist-1.json").exists()
    assert (save_dir / "run-persist-2.json").exists()
    assert (save_dir / "manifest.json").exists()

    manifest = index.export_manifest()
    assert manifest["total_runs"] == 2
    assert len(manifest["runs"]) == 2

    # Test restoring from directory into a fresh index
    restored_index = RunIndex()
    loaded_count = restored_index.load_from_directory(save_dir)
    assert loaded_count == 2
    assert restored_index.get_run("run-persist-1") is not None
    assert restored_index.get_run("run-persist-2") is not None

    r1 = restored_index.get_run("run-persist-1")
    assert r1.solver == "standard"
    assert r1.acceptance_passed is True
    assert r1.get_metric("peak_mises") == 210.5
    assert r1.provenance is not None
    assert r1.provenance.model_name == "Beam"

    r2 = restored_index.get_run("run-persist-2")
    assert r2.solver == "explicit"
    assert r2.acceptance_passed is False
    assert r2.diagnostics == ("abnormal energy growth",)
