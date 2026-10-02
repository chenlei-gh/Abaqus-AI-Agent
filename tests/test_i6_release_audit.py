"""Tests for Phase I.6 Public Release Audit & Security Sanitization."""

from __future__ import annotations

from pathlib import Path

from tools.i6_release_audit import run_release_audit

ROOT = Path(__file__).resolve().parent.parent


def test_public_release_audit_all_passed():
    manifest = run_release_audit()
    assert manifest["schema_version"] == "release_audit_v1"
    assert manifest["total_checks"] == 4
    assert manifest["passed_checks"] == 4
    assert manifest["all_passed"] is True
    for c in manifest["checks"]:
        assert c["passed"] is True

    # Assert repository-wide scan checked over 100 tracked files
    chk2 = next(c for c in manifest["checks"] if c["check_id"] == "CHK-02")
    assert chk2["details"]["scanned_files_count"] >= 100
    assert len(chk2["details"]["leaks_detected"]) == 0

    # Assert no binaries tracked
    chk3 = next(c for c in manifest["checks"] if c["check_id"] == "CHK-03")
    assert len(chk3["details"]["accidentally_committed_binaries"]) == 0
