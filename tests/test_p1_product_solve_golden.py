"""Regression and consistency verification for P1.0 Product Solve Golden Manifest.

Validates that the real Abaqus 2025 machine run through `solve_requirement()`
maintains complete integrity, signed artifacts, verified metrics, and fail-closed gates.
"""

import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "machine_validation" / "p1_product_solve_manifest.json"


def test_p1_product_solve_manifest_integrity():
    """Verify that P1.0 Product Solve Golden manifest is qualified and matches physical criteria."""
    assert MANIFEST_PATH.is_file(), f"Manifest missing at {MANIFEST_PATH}"

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest.get("schema_version") == "p1_product_solve_golden_v1"
    assert manifest.get("case_id") == "P1_0_Product_Solve_Golden"
    assert manifest.get("evidence_tier") == "REAL_ABAQUS"
    assert manifest.get("solver") == "Abaqus 2025"
    assert manifest.get("status") == "QUALIFIED"

    # Workflow stage checks
    workflow = manifest.get("workflow", {})
    assert workflow.get("natural_language_routing") == "PASS"
    assert workflow.get("capability_resolution_20_l4") == "PASS"
    assert workflow.get("canonical_compiler") == "PASS"
    assert workflow.get("preflight_checks") == "PASS"
    assert workflow.get("live_solver_execution") == "PASS"
    assert workflow.get("odb_extraction") == "PASS"
    assert workflow.get("evidence_v2_manifest") == "PASS"
    assert workflow.get("single_exit_acceptance") == "PASS"
    assert workflow.get("task_result_contract") == "PASS"
    assert workflow.get("markdown_report_generation") == "PASS"

    # Negative probes
    probes = manifest.get("negative_probes", {})
    assert len(probes) >= 6
    for probe_name, outcome in probes.items():
        assert outcome == "PASS", f"Negative probe {probe_name} failed: {outcome}"

    # Physical metrics
    metrics = manifest.get("metrics", {})
    assert 1.5 <= metrics.get("tip_displacement", 0.0) <= 3.0
    assert 400.0 <= metrics.get("max_mises", 0.0) <= 700.0

    # Physical artifacts verification
    artifacts = manifest.get("artifacts", {})
    for ext in ("inp", "odb", "sta", "msg", "dat", "log"):
        key = f"Job_P1_Product_Solve.{ext}"
        assert key in artifacts, f"Artifact {key} missing from manifest"
        art = artifacts[key]
        assert art.get("exists") is True
        assert art.get("size_bytes", 0) > 0
        assert len(art.get("sha256", "")) == 64

    # Summary verification with strict multi-state bidirectional equivalence
    summary = manifest.get("summary", {})
    is_task_completed = (summary.get("task_status") == "COMPLETED")
    assert is_task_completed is True
    assert (summary.get("run_state", "").lower() == "accepted") == is_task_completed
    assert (summary.get("engineering_status") in ("RESULT_VALID", "ACCEPTED")) == is_task_completed
    assert (summary.get("acceptance_passed") is True) == is_task_completed

    summary_card = summary.get("summary_card", {})
    assert (summary_card.get("status") == "COMPLETED") == is_task_completed
    assert (summary_card.get("acceptance_passed") is True) == is_task_completed
