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
