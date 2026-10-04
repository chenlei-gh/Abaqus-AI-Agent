"""Tests for GA-CL.4: Evidence / Provenance V2 Contract & Integrity Verification.

Validates:
1. Unified EvidenceManifestV2 contract schema, serialization, and cryptographic audit signature.
2. Run Identity Binding (prohibits reusing artifacts across runs; expected_run_id mismatch -> EVIDENCE_STALE).
3. Live artifact integrity (SHA-256 byte tampering -> EVIDENCE_TAMPERED).
4. Missing mandatory solver artifact detection (missing .sta/.odb/.msg -> EVIDENCE_INCOMPLETE).
5. Stale evidence protection (timestamp expiry -> EVIDENCE_STALE).
6. Acceptance gate integration (evidence invalid -> status BLOCKED, result_validity RESULT_INVALID, gate FAIL).
7. Report layer synchronization (never displays false approval when evidence fails integrity).
8. Official machine_validation/evidence_v2_manifest.json qualification.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import pytest

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.evidence import (
    DEFAULT_MANDATORY_ROLES,
    ArtifactRecord,
    EvidenceManifestV2,
    EvidenceVerificationReport,
    build_evidence_manifest_v2,
    compute_file_sha256,
    infer_artifact_role,
    verify_evidence_integrity,
)
from abaqus_ai_agent.contracts.report import EngineeringReportData
from abaqus_ai_agent.reporting.renderer import render_markdown
from tools.evidence_v2_qualification_e2e import run_evidence_v2_qualification

ROOT = Path(__file__).resolve().parent.parent


def test_artifact_record_and_role_inference():
    """Verify role inference and serialization for ArtifactRecord."""
    assert infer_artifact_role("model.inp") == "inp"
    assert infer_artifact_role("analysis.odb") == "odb"
    assert infer_artifact_role("job.sta") == "sta"
    assert infer_artifact_role("job.msg") == "msg"
    assert infer_artifact_role("job.dat") == "dat"
    assert infer_artifact_role("job.log") == "log"
    assert infer_artifact_role("report.md") == "report"
    assert infer_artifact_role("report.html") == "report"

    rec = ArtifactRecord(
        name="test.odb",
        path="test.odb",
        role="odb",
        exists=True,
        size_bytes=1024,
        sha256="abc123def456",
        modified_time=1700000000.0,
        mandatory=True,
    )
    d = rec.to_dict()
    assert d["role"] == "odb"
    assert d["size_bytes"] == 1024
    rec2 = ArtifactRecord.from_dict(d)
    assert rec2 == rec


def test_evidence_manifest_v2_contract_and_signature():
    """Verify cryptographic audit signature computation and validation."""
    m = EvidenceManifestV2(
        run_id="run_test_001",
        case_id="case_sample",
        created_at="2026-10-04T00:00:00Z",
        environment={"os": "windows", "solver_version": "Abaqus 2025"},
        intent_summary={"model": "Beam"},
        required_results={"fields": ["U", "S"]},
        artifacts={
            "job.inp": ArtifactRecord("job.inp", "job.inp", "inp", True, 100, "hash_inp"),
            "job.odb": ArtifactRecord("job.odb", "job.odb", "odb", True, 200, "hash_odb"),
        },
    )
    # Unsigned manifest
    assert m.audit_signature == ""
    assert not m.verify_signature()

    # Sign manifest
    m.with_signature()
    sig = m.audit_signature
    assert len(sig) == 64  # SHA-256 hex length
    assert m.verify_signature()

    # Serialization roundtrip
    json_str = m.to_json()
    m_restored = EvidenceManifestV2.from_json(json_str)
    assert m_restored.run_id == m.run_id
    assert m_restored.verify_signature()

    # Tamper manifest payload
    m_restored.intent_summary["model"] = "ForgedModel"
    assert not m_restored.verify_signature()


def test_live_artifact_integrity_and_tampering(tmp_path: Path):
    """Verify live SHA-256 checksums on disk detect byte mutation."""
    # Create mock solver artifacts
    mandatory_roles = ("inp", "odb", "msg", "dat", "sta", "log")
    fnames = [f"Job.{r}" for r in mandatory_roles]
    for fn in fnames:
        (tmp_path / fn).write_bytes(f"Content for {fn}\n".encode("utf-8"))

    manifest = build_evidence_manifest_v2(
        run_id="run_live_test",
        case_id="live_case",
        artifacts_dir=tmp_path,
        artifact_filenames=fnames,
    )
    assert manifest.verify_signature()

    # Clean verification
    rep = verify_evidence_integrity(manifest, base_dir=tmp_path, expected_run_id="run_live_test")
    assert rep.valid is True
    assert rep.validity == "VALID"
    assert len(rep.artifact_checks) == 6

    # Mutate 1 byte in Job.odb
    odb_file = tmp_path / "Job.odb"
    odb_bytes = bytearray(odb_file.read_bytes())
    odb_bytes[0] = (odb_bytes[0] + 1) % 256
    odb_file.write_bytes(odb_bytes)

    # Verification must detect tampering
    rep_tampered = verify_evidence_integrity(manifest, base_dir=tmp_path, expected_run_id="run_live_test")
    assert rep_tampered.valid is False
    assert rep_tampered.validity == "TAMPERED"
    assert "Job.odb" in rep_tampered.tampered_artifacts
    assert any("evidence_tampered:hash_mismatch:Job.odb" in f for f in rep_tampered.failures)


def test_missing_mandatory_solver_artifact_detection(tmp_path: Path):
    """Verify missing mandatory solver artifact fails with EVIDENCE_INCOMPLETE."""
    mandatory_roles = ("inp", "odb", "msg", "dat", "sta", "log")
    fnames = [f"Job.{r}" for r in mandatory_roles]
    for fn in fnames:
        (tmp_path / fn).write_bytes(f"Content for {fn}\n".encode("utf-8"))

    manifest = build_evidence_manifest_v2(
        run_id="run_incomplete_test",
        case_id="incomplete_case",
        artifacts_dir=tmp_path,
        artifact_filenames=fnames,
    )

    # Delete Job.sta from disk
    (tmp_path / "Job.sta").unlink()

    rep = verify_evidence_integrity(manifest, base_dir=tmp_path, expected_run_id="run_incomplete_test")
    assert rep.valid is False
    assert rep.validity == "INCOMPLETE"
    assert "Job.sta" in rep.missing_artifacts
    assert any("evidence_incomplete:missing_artifact:Job.sta" in f for f in rep.failures)


def test_run_identity_binding_and_stale_detection(tmp_path: Path):
    """Verify run_id mismatch and timestamp expiry reject stale evidence."""
    (tmp_path / "Job.inp").write_bytes(b"INPUT")
    (tmp_path / "Job.odb").write_bytes(b"OUTPUT")

    manifest = build_evidence_manifest_v2(
        run_id="run_old_job_123",
        case_id="case_1",
        artifacts_dir=tmp_path,
        artifact_filenames=["Job.inp", "Job.odb"],
        created_at="2020-01-01T00:00:00Z",
    )

    # 1. Run ID mismatch
    rep_mismatch = verify_evidence_integrity(
        manifest,
        base_dir=tmp_path,
        expected_run_id="run_new_job_456",
        mandatory_roles=("inp", "odb"),
    )
    assert rep_mismatch.valid is False
    assert rep_mismatch.stale is True
    assert rep_mismatch.validity == "STALE"
    assert any("evidence_stale:run_id_mismatch" in f for f in rep_mismatch.failures)

    # 2. Timestamp expiry
    rep_expired = verify_evidence_integrity(
        manifest,
        base_dir=tmp_path,
        expected_run_id="run_old_job_123",
        max_age_seconds=60.0,
        mandatory_roles=("inp", "odb"),
    )
    assert rep_expired.valid is False
    assert rep_expired.stale is True
    assert rep_expired.validity == "STALE"
    assert any("evidence_stale:timestamp_expired" in f for f in rep_expired.failures)


def test_acceptance_gate_binding_fail_closed(tmp_path: Path):
    """Verify evaluate_result_acceptance binds to evidence integrity and fails closed."""
    mandatory_roles = ("inp", "odb", "msg", "dat", "sta", "log")
    fnames = [f"Job.{r}" for r in mandatory_roles]
    for fn in fnames:
        (tmp_path / fn).write_bytes(f"Content for {fn}\n".encode("utf-8"))

    manifest = build_evidence_manifest_v2(
        run_id="run_acc_test",
        case_id="acc_case",
        artifacts_dir=tmp_path,
        artifact_filenames=fnames,
    )

    # Positive: valid evidence passes
    acc_pass = evaluate_result_acceptance(
        result_status="completed",
        values={"max_stress": 50.0},
        criteria=[{"name": "stress", "value_key": "max_stress", "operator": "<=", "limit": 100.0}],
        evidence_manifest=manifest,
        expected_run_id="run_acc_test",
        base_dir=tmp_path,
    )
    assert acc_pass.passed is True
    assert acc_pass.status == "PASS"
    assert acc_pass.result_validity == "VALID"
    assert acc_pass.gates["evidence_sufficiency"] == "PASS"
    assert acc_pass.evidence_status == "VALID"

    # Negative 1: Tampered artifact causes acceptance BLOCKED and RESULT_INVALID
    (tmp_path / "Job.odb").write_bytes(b"CORRUPTED_BYTES")
    acc_tampered = evaluate_result_acceptance(
        result_status="completed",
        values={"max_stress": 50.0},
        criteria=[{"name": "stress", "value_key": "max_stress", "operator": "<=", "limit": 100.0}],
        evidence_manifest=manifest,
        expected_run_id="run_acc_test",
        base_dir=tmp_path,
    )
    assert acc_tampered.passed is False
    assert acc_tampered.status == "BLOCKED"
    assert acc_tampered.result_validity == "RESULT_INVALID"
    assert acc_tampered.gates["evidence_sufficiency"] == "FAIL"
    assert acc_tampered.evidence_status == "TAMPERED"
    assert any("evidence_tampered:hash_mismatch:Job.odb" in b for b in acc_tampered.blocked)
    assert "Engineering Acceptance: FAIL" in acc_tampered.audit_summary

    # Negative 2: Stale run_id causes acceptance BLOCKED and RESULT_INVALID
    # Restore Job.odb so only run_id is mismatched
    (tmp_path / "Job.odb").write_bytes(f"Content for Job.odb\n".encode("utf-8"))
    acc_stale = evaluate_result_acceptance(
        result_status="completed",
        values={"max_stress": 50.0},
        criteria=[{"name": "stress", "value_key": "max_stress", "operator": "<=", "limit": 100.0}],
        evidence_manifest=manifest,
        expected_run_id="run_different_job_id",
        base_dir=tmp_path,
    )
    assert acc_stale.passed is False
    assert acc_stale.status == "BLOCKED"
    assert acc_stale.result_validity == "RESULT_INVALID"
    assert acc_stale.gates["evidence_sufficiency"] == "FAIL"
    assert acc_stale.evidence_status == "STALE"


def test_engineering_report_evidence_synchronization():
    """Verify that reports display cryptographic provenance and fail closed on invalid evidence."""
    # Report with evidence failures
    mock_acceptance_tampered = {
        "passed": False,
        "status": "BLOCKED",
        "result_validity": "RESULT_INVALID",
        "failures": ["evidence_tampered:hash_mismatch:model.odb"],
        "gates": {"execution": "PASS", "odb": "PASS", "evidence_sufficiency": "FAIL"},
        "evidence_status": "TAMPERED",
    }
    report = EngineeringReportData(
        title="Tamper Audit Test Report",
        acceptance=mock_acceptance_tampered,
    )
    md = render_markdown(report)
    assert "EVIDENCE TAMPER DETECTED" in md
    assert "REJECTED (RESULT_INVALID)" in md
    assert "FAIL (TAMPERED)" in md


def test_official_evidence_v2_qualification_manifest():
    """Verify that the official GA-CL.4 qualification manifest is verified and pass."""
    manifest_path = ROOT / "machine_validation" / "evidence_v2_manifest.json"
    if not manifest_path.exists():
        manifest = run_evidence_v2_qualification()
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "evidence_v2_manifest_v1"
    assert manifest["milestone"] == "GA-CL.4"
    assert manifest["all_vectors_passed"] is True
    assert manifest["vectors_count"] == 7

    vectors = manifest["vectors"]
    assert vectors["V1_valid_manifest_qualification"]["passed"] is True
    assert vectors["V2_artifact_tamper_detection"]["fail_closed"] is True
    assert vectors["V3_missing_critical_artifact"]["fail_closed"] is True
    assert vectors["V4_run_identity_mismatch"]["fail_closed"] is True
    assert vectors["V5_timestamp_expiry_stale"]["fail_closed"] is True
    assert vectors["V6_manifest_signature_tamper"]["fail_closed"] is True
    assert vectors["V7_report_synchronization"]["fail_closed"] is True
