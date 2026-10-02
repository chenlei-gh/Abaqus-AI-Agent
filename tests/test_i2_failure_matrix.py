"""Tests for Phase I.2 Mandatory Failure-Path Matrix & State Preservation."""

from __future__ import annotations

from pathlib import Path

from tools.i2_failure_matrix import (
    CANONICAL_FAILURE_SPECS,
    evaluate_failure_path_case,
    run_failure_matrix_verification,
)


def test_canonical_failure_specs_coverage():
    assert len(CANONICAL_FAILURE_SPECS) == 8
    target_states = [s.target_state for s in CANONICAL_FAILURE_SPECS]
    expected_states = [
        "PASS",
        "FAIL",
        "BLOCKED",
        "SUSPICIOUS",
        "INCOMPLETE",
        "TIMEOUT",
        "ODB_MISSING",
        "RESULT_INVALID",
    ]
    assert set(target_states) == set(expected_states)


def test_failure_matrix_verification_runs():
    manifest = run_failure_matrix_verification()
    assert manifest["schema_version"] == "failure_path_matrix_v1"
    assert manifest["total_states"] == 8
    assert manifest["verified_states"] == 8
    assert manifest["all_contracts_verified"] is True
    for res in manifest["results"]:
        assert res["contract_verified"] is True
        if res["target_state"] not in ("PASS", "SUSPICIOUS"):
            assert res["passed"] is False
