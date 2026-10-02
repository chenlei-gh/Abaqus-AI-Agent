"""Tests for Phase I.1 Comprehensive Engineering Case Matrix."""

from __future__ import annotations

import json
from pathlib import Path

from tools.i1_engineering_case_matrix import CANONICAL_NINE_CASES, verify_case_matrix

ROOT = Path(__file__).resolve().parent.parent


def test_canonical_nine_cases_definition():
    assert len(CANONICAL_NINE_CASES) == 9
    categories = [c["category_id"] for c in CANONICAL_NINE_CASES]
    assert categories == [f"CASE-{i:02d}" for i in range(1, 10)]


def test_verify_case_matrix_live():
    validation_dir = ROOT / "machine_validation"
    manifest = verify_case_matrix(validation_dir)
    assert manifest["schema_version"] == "engineering_case_matrix_v1"
    assert manifest["total_categories"] == 9
    assert manifest["passed_categories"] == 9
    assert manifest["all_passed"] is True
    for c in manifest["cases"]:
        assert c["status"] == "PASS"
        assert c["traceability_intact"] is True
        assert c["odb_present"] is True
