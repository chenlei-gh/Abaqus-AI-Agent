"""Tests for Phase I.1 Comprehensive Engineering Case Matrix."""

from __future__ import annotations

import json
from pathlib import Path

from tools.i1_engineering_case_matrix import (
    CANONICAL_NINE_CASES,
    execute_fresh_case_probe,
    verify_case_matrix,
)

ROOT = Path(__file__).resolve().parent.parent


def test_canonical_nine_cases_definition():
    assert len(CANONICAL_NINE_CASES) == 9
    categories = [c["category_id"] for c in CANONICAL_NINE_CASES]
    assert categories == [f"CASE-{i:02d}" for i in range(1, 10)]


def test_verify_case_matrix_live():
    validation_dir = ROOT / "machine_validation"
    manifest = verify_case_matrix(validation_dir, run_fresh_probes=True)
    assert manifest["schema_version"] == "engineering_case_matrix_v1"
    assert manifest["total_categories"] == 9
    assert manifest["passed_categories"] == 9
    assert manifest["all_passed"] is True
    for c in manifest["cases"]:
        assert c["status"] == "PASS"
        assert c["traceability_intact"] is True
        assert c["odb_present"] is True

    # Fresh execution probes verification
    fresh = manifest.get("fresh_execution_probes", [])
    assert len(fresh) == 9
    assert manifest["fresh_probes_all_passed"] is True
    for p in fresh:
        assert p["fresh_acceptance_passed"] is True
        assert p["status"] == "PASS"
        assert len(p["intent_fingerprint"]) > 0


def test_execute_fresh_case_probe_individual():
    """Verify fresh live solver execution probe executes on demand."""
    probe_static = execute_fresh_case_probe("CASE-01")
    assert probe_static.category_id == "CASE-01"
    assert probe_static.fresh_acceptance_passed is True
    assert "tip_displacement" in probe_static.fresh_metrics

    probe_thermal = execute_fresh_case_probe("CASE-02")
    assert probe_thermal.category_id == "CASE-02"
    assert probe_thermal.fresh_acceptance_passed is True
    assert probe_thermal.fresh_metrics["midpoint_temperature"] == 50.0
