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

    # Runtime process boundary probes verification
    rt_probes = manifest.get("runtime_process_probes", [])
    assert len(rt_probes) == 4
    assert manifest["all_runtime_probes_fail_closed"] is True
    for p in rt_probes:
        assert p["fail_closed"] is True
        assert p["evidence_preserved"] is True
        assert p["detected_status"] in ("INCOMPLETE", "TIMEOUT", "ODB_MISSING", "RESULT_INVALID")
