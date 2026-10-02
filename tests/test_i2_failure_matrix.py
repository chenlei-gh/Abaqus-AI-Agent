"""Tests for Phase I.2 Mandatory Failure-Path Matrix & State Preservation."""

from __future__ import annotations

from pathlib import Path

from tools.i2_failure_matrix import (
    CANONICAL_FAILURE_SPECS,
    evaluate_failure_path_case,
    run_failure_matrix_verification,
    spawn_and_evaluate_real_process_failure,
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
        assert p["is_live_subprocess"] is True
        assert p["real_exit_code"] is not None
        assert p["detected_status"] in ("INCOMPLETE", "TIMEOUT", "ODB_MISSING", "RESULT_INVALID")


def test_spawn_and_evaluate_real_process_failure_direct():
    """Directly assert that authentic OS subprocesses are invoked and intercepted."""
    p_crash = spawn_and_evaluate_real_process_failure(
        probe_id="LIVE-CRASH-01",
        scenario="Live abort with exit 137",
        probe_type="CRASH",
    )
    assert p_crash.is_live_subprocess is True
    assert p_crash.real_exit_code == 137
    assert p_crash.detected_status == "INCOMPLETE"
    assert p_crash.fail_closed is True
    assert p_crash.evidence_preserved is True

    p_timeout = spawn_and_evaluate_real_process_failure(
        probe_id="LIVE-TIMEOUT-01",
        scenario="Live sleep exceeding timeout limit",
        probe_type="TIMEOUT",
    )
    assert p_timeout.is_live_subprocess is True
    assert p_timeout.detected_status == "TIMEOUT"
    assert p_timeout.fail_closed is True
    assert p_timeout.evidence_preserved is True
