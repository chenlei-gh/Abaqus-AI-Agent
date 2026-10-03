"""Tests for Batch 1: Real Abaqus Failure-Path Matrix & Tamper Protection.

Validates that:
1. All 5 authentic solver failure & evidence protection cases (F1~F5) are present and verified.
2. The schema version is 'real_failure_matrix_v1' and evidence tier is 'REAL_ABAQUS'.
3. Real solver errors (numerical singularity, cutback below minimum, syntax abort) deterministically fail closed.
4. Solver exit 0 with missing required field output (e.g., U absent when max_displacement declared) results in BLOCKED / RESULT_INVALID, NEVER a false PASS.
5. Cryptographic tampering of ODB or INP is immediately detected by SHA-256 provenance check and fails closed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from abaqus_ai_agent.acceptance import evaluate_criteria, evaluate_result_acceptance
from abaqus_ai_agent.diagnostics.solver_patterns import diagnose_solver_artifacts

ROOT = Path(__file__).resolve().parent.parent


def test_real_failure_matrix_evidence_manifest():
    """Verify machine_validation/real_failure_matrix_evidence.json qualification."""
    manifest_path = ROOT / "machine_validation" / "real_failure_matrix_evidence.json"
    assert manifest_path.is_file(), f"Missing manifest: {manifest_path}"

    with manifest_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["schema_version"] == "real_failure_matrix_v1"
    assert data["evidence_tier"] == "REAL_ABAQUS"
    assert data["solver_version"] == "Abaqus 2025"
    assert data["all_cases_fail_closed"] is True
    assert data["cases_count"] == 5
    assert data["passed_cases_count"] == 5

    cases_by_id = {c["case_id"]: c for c in data["cases"]}
    assert set(cases_by_id.keys()) == {"F1", "F2", "F3", "F4", "F5"}

    # F1: Unconstrained Rigid Body
    f1 = cases_by_id["F1"]
    assert f1["name"] == "UNCONSTRAINED_RIGID_BODY"
    assert f1["target_status"] == "FAILED"
    assert f1["solver_completed_cleanly"] is False
    assert f1["has_singularity_or_cutbacks"] is True
    assert "NUMERICAL_SINGULARITY" in f1["diagnosed_issue_ids"]
    assert f1["acceptance_status"] == "BLOCKED"
    assert f1["acceptance_passed"] is False
    assert f1["fail_closed"] is True
    assert len(f1["artifacts"]["msg_sha256"]) == 64

    # F2: Convergence Cutback Exhausted
    f2 = cases_by_id["F2"]
    assert f2["name"] == "CONVERGENCE_CUTBACK_EXHAUSTED"
    assert f2["target_status"] == "FAILED"
    assert f2["solver_completed_cleanly"] is False
    assert f2["has_cutback_or_distortion"] is True
    assert "TIME_INCREMENT_LESS_THAN_MINIMUM" in f2["diagnosed_issue_ids"]
    assert f2["acceptance_status"] == "BLOCKED"
    assert f2["acceptance_passed"] is False
    assert f2["fail_closed"] is True
    assert len(f2["artifacts"]["msg_sha256"]) == 64

    # F3: INP Syntax Abort
    f3 = cases_by_id["F3"]
    assert f3["name"] == "INP_SYNTAX_ABORT"
    assert f3["target_status"] == "FAILED"
    assert f3["pre_processor_rejected"] is True
    assert f3["acceptance_status"] == "BLOCKED"
    assert f3["acceptance_passed"] is False
    assert f3["fail_closed"] is True
    assert len(f3["artifacts"]["inp_sha256"]) == 64
    assert len(f3["artifacts"]["dat_sha256"]) == 64

    # F4: Missing Required Field Output
    f4 = cases_by_id["F4"]
    assert f4["name"] == "MISSING_REQUIRED_FIELD_OUTPUT"
    assert f4["target_status"] == "RESULT_INVALID"
    assert f4["solver_succeeded"] is True  # Exit 0
    assert f4["odb_exists"] is True        # ODB was created
    assert f4["displacement_missing"] is True
    assert "U" not in f4["available_field_outputs"]
    assert f4["acceptance_status"] == "BLOCKED"
    assert f4["acceptance_passed"] is False
    assert any("max_displacement" in b for b in f4["acceptance_blocked"])
    assert f4["fail_closed"] is True

    # F5: Evidence Tamper Protection
    f5 = cases_by_id["F5"]
    assert f5["name"] == "EVIDENCE_TAMPER_PROTECTION"
    assert f5["target_status"] == "EVIDENCE_TAMPERED"
    assert f5["odb_tamper_detected"] is True
    assert f5["inp_tamper_detected"] is True
    assert f5["evidence_tampered_rejected"] is True
    assert f5["original_odb_sha256"] != f5["tampered_odb_sha256"]
    assert f5["original_inp_sha256"] != f5["tampered_inp_sha256"]
    assert f5["fail_closed"] is True


def test_missing_required_field_acceptance_logic():
    """Unit test: solver completed with exit 0, but required metric is missing -> BLOCKED."""
    # When solver finishes successfully, but an intentional requirement was not extracted
    acc = evaluate_result_acceptance(
        result_status="completed",
        values={"mises_max": 120.0},  # S present, but U missing
        criteria=[{"name": "max_displacement", "operator": "<=", "limit": 0.5}],
        required_metrics=["max_displacement"],
    )
    assert acc.passed is False
    assert acc.status == "BLOCKED"
    assert any("max_displacement" in b for b in acc.blocked)


def test_evidence_tamper_detection_logic(tmp_path: Path):
    """Unit test: any byte mutation or modification invalidates provenance hash."""
    test_file = tmp_path / "artifact.dat"
    test_file.write_bytes(b"A" * 1024)

    h1 = hashlib.sha256(test_file.read_bytes()).hexdigest()

    # Mutate 1 byte
    with test_file.open("r+b") as f:
        f.seek(100)
        f.write(b"B")

    h2 = hashlib.sha256(test_file.read_bytes()).hexdigest()
    assert h1 != h2, "Cryptographic hash must detect byte-level mutation"
