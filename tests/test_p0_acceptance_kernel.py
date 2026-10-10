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

import dataclasses
import hashlib
import json
from pathlib import Path
import pytest

from abaqus_ai_agent.acceptance import (
    AcceptanceFindings,
    AcceptanceResult,
    evaluate_criteria,
    evaluate_production_acceptance,
    evaluate_result_acceptance,
)
from abaqus_ai_agent.contracts.evidence import build_evidence_manifest_v2, verify_evidence_integrity, compute_file_sha256
from abaqus_ai_agent.execution.jobs import JobStatus, JobState
from abaqus_ai_agent.contracts.metrics import EngineeringMetric
from abaqus_ai_agent.contracts.provenance import AnalysisProvenance
from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState


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


# =========================================================================
# P0-B & P0-C Specific Verification Suites
# =========================================================================

def test_p0_b_audit_signature_canonicalization_and_metadata_tamper(tmp_path: Path):
    """P0-B: Verify that canonical audit_signature protects all manifest fields including metadata."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_b_sig")
    manifest = build_evidence_manifest_v2(
        run_id="p0_b_sig",
        case_id="case_b_sig",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
        metadata={"domain_policy": "strict_v1"},
    )
    assert manifest.verify_signature() is True

    # 1. Tampering metadata must invalidate signature
    manifest.metadata["domain_policy"] = "loose_v0"
    assert manifest.verify_signature() is False
    manifest.metadata["domain_policy"] = "strict_v1"
    assert manifest.verify_signature() is True

    # 2. Tampering case_id must invalidate signature
    manifest.case_id = "forged_case"
    assert manifest.verify_signature() is False
    manifest.case_id = "case_b_sig"
    assert manifest.verify_signature() is True

    # 3. Tampering artifact record must invalidate signature
    old_art = manifest.artifacts["Job_p0_b_sig.sta"]
    manifest.artifacts["Job_p0_b_sig.sta"] = dataclasses.replace(old_art, sha256="0" * 64)
    assert manifest.verify_signature() is False


def test_p0_b_layer1_odb_empty_and_script_probe(tmp_path: Path):
    """P0-B: Layer 1 ODB probe rejects empty files and scripts disguised as ODB as EVIDENCE_CORRUPT."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_b_probe")

    # 1. Empty ODB file
    empty_odb = tmp_path / "Job_p0_b_probe.odb"
    empty_odb.write_bytes(b"")
    manifest = build_evidence_manifest_v2(
        run_id="p0_b_probe",
        case_id="case_b_probe",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )
    rep = verify_evidence_integrity(manifest, base_dir=str(tmp_path))
    assert rep.valid is False
    assert rep.validity == "EVIDENCE_CORRUPT"
    assert any("corrupt_artifact:odb_file_empty" in f for f in rep.failures)

    # 2. Python script disguised as ODB
    empty_odb.write_bytes(b"import abaqus\ndef main(): pass\n")
    manifest2 = build_evidence_manifest_v2(
        run_id="p0_b_probe",
        case_id="case_b_probe",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )
    rep2 = verify_evidence_integrity(manifest2, base_dir=str(tmp_path))
    assert rep2.valid is False
    assert rep2.validity == "EVIDENCE_CORRUPT"
    assert any("corrupt_artifact:odb_is_script" in f for f in rep2.failures)


