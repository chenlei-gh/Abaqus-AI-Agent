"""P0 Acceptance Kernel Verification Suite: Negative and Positive Probes.

Tests the four-dimensional decoupled acceptance evaluation contract:
1. acceptance_status: PASS | FAIL | BLOCKED | RESULT_INVALID
2. result_validity: VALID | INCOMPLETE | EVIDENCE_STALE | EVIDENCE_TAMPERED | EVIDENCE_CORRUPT
3. deliverable: True only if acceptance_status == "PASS" and result_validity == "VALID"
4. findings: Structured findings preserving all failures, blocked, evidence_errors, warnings, missing_gates.

Covers:
- NEG-P0-01 ~ NEG-P0-08: Fail-closed negative security and grounding probes.
- POS-P0-01 ~ POS-P0-03: Positive baseline probes.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.acceptance import (
    AcceptanceFindings,
    AcceptanceResult,
    evaluate_criteria,
    evaluate_result_acceptance,
)
from abaqus_ai_agent.contracts.evidence import build_evidence_manifest_v2


def _create_standard_mock_artifacts(tmp_path: Path, run_id: str = "run_p0_std") -> list[str]:
    """Helper to create standard mock artifacts in tmp_path."""
    roles = ("inp", "odb", "msg", "dat", "sta", "log")
    fnames = []
    for r in roles:
        fn = f"Job_{run_id}.{r}"
        p = tmp_path / fn
        # Write binary-looking non-json bytes for odb, text for others
        if r == "odb":
            p.write_bytes(b"\x7fABAQUS_BINARY_ODB_HEADER\x00\x01\x02\x03\x04" * 64)
        else:
            p.write_text(f"Content for {fn}\n", encoding="utf-8")
        fnames.append(fn)
    return fnames


# =========================================================================
# Negative Probes (NEG-P0-01 ~ NEG-P0-08)
# =========================================================================

def test_neg_p0_01_mixed_criteria_failed_with_blocked_gate(tmp_path: Path):
    """NEG-P0-01: Physical failure must NEVER be masked by missing/blocked gates.

    When stress exceeds limit (physical FAIL) but mandatory contact gate is missing/blocked,
    status MUST be 'FAIL' (preserving physical failure), result_validity 'VALID',
    deliverable False, and findings.blocked must record the missing gate.
    """
    files = _create_standard_mock_artifacts(tmp_path, "p0_neg1")
    manifest = build_evidence_manifest_v2(
        run_id="p0_neg1",
        case_id="case_neg1",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    criteria = [
        {"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 200.0, "unit": "MPa"},
    ]
    # max_mises is 350.0 > 200.0 (clearly failed physically)
    values = {"max_mises": 350.0, "contact_pressure": 0.0}

    res = evaluate_result_acceptance(
        result_status="completed",
        values=values,
        criteria=criteria,
        physics_domain="contact",  # domain contact requires contact_diagnostics gate
        contact_diagnostics=None,  # missing mandatory gate!
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert res.acceptance_status == "FAIL", f"Expected FAIL, got {res.acceptance_status}"
    assert res.status == "FAIL"
    assert res.passed is False
    assert res.result_validity == "VALID"
    assert res.deliverable is False

    # Check findings details
    assert hasattr(res, "findings")
    assert any("mises_limit" in f for f in res.findings.failures)
    assert any("contact_diagnostics" in b for b in res.findings.blocked)


def test_neg_p0_02_plaintext_json_fake_odb_rejected(tmp_path: Path):
    """NEG-P0-02: Plaintext JSON disguised as .odb must be rejected as EVIDENCE_CORRUPT."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_neg2")
    # Overwrite the .odb with plaintext JSON (Case 06 fake ODB pattern)
    odb_path = tmp_path / "Job_p0_neg2.odb"
    odb_path.write_text(json.dumps({"mises": 120.0, "fake": True}), encoding="utf-8")

    manifest = build_evidence_manifest_v2(
        run_id="p0_neg2",
        case_id="case_neg2",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"stress": 100.0},
        criteria=[{"name": "s", "value_key": "stress", "operator": "<", "limit": 200.0}],
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "EVIDENCE_CORRUPT"
    assert res.deliverable is False
    assert any("corrupt_artifact:odb_is_plaintext_json" in e for e in res.findings.evidence_errors)


def test_neg_p0_03_empty_audit_signature_rejected(tmp_path: Path):
    """NEG-P0-03: Empty audit_signature must be rejected as INCOMPLETE (unsigned)."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_neg3")
    manifest = build_evidence_manifest_v2(
        run_id="p0_neg3",
        case_id="case_neg3",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )
    # Tamper manifest to have empty signature
    m_dict = manifest.to_dict()
    m_dict["audit_signature"] = ""

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"stress": 100.0},
        criteria=[{"name": "s", "value_key": "stress", "operator": "<", "limit": 200.0}],
        evidence_manifest=m_dict,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "INCOMPLETE"
    assert res.deliverable is False
    assert any("evidence_unsigned" in e for e in res.findings.evidence_errors)


def test_neg_p0_04_bare_dict_evidence_rejected():
    """NEG-P0-04: Bare unvalidated dictionary passed as evidence must be rejected as EVIDENCE_CORRUPT."""
    fake_dict = {"status": "all_good", "passed": True}

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"stress": 100.0},
        criteria=[{"name": "s", "value_key": "stress", "operator": "<", "limit": 200.0}],
        evidence=fake_dict,
        require_evidence=True,
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "EVIDENCE_CORRUPT"
    assert res.deliverable is False
    assert res.gates.get("evidence_sufficiency") != "PASS"
    assert any("unsupported_evidence_format" in e for e in res.findings.evidence_errors)


def test_neg_p0_05_tampered_sta_file_rejected(tmp_path: Path):
    """NEG-P0-05: Single-byte corruption on solver artifact must be detected as EVIDENCE_TAMPERED."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_neg5")
    manifest = build_evidence_manifest_v2(
        run_id="p0_neg5",
        case_id="case_neg5",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    # Corrupt .sta by appending 1 byte
    sta_path = tmp_path / "Job_p0_neg5.sta"
    with open(sta_path, "ab") as f:
        f.write(b"X")

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"stress": 100.0},
        criteria=[{"name": "s", "value_key": "stress", "operator": "<", "limit": 200.0}],
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "EVIDENCE_TAMPERED"
    assert res.deliverable is False
    assert any("evidence_tampered" in e for e in res.findings.evidence_errors)


