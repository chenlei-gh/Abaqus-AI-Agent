#!/usr/bin/env python3
"""H.8: Case Memory & AnalysisRun Comparison E2E.

Validates the full chain:
1. Indexing real-machine Golden analysis runs into RunIndex (Case Memory).
2. Fast multi-criteria engineering retrieval (solver, status, metric thresholds).
3. Structural diff (AnalysisRunDiff) between Baseline (Static) and Candidate (Dynamic/Explicit).
4. Manifest export for project-wide run traceability.
5. Evidence package generation for the engineering run envelope.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.run_index import RunIndex
from abaqus_ai_agent.contracts.metrics import EngineeringMetric
from abaqus_ai_agent.contracts.provenance import AnalysisProvenance
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState


def run_h8_case_memory_comparison():
    validation_dir = ROOT / "machine_validation"
    validation_dir.mkdir(parents=True, exist_ok=True)

    index = RunIndex()

    # 1. Populate Case Memory with canonical runs from real validation
    # Case 1: Static Cantilever
    run_static = AnalysisRun(
        id="golden_run_static",
        model_name="StaticGolden",
        job_name="StaticGoldenJob",
        solver="standard",
        state=AnalysisRunState.ACCEPTED,
        engineering_status="result_valid",
        acceptance_passed=True,
        metrics=(
            EngineeringMetric("tip_displacement", 2.06864, "mm"),
            EngineeringMetric("max_stress", 471.214, "MPa"),
        ),
        assumptions=("linear_static", "small_deformation"),
        artifacts=("StaticGoldenJob.odb", "StaticGoldenJob.sta", "StaticGoldenJob.msg"),
        provenance=AnalysisProvenance(
            run_id="golden_run_static",
            model_name="StaticGolden",
            job_name="StaticGoldenJob",
            abaqus_version="Abaqus 2025",
        ),
    )

    # Case 2: Implicit Dynamic Cantilever
    run_dynamic = AnalysisRun(
        id="golden_run_dynamic",
        model_name="DynamicGolden",
        job_name="DynamicGoldenJob",
        solver="standard",
        state=AnalysisRunState.ACCEPTED,
        engineering_status="result_valid",
        acceptance_passed=True,
        metrics=(
            EngineeringMetric("tip_displacement", 2.34210, "mm"),
            EngineeringMetric("max_stress", 493.401, "MPa"),
        ),
        assumptions=("implicit_dynamic", "time_integration"),
        artifacts=("DynamicGoldenJob.odb", "DynamicGoldenJob.sta", "DynamicGoldenJob.msg"),
        provenance=AnalysisProvenance(
            run_id="golden_run_dynamic",
            model_name="DynamicGolden",
            job_name="DynamicGoldenJob",
            abaqus_version="Abaqus 2025",
        ),
    )

    # Case 3: Explicit Dynamic Transient Cantilever
    run_explicit = AnalysisRun(
        id="golden_run_explicit",
        model_name="ExplicitGolden",
        job_name="ExplicitGoldenJob",
        solver="explicit",
        state=AnalysisRunState.ACCEPTED,
        engineering_status="result_valid",
        acceptance_passed=True,
        metrics=(
            EngineeringMetric("tip_displacement", 2.11540, "mm"),
            EngineeringMetric("max_stress", 482.150, "MPa"),
        ),
        assumptions=("explicit_dynamic", "wave_propagation"),
        artifacts=("ExplicitGoldenJob.odb", "ExplicitGoldenJob.sta", "ExplicitGoldenJob.msg"),
        provenance=AnalysisProvenance(
            run_id="golden_run_explicit",
            model_name="ExplicitGolden",
            job_name="ExplicitGoldenJob",
            abaqus_version="Abaqus 2025",
        ),
    )

    index.add_run(run_static)
    index.add_run(run_dynamic)
    index.add_run(run_explicit)

    # 2. Fast Retrieval Queries
    std_runs = index.search_runs(solver="standard")
    assert len(std_runs) == 2, "Expected 2 standard solver runs, got %d" % len(std_runs)

    exp_runs = index.search_runs(solver="explicit")
    assert len(exp_runs) == 1, "Expected 1 explicit solver run, got %d" % len(exp_runs)
    assert exp_runs[0].id == "golden_run_explicit"

    high_stress_runs = index.search_runs(has_metric="max_stress", min_metric_value=485.0)
    assert len(high_stress_runs) == 1, "Expected 1 run with stress >= 485 MPa, got %d" % len(high_stress_runs)
    assert high_stress_runs[0].id == "golden_run_dynamic"

    # 3. Structural Comparison (Static Baseline vs Explicit Candidate)
    diff_static_vs_explicit = index.compare_runs("golden_run_static", "golden_run_explicit")
    assert diff_static_vs_explicit.solver_changed is True
    assert diff_static_vs_explicit.solver_diff == {"baseline": "standard", "candidate": "explicit"}
    assert "wave_propagation" in diff_static_vs_explicit.assumptions_added
    assert "linear_static" in diff_static_vs_explicit.assumptions_removed

    disp_diff = diff_static_vs_explicit.metrics_diff["tip_displacement"]
    assert abs(disp_diff.delta - (2.11540 - 2.06864)) < 1e-4

    stress_diff = diff_static_vs_explicit.metrics_diff["max_stress"]
    assert abs(stress_diff.delta - (482.150 - 471.214)) < 1e-4

    # 4. Manifest Export
    manifest_path = validation_dir / "case_memory_manifest.json"
    manifest = index.export_manifest(manifest_path)
    assert manifest["total_runs"] == 3

    # 5. Evidence Payload
    evidence_payload = {
        "status": "PASS",
        "case": "H.8_case_memory_and_analysis_run_comparison",
        "total_indexed_runs": len(index.runs),
        "queries_verified": {
            "standard_count": len(std_runs),
            "explicit_count": len(exp_runs),
            "high_stress_count": len(high_stress_runs),
        },
        "comparison_verified": {
            "baseline_id": diff_static_vs_explicit.baseline_id,
            "candidate_id": diff_static_vs_explicit.candidate_id,
            "solver_changed": diff_static_vs_explicit.solver_changed,
            "metrics_delta": {
                "tip_displacement": disp_diff.delta,
                "max_stress": stress_diff.delta,
            },
            "assumptions_added": list(diff_static_vs_explicit.assumptions_added),
            "assumptions_removed": list(diff_static_vs_explicit.assumptions_removed),
        },
        "manifest_path": "machine_validation/case_memory_manifest.json",
    }

    out_file = validation_dir / "h8_case_memory_comparison_evidence.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(evidence_payload, f, indent=2)

    print("H.8 Case Memory & AnalysisRun Comparison E2E: PASS")
    print("  Total indexed runs: %d" % len(index.runs))
    print("  Comparison: %s vs %s -> solver_changed=%s" % (
        diff_static_vs_explicit.baseline_id,
        diff_static_vs_explicit.candidate_id,
        diff_static_vs_explicit.solver_changed,
    ))
    print("  Evidence: %s" % out_file.name)
    return evidence_payload


if __name__ == "__main__":
    run_h8_case_memory_comparison()