def test_p0_c_production_acceptance_golden_path(tmp_path: Path):
    """P0-C: Production acceptance succeeds with full causal binding and delivers True."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_c_gold")
    manifest = build_evidence_manifest_v2(
        run_id="p0_c_gold",
        case_id="case_c_gold",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )
    inp_sha = manifest.artifacts["Job_p0_c_gold.inp"].sha256

    run = AnalysisRun(
        id="p0_c_gold",
        model_name="Model_Golden",
        job_name="Job_p0_c_gold",
        state=AnalysisRunState.COMPLETED,
        job_status=JobStatus(name="Job_p0_c_gold", state=JobState.COMPLETED),
        odb_path=str(tmp_path / "Job_p0_c_gold.odb"),
        provenance=AnalysisProvenance(
            run_id="p0_c_gold",
            model_name="Model_Golden",
            job_name="Job_p0_c_gold",
            input_hash=inp_sha,
        ),
        metrics=(
            EngineeringMetric(name="max_mises", value=150.0, unit="MPa"),
            EngineeringMetric(name="reaction_force", value=1000.0, unit="N"),
            EngineeringMetric(name="max_displacement", value=0.5, unit="mm"),
        ),
    )

    res = evaluate_production_acceptance(
        run,
        criteria=[
            {"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 200.0},
        ],
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        physics_domain="static",
        odb_fields=["U", "S", "RF"],
    )

    assert res.acceptance_status == "PASS"
    assert res.status == "PASS"
    assert res.passed is True
    assert res.result_validity == "VALID"
    assert res.deliverable is True


def test_p0_c_production_acceptance_forbids_require_evidence_false():
    """P0-C: Production acceptance strictly raises ValueError if caller attempts require_evidence=False."""
    with pytest.raises(ValueError, match="strictly forbids disabling evidence"):
        evaluate_production_acceptance(require_evidence=False)


def test_p0_c_production_acceptance_input_hash_mismatch(tmp_path: Path):
    """P0-C: Input hash mismatch between AnalysisRun provenance and manifest INP artifact causes EVIDENCE_TAMPERED."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_c_inp_tamper")
    manifest = build_evidence_manifest_v2(
        run_id="p0_c_inp_tamper",
        case_id="case_inp_tamper",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    run = AnalysisRun(
        id="p0_c_inp_tamper",
        model_name="Model_Inp",
        job_name="Job_p0_c_inp_tamper",
        state=AnalysisRunState.COMPLETED,
        job_status=JobStatus(name="Job_p0_c_inp_tamper", state=JobState.COMPLETED),
        odb_path=str(tmp_path / "Job_p0_c_inp_tamper.odb"),
        provenance=AnalysisProvenance(
            run_id="p0_c_inp_tamper",
            model_name="Model_Inp",
            job_name="Job_p0_c_inp_tamper",
            input_hash="deadbeef" * 8,  # Does not match live INP sha256!
        ),
        metrics=(EngineeringMetric(name="max_mises", value=150.0, unit="MPa"),),
    )

    res = evaluate_production_acceptance(
        run,
        criteria=[{"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 200.0}],
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "EVIDENCE_TAMPERED"
    assert res.deliverable is False
    assert any("input_hash_mismatch" in e for e in res.findings.evidence_errors)


def test_p0_c_production_acceptance_run_id_mismatch(tmp_path: Path):
    """P0-C: Run ID mismatch between AnalysisRun and Manifest triggers EVIDENCE_STALE."""
    files = _create_standard_mock_artifacts(tmp_path, "run_manifest_A")
    manifest = build_evidence_manifest_v2(
        run_id="run_manifest_A",
        case_id="case_A",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    run = AnalysisRun(
        id="run_expected_B",  # Mismatch!
        model_name="Model_B",
        job_name="Job_B",
        state=AnalysisRunState.COMPLETED,
        job_status=JobStatus(name="Job_B", state=JobState.COMPLETED),
        odb_path=str(tmp_path / "Job_run_manifest_A.odb"),
        metrics=(EngineeringMetric(name="max_mises", value=150.0, unit="MPa"),),
    )

    res = evaluate_production_acceptance(
        run,
        criteria=[{"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 200.0}],
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "EVIDENCE_STALE"
    assert res.deliverable is False
    assert any("evidence_stale" in e for e in res.findings.evidence_errors)


def test_p0_c_production_acceptance_unsubmitted_job(tmp_path: Path):
    """P0-C: Unsubmitted / probe-only job status is rejected as solver_execution failure in production."""
    files = _create_standard_mock_artifacts(tmp_path, "run_unsubmitted")
    manifest = build_evidence_manifest_v2(
        run_id="run_unsubmitted",
        case_id="case_unsub",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    run = AnalysisRun(
        id="run_unsubmitted",
        model_name="Model_Unsub",
        job_name="Job_Unsub",
        state=AnalysisRunState.PREFLIGHTED,
        job_status=JobStatus(name="Job_Unsub", state=JobState.CREATED),
        metrics=(EngineeringMetric(name="max_mises", value=150.0, unit="MPa"),),
    )

    res = evaluate_production_acceptance(
        run,
        criteria=[{"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 200.0}],
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.deliverable is False
    assert any("solver_execution" in e for e in res.findings.evidence_errors)


def test_p0_c_production_acceptance_rejects_external_input(tmp_path: Path):
    """P0-C: AnalysisRun marked with result_source='external_input' is strictly prohibited from production deliverable."""
    files = _create_standard_mock_artifacts(tmp_path, "run_ext_input")
    manifest = build_evidence_manifest_v2(
        run_id="run_ext_input",
        case_id="case_ext",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    run = AnalysisRun(
        id="run_ext_input",
        model_name="Model_Ext",
        job_name="Job_Ext",
        state=AnalysisRunState.COMPLETED,
        job_status=JobStatus(name="Job_Ext", state=JobState.COMPLETED),
        metadata={"result_source": "external_input"},
        metrics=(EngineeringMetric(name="max_mises", value=150.0, unit="MPa"),),
    )

    res = evaluate_production_acceptance(
        run,
        criteria=[{"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 200.0}],
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
    )

    assert res.deliverable is False
    assert any("external_input_disallowed_in_production" in e for e in res.findings.evidence_errors)


# =========================================================================
# P0-D Delivery Exit Gate & Reporting Closure
# =========================================================================

def test_p0_d_report_pipeline_deliverable_gating_blocks_undeliverable_run(tmp_path: Path):
    """P0-D: DeterministicReportPipeline with require_deliverable=True raises PermissionError on deliverable=False."""
    pipeline = DeterministicReportPipeline()
    out_dir = tmp_path / "report_out"

    # Simulated acceptance result with deliverable=False
    failed_acc = AcceptanceResult(
        passed=False,
        criteria=(),
        status="FAIL",
        acceptance_status="FAIL",
        result_validity="VALID",
        deliverable=False,
        findings=AcceptanceFindings(failures=("criteria_exceeded:max_mises",)),
    )

    with pytest.raises(PermissionError, match="Official engineering delivery blocked: deliverable is False"):
        pipeline.build_and_render(
            output_dir=out_dir,
            title="Bolted Flange Test Report",
            case_id="case_p0_d",
            run_id="run_p0_d",
            model_info={"max_mises_mpa": 350.0},
            results_info=(),
            acceptance_info=failed_acc,
            require_deliverable=True,
        )


def test_p0_d_report_delivery_card_reflects_deliverable_status(tmp_path: Path):
    """P0-D: ReportDeliveryCard captures deliverable status correctly for both pass and fail runs."""
    pipeline = DeterministicReportPipeline()
    out_dir = tmp_path / "report_out2"

    passed_acc = AcceptanceResult(
        passed=True,
        criteria=(),
        status="PASS",
        acceptance_status="PASS",
        result_validity="VALID",
        deliverable=True,
        findings=AcceptanceFindings(),
    )

    card, pointer, data = pipeline.build_and_render(
        output_dir=out_dir,
        title="Flange Passing Report",
        case_id="case_p0_d_pass",
        run_id="run_p0_d_pass",
        model_info={"max_mises_mpa": 120.0},
        results_info=(),
        acceptance_info=passed_acc,
        require_deliverable=False,
    )

    assert card.deliverable is True
    assert card.to_llm_card()["deliverable"] is True


def test_p0_c_production_acceptance_rejects_missing_analysis_run(tmp_path: Path):
    """P0-C: Calling evaluate_production_acceptance with analysis_run=None is strictly blocked."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_c_no_run")
    manifest = build_evidence_manifest_v2(
        run_id="p0_c_no_run",
        case_id="case_no_run",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    res = evaluate_production_acceptance(
        analysis_run=None,
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        criteria=[{"name": "mises", "value_key": "max_mises", "operator": "<=", "limit": 200.0}],
    )

    assert res.acceptance_status in ("BLOCKED", "RESULT_INVALID")
    assert res.deliverable is False
    assert any("missing_analysis_run" in e for e in res.findings.evidence_errors)


def test_p0_c_production_acceptance_rejects_missing_job_status(tmp_path: Path):
    """P0-C: AnalysisRun without job status is rejected as missing_job_status; never defaults to completed."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_c_no_status")
    manifest = build_evidence_manifest_v2(
        run_id="p0_c_no_status",
        case_id="case_no_status",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )
    inp_sha = manifest.artifacts["Job_p0_c_no_status.inp"].sha256

    run = AnalysisRun(
        id="p0_c_no_status",
        model_name="Model_NoStatus",
        job_name="Job_p0_c_no_status",
        state=None,  # No state
        job_status=None,  # No job status
        odb_path=str(tmp_path / "Job_p0_c_no_status.odb"),
        provenance=AnalysisProvenance(
            run_id="p0_c_no_status",
            model_name="Model_NoStatus",
            job_name="Job_p0_c_no_status",
            input_hash=inp_sha,
        ),
        metrics=(EngineeringMetric(name="max_mises", value=150.0, unit="MPa"),),
    )

    res = evaluate_production_acceptance(
        run,
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        criteria=[{"name": "mises", "value_key": "max_mises", "operator": "<=", "limit": 200.0}],
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "SOLVER_FAILED"
    assert res.deliverable is False
    assert any("solver_execution:missing_job_status" in e for e in res.findings.evidence_errors)


def test_p0_c_production_acceptance_rejects_missing_input_hash(tmp_path: Path):
    """P0-C: AnalysisRun lacking input hash in provenance is blocked as missing_input_hash."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_c_no_inp_hash")
    manifest = build_evidence_manifest_v2(
        run_id="p0_c_no_inp_hash",
        case_id="case_no_inp_hash",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    run = AnalysisRun(
        id="p0_c_no_inp_hash",
        model_name="Model_NoHash",
        job_name="Job_p0_c_no_inp_hash",
        state=AnalysisRunState.COMPLETED,
        job_status=JobStatus(name="Job_p0_c_no_inp_hash", state=JobState.COMPLETED),
        odb_path=str(tmp_path / "Job_p0_c_no_inp_hash.odb"),
        provenance=None,  # No provenance / no input_hash
        metrics=(EngineeringMetric(name="max_mises", value=150.0, unit="MPa"),),
    )

    res = evaluate_production_acceptance(
        run,
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        criteria=[{"name": "mises", "value_key": "max_mises", "operator": "<=", "limit": 200.0}],
    )

    assert res.acceptance_status == "BLOCKED"
    assert res.result_validity == "INCOMPLETE"
    assert res.deliverable is False
    assert any("missing_input_hash" in e for e in res.findings.evidence_errors)


def test_p0_c_production_acceptance_rejects_missing_inp_artifact(tmp_path: Path):
    """P0-C: EvidenceManifest lacking role='inp' artifact is blocked as missing_inp_artifact."""
    # Create artifacts omitting .inp
    files = ["Job_no_inp.odb", "Job_no_inp.sta", "Job_no_inp.dat"]
    for fn in files:
        fp = tmp_path / fn
        if fn.endswith(".odb"):
            fp.write_bytes(b"\x00\x00\x00\x00" + b"\x53\x49\x4d" + b"\x00" * 2000)
        else:
            fp.write_text("dummy artifact content\n", encoding="utf-8")

    manifest = build_evidence_manifest_v2(
        run_id="p0_c_no_inp_art",
        case_id="case_no_inp_art",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )

    run = AnalysisRun(
        id="p0_c_no_inp_art",
        model_name="Model_NoInpArt",
        job_name="Job_no_inp",
        state=AnalysisRunState.COMPLETED,
        job_status=JobStatus(name="Job_no_inp", state=JobState.COMPLETED),
        odb_path=str(tmp_path / "Job_no_inp.odb"),
        provenance=AnalysisProvenance(
            run_id="p0_c_no_inp_art",
            model_name="Model_NoInpArt",
            job_name="Job_no_inp",
            input_hash="a" * 64,
        ),
        metrics=(EngineeringMetric(name="max_mises", value=150.0, unit="MPa"),),
    )

    res = evaluate_production_acceptance(
        run,
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        criteria=[{"name": "mises", "value_key": "max_mises", "operator": "<=", "limit": 200.0}],
    )

    assert res.acceptance_status == "BLOCKED"
    assert res.result_validity == "INCOMPLETE"
    assert res.deliverable is False
    assert any("missing_inp_artifact" in e for e in res.findings.evidence_errors)


def test_p0_d_report_pipeline_defaults_to_strict_deliverable_rejection(tmp_path: Path):
    """P0-D: pipeline.build_and_render defaults to require_deliverable=True and raises PermissionError without explicit argument."""
    pipeline = DeterministicReportPipeline()
    out_dir = tmp_path / "report_strict_default"

    failed_acc = AcceptanceResult(
        passed=False,
        criteria=(),
        status="FAIL",
        acceptance_status="FAIL",
        result_validity="VALID",
        deliverable=False,
        findings=AcceptanceFindings(failures=("criteria_exceeded:max_mises",)),
    )

    # Note: caller does NOT pass require_deliverable; it must default to True and fail closed!
    with pytest.raises(PermissionError, match="Official engineering delivery blocked: deliverable is False"):
        pipeline.build_and_render(
            output_dir=out_dir,
            title="Strict Default Delivery Test",
            case_id="case_strict_default",
            run_id="run_strict_default",
            model_info={"max_mises_mpa": 350.0},
            results_info=(),
            acceptance_info=failed_acc,
        )


def test_p0_d_report_pipeline_rejects_empty_or_unauthorized_acceptance(tmp_path: Path):
    """P0-D: Passing a bare dict with only status='PASS' or empty info is rejected by default as deliverable=False."""
    pipeline = DeterministicReportPipeline()
    out_dir = tmp_path / "report_bare_dict"

    with pytest.raises(PermissionError, match="Official engineering delivery blocked: deliverable is False"):
        pipeline.build_and_render(
            output_dir=out_dir,
            title="Bare Dict Rejection",
            case_id="case_bare_dict",
            run_id="run_bare_dict",
            model_info={"max_mises_mpa": 120.0},
            results_info=(),
            acceptance_info={"status": "PASS"},  # No deliverable: True authorization
        )


def test_p0_d_report_pipeline_early_gate_prevents_any_disk_write(tmp_path: Path):
    """P0-D: Early gate blocks unauthorized delivery BEFORE writing any files to disk."""
    pipeline = DeterministicReportPipeline()
    out_dir = tmp_path / "report_no_leak_dir"

    unauthorized_acc = AcceptanceResult(
        passed=False,
        criteria=(),
        status="BLOCKED",
        acceptance_status="BLOCKED",
        result_validity="INCOMPLETE",
        deliverable=False,
        findings=AcceptanceFindings(blocked=("missing_mandatory_gate",)),
    )

    with pytest.raises(PermissionError, match="No report artifacts were written to disk"):
        pipeline.build_and_render(
            output_dir=out_dir,
            title="Unwritten Report",
            case_id="case_unwritten",
            run_id="run_unwritten",
            model_info={"max_mises_mpa": 100.0},
            results_info=(),
            acceptance_info=unauthorized_acc,
            require_deliverable=True,
        )

    # Verify zero report artifacts or images leaked to disk
    if out_dir.exists():
        leaked_files = list(out_dir.glob("*"))
        assert len(leaked_files) == 0, f"Leaked artifacts on disk after delivery block: {leaked_files}"


def test_p0_d_report_pipeline_diagnostic_draft_mode_isolation(tmp_path: Path):
    """P0-D: Diagnostic draft mode explicitly labels non-deliverable reports and isolates them from official delivery."""
    pipeline = DeterministicReportPipeline()
    out_dir = tmp_path / "report_diagnostic_dir"

    failed_acc = AcceptanceResult(
        passed=False,
        criteria=(),
        status="FAIL",
        acceptance_status="FAIL",
        result_validity="VALID",
        deliverable=False,
        findings=AcceptanceFindings(failures=("criteria_exceeded",)),
    )

    # Diagnostic mode allowed only when require_deliverable=False is explicitly passed
    card, pointer, data = pipeline.build_and_render(
        output_dir=out_dir,
        title="Flange Failure Investigation",
        case_id="case_diag",
        run_id="run_diag",
        model_info={"max_mises_mpa": 450.0},
        results_info=(),
        acceptance_info=failed_acc,
        require_deliverable=False,
    )

    assert card.deliverable is False
    assert "[DIAGNOSTIC / NON-DELIVERABLE DRAFT]" in card.report_title
    assert pointer.metadata["delivery_mode"] == "diagnostic_draft"
    assert pointer.metadata["is_diagnostic_draft"] is True


def test_p0_c_production_acceptance_rejects_caller_overriding_run_input_hash(tmp_path: Path):
    """P0-C: Caller cannot override AnalysisRun input_hash with conflicting expected_input_hash."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_c_override")
    manifest = build_evidence_manifest_v2(
        run_id="p0_c_override",
        case_id="case_override",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )
    inp_sha = manifest.artifacts["Job_p0_c_override.inp"].sha256

    run = AnalysisRun(
        id="p0_c_override",
        model_name="Model_Override",
        job_name="Job_p0_c_override",
        state=AnalysisRunState.COMPLETED,
        job_status=JobStatus(name="Job_p0_c_override", state=JobState.COMPLETED),
        odb_path=str(tmp_path / "Job_p0_c_override.odb"),
        provenance=AnalysisProvenance(
            run_id="p0_c_override",
            model_name="Model_Override",
            job_name="Job_p0_c_override",
            input_hash=inp_sha,  # Authentic run provenance hash
        ),
        metrics=(EngineeringMetric(name="max_mises", value=150.0, unit="MPa"),),
    )

    # Caller attempts to supply conflicting expected_input_hash
    res = evaluate_production_acceptance(
        run,
        expected_input_hash="f" * 64,  # Conflicting hash!
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        criteria=[{"name": "mises", "value_key": "max_mises", "operator": "<=", "limit": 200.0}],
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "EVIDENCE_TAMPERED"
    assert res.deliverable is False
    assert any("caller_input_hash_conflict" in e for e in res.findings.evidence_errors)


def test_p0_c_production_acceptance_run_hash_tampered_even_if_caller_provides_matching_expected_hash(tmp_path: Path):
    """P0-C: If AnalysisRun provenance hash is tampered, caller providing manifest hash still fails."""
    files = _create_standard_mock_artifacts(tmp_path, "p0_c_tampered_run")
    manifest = build_evidence_manifest_v2(
        run_id="p0_c_tampered_run",
        case_id="case_tampered_run",
        artifacts_dir=str(tmp_path),
        artifact_filenames=files,
    )
    inp_sha = manifest.artifacts["Job_p0_c_tampered_run.inp"].sha256

    run = AnalysisRun(
        id="p0_c_tampered_run",
        model_name="Model_TamperedRun",
        job_name="Job_p0_c_tampered_run",
        state=AnalysisRunState.COMPLETED,
        job_status=JobStatus(name="Job_p0_c_tampered_run", state=JobState.COMPLETED),
        odb_path=str(tmp_path / "Job_p0_c_tampered_run.odb"),
        provenance=AnalysisProvenance(
            run_id="p0_c_tampered_run",
            model_name="Model_TamperedRun",
            job_name="Job_p0_c_tampered_run",
            input_hash="9" * 64,  # Tampered provenance hash!
        ),
        metrics=(EngineeringMetric(name="max_mises", value=150.0, unit="MPa"),),
    )

    # Caller passes the true manifest inp_sha, but AnalysisRun provenance is tampered
    res = evaluate_production_acceptance(
        run,
        expected_input_hash=inp_sha,
        evidence_manifest=manifest,
        base_dir=str(tmp_path),
        criteria=[{"name": "mises", "value_key": "max_mises", "operator": "<=", "limit": 200.0}],
    )

    assert res.acceptance_status == "RESULT_INVALID"
    assert res.result_validity == "EVIDENCE_TAMPERED"
    assert res.deliverable is False
    assert any("caller_input_hash_conflict" in e or "input_hash_mismatch" in e for e in res.findings.evidence_errors)


def test_p0_d_legacy_dict_with_passed_true_blocked_without_explicit_deliverable(tmp_path: Path):
    """P0-D-1: Legacy acceptance dict with passed=True but lacking explicit deliverable=True is strictly blocked."""
    pipeline = DeterministicReportPipeline()
    out_dir = tmp_path / "report_legacy_dict_blocked"

    with pytest.raises(PermissionError, match="deliverable is False"):
        pipeline.build_and_render(
            output_dir=out_dir,
            title="Legacy Dict Official Attempt",
            case_id="case_legacy_blocked",
            run_id="run_legacy_blocked",
            model_info={"max_mises_mpa": 120.0},
            results_info=(),
            acceptance_info={"status": "PASS", "passed": True},  # Missing deliverable: True
            require_deliverable=True,
        )


def test_p0_d_diagnostic_draft_mode_renders_html_banner_and_title(tmp_path: Path):
    """P0-D-2: Diagnostic draft mode embeds explicit banner and title tag in actual rendered HTML body."""
    pipeline = DeterministicReportPipeline()
    out_dir = tmp_path / "report_diagnostic_html_check"

    failed_acc = AcceptanceResult(
        passed=False,
        criteria=(),
        status="FAIL",
        acceptance_status="FAIL",
        result_validity="VALID",
        deliverable=False,
        findings=AcceptanceFindings(failures=("criteria_exceeded:max_mises",)),
    )

    card, pointer, data = pipeline.build_and_render(
        output_dir=out_dir,
        title="Diagnostic Stress Report",
        case_id="case_diag_html",
        run_id="run_diag_html",
        model_info={"max_mises_mpa": 450.0},
        results_info=(),
        acceptance_info=failed_acc,
        require_deliverable=False,
    )

    html_file = out_dir / "report.html"
    assert html_file.exists()
    html_content = html_file.read_text(encoding="utf-8")

    # Assert explicit diagnostic banners exist in generated HTML
    assert "[DIAGNOSTIC / NON-DELIVERABLE DRAFT]" in html_content
    assert "diagnostic-banner" in html_content
    assert "DIAGNOSTIC NON-DELIVERABLE DRAFT" in html_content


def test_p0_d_missing_cae_visualization_asset_blocks_official_delivery_without_synthetic_fallback(tmp_path: Path):
    """P0-D-3: Missing required CAE visualization image fails closed (FileNotFoundError); never generates synthetic fallback."""
    from abaqus_ai_agent.reporting.visualization_spec import VisualizationSpec

    pipeline = DeterministicReportPipeline()
    out_dir = tmp_path / "report_missing_vis_asset"

    passed_acc = AcceptanceResult(
        passed=True,
        criteria=(),
        status="PASS",
        acceptance_status="PASS",
        result_validity="VALID",
        deliverable=True,
        findings=AcceptanceFindings(),
    )

    non_existent_img_name = "non_existent_mises_contour.png"
    specs = [
        VisualizationSpec(
            artifact_id="FIG-S-001",
            visualization_type="stress_hotspot",
            field_name="S",
            component="mises",
            target_filename=non_existent_img_name,
            caption_zh="Mises 应力云图",
            caption_en="von Mises Stress Contour",
        )
    ]

    with pytest.raises(FileNotFoundError, match="Official engineering delivery blocked: required CAE visualization asset"):
        pipeline.build_and_render(
            output_dir=out_dir,
            title="Official Report Missing Asset",
            case_id="case_missing_asset",
            run_id="run_missing_asset",
            model_info={"max_mises_mpa": 120.0},
            results_info=(),
            acceptance_info=passed_acc,
            visualization_specs=specs,
            require_deliverable=True,
        )

    # Fail-closed guarantee: zero report files written to output_dir
    if out_dir.exists():
        assert len(list(out_dir.glob("*.html"))) == 0


def test_p0_d_authentic_cae_visualization_asset_succeeds_in_official_delivery(tmp_path: Path):
    """P0-D-4: Official delivery succeeds when authentic CAE image file is verified on disk."""
    from abaqus_ai_agent.reporting.visualization_spec import VisualizationSpec

    pipeline = DeterministicReportPipeline()
    out_dir = tmp_path / "report_authentic_vis_asset"

    passed_acc = AcceptanceResult(
        passed=True,
        criteria=(),
        status="PASS",
        acceptance_status="PASS",
        result_validity="VALID",
        deliverable=True,
        findings=AcceptanceFindings(),
    )

    # Provide authentic CAE image artifact on disk
    from abaqus_ai_agent.execution.odb_rendering import MINIMAL_VALID_PNG_BYTES
    authentic_filename = "authentic_odb_contour.png"
    authentic_img = tmp_path / "report_authentic_vis_asset" / authentic_filename
    out_dir.mkdir(parents=True, exist_ok=True)
    authentic_img.write_bytes(MINIMAL_VALID_PNG_BYTES)

    specs = [
        VisualizationSpec(
            artifact_id="FIG-S-002",
            visualization_type="stress_hotspot",
            field_name="S",
            component="mises",
            target_filename=authentic_filename,
            caption_zh="Mises 应力云图",
            caption_en="von Mises Stress Contour",
            output_position="INTEGRATION_POINT",
        )
    ]

    h_img = hashlib.sha256(authentic_img.read_bytes()).hexdigest()
    mock_odb = tmp_path / "authentic.odb"
    mock_odb.write_bytes(b"\x7fSIMULIA_ODB_BINARY_HEADER" + b"\x00" * 1024)
    h_odb = hashlib.sha256(mock_odb.read_bytes()).hexdigest()
    auth_input_hash = "INP-AUTH-ASSET-01"

    fig = specs[0].to_report_figure(str(authentic_img.as_posix()))
    fig.metadata["image_sha256"] = h_img
    fig.metadata["sha256"] = h_img
    fig.metadata["run_id"] = "run_authentic_asset"
    fig.metadata["input_hash"] = auth_input_hash
    fig.metadata["odb_sha256"] = h_odb
    fig.metadata["field"] = specs[0].field_name
    fig.metadata["component"] = specs[0].component
    from abaqus_ai_agent.execution.odb_rendering import (
        compute_viewer_session_token,
        create_render_execution_evidence,
    )
    auth_nonce = "0123456789abcdef0123456789abcdef"
    auth_token = compute_viewer_session_token(
        session_nonce=auth_nonce,
        run_id="run_authentic_asset",
        odb_sha256=h_odb,
        target_filename=authentic_img.name,
        image_sha256=h_img,
    )
    auth_ev = create_render_execution_evidence(
        session_nonce=auth_nonce,
        run_id="run_authentic_asset",
        odb_sha256=h_odb,
        input_hash=auth_input_hash,
        rendered_figures=[{"filename": authentic_img.name, "image_sha256": h_img}],
    )
    fig.metadata["output_position"] = "INTEGRATION_POINT"
    fig.metadata["viewer_rendered"] = True
    fig.metadata["session_nonce"] = auth_nonce
    fig.metadata["viewer_session_token"] = auth_token
    fig.metadata["render_execution_evidence"] = auth_ev.to_dict()

    card, pointer, data = pipeline.build_and_render(
        output_dir=out_dir,
        title="Official Authentic Delivery",
        case_id="case_authentic_asset",
        run_id="run_authentic_asset",
        input_hash=auth_input_hash,
        odb_path=mock_odb,
        model_info={"max_mises_mpa": 120.0},
        results_info=(),
        acceptance_info=passed_acc,
        visualization_specs=specs,
        figures=[fig],
        require_deliverable=True,
    )

    assert card.deliverable is True
    assert len(data.figures) == 1
    assert Path(data.figures[0].path) == authentic_img
    # Ensure no synthetic transient_evolution.gif was forced
    assert not any(fig.path.endswith("transient_evolution.gif") for fig in data.figures)