def test_neg_p0_06_solver_probe_only_rejected(tmp_path: Path):
    """NEG-P0-06: Running only solver help probe without submitting job must fail acceptance."""
    # When solver_status is unsubmitted or probe only
    res = evaluate_result_acceptance(
        result_status="unsubmitted",
        values={"stress": 100.0},
        criteria=[{"name": "s", "value_key": "stress", "operator": "<", "limit": 200.0}],
        require_evidence=True,
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.deliverable is False
    assert any("solver" in f for f in res.findings.failures + res.findings.blocked)


def test_neg_p0_07_stale_cross_run_evidence_rejected(tmp_path: Path):
    """NEG-P0-07: Valid ODB/manifest from Run A used in expected Run B must be rejected as EVIDENCE_STALE."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_run_A")
    manifest = build_evidence_manifest_v2(
        run_id="p0_run_A",
        case_id="case_stale",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"stress": 100.0},
        criteria=[{"name": "s", "value_key": "stress", "operator": "<", "limit": 200.0}],
        evidence_manifest=manifest,
        expected_run_id="p0_run_B",  # mismatch!
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "EVIDENCE_STALE"
    assert res.deliverable is False
    assert any("evidence_stale" in e for e in res.findings.evidence_errors)


def test_neg_p0_08_mandatory_gate_skipped_blocks_pass(tmp_path: Path):
    """NEG-P0-08: When a mandatory gate is SKIPPED, acceptance status MUST be BLOCKED, deliverable False."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_neg8")
    manifest = build_evidence_manifest_v2(
        run_id="p0_neg8",
        case_id="case_neg8",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    # Contact domain requires contact_diagnostics gate. If not provided and not evaluated,
    # it must NOT silently pass even if stress criteria passes.
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"contact_pressure": 30.0, "frictional_shear": 5.0, "reaction_force": 1000.0, "max_mises": 100.0},
        criteria=[{"name": "mises", "value_key": "max_mises", "operator": "<=", "limit": 200.0}],
        physics_domain="contact",
        contact_diagnostics=None,  # skipped mandatory gate
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert res.acceptance_status == "BLOCKED"
    assert res.result_validity == "VALID"
    assert res.deliverable is False
    assert any("missing_mandatory_gate:contact_diagnostics" in b for b in res.findings.blocked)


# =========================================================================
# Positive Baseline Probes (POS-P0-01 ~ POS-P0-03)
# =========================================================================

def test_pos_p0_01_standard_golden_pass(tmp_path: Path):
    """POS-P0-01: Authentic evidence, completed solver, passing criteria & gates -> PASS & deliverable=True."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_pos1")
    manifest = build_evidence_manifest_v2(
        run_id="p0_pos1",
        case_id="case_pos1",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_displacement": 0.5, "max_mises": 120.0, "reaction_force": 1000.0},
        criteria=[{"name": "disp", "value_key": "max_displacement", "operator": "<", "limit": 1.0}],
        physics_domain="static",
        odb_fields=["U", "S", "RF"],
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert res.acceptance_status == "PASS"
    assert res.status == "PASS"
    assert res.passed is True
    assert res.result_validity == "VALID"
    assert res.deliverable is True
    assert len(res.findings.failures) == 0
    assert len(res.findings.blocked) == 0


def test_pos_p0_02_pure_mechanical_fail_with_valid_evidence(tmp_path: Path):
    """POS-P0-02: Authentic evidence and completed solver, but stress exceeds allowable -> FAIL & deliverable=False."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_pos2")
    manifest = build_evidence_manifest_v2(
        run_id="p0_pos2",
        case_id="case_pos2",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_displacement": 0.5, "max_mises": 280.0, "reaction_force": 1000.0},
        criteria=[{"name": "mises", "value_key": "max_mises", "operator": "<", "limit": 200.0}],
        physics_domain="static",
        odb_fields=["U", "S", "RF"],
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert res.acceptance_status == "FAIL"
    assert res.status == "FAIL"
    assert res.passed is False
    assert res.result_validity == "VALID"
    assert res.deliverable is False
    assert len(res.findings.failures) > 0
    assert len(res.findings.blocked) == 0


def test_pos_p0_03_corrupt_evidence_never_yields_mechanical_fail(tmp_path: Path):
    """POS-P0-03: Corrupt evidence must NOT yield physical FAIL; must yield RESULT_INVALID."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_pos3")
    manifest = build_evidence_manifest_v2(
        run_id="p0_pos3",
        case_id="case_pos3",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )
    # Corrupt an artifact
    (tmp_path / "Job_p0_pos3.msg").write_bytes(b"CORRUPTED")

    # Even if max_mises is 500.0 (which would be fail if data was valid),
    # since evidence is corrupt, the system MUST NOT claim a valid mechanical failure.
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_mises": 500.0},
        criteria=[{"name": "mises", "value_key": "max_mises", "operator": "<", "limit": 200.0}],
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "EVIDENCE_TAMPERED"
    assert res.deliverable is False
