#!/usr/bin/env python3
"""GA-CL.4: Evidence / Provenance V2 Qualification E2E.

Proves:
1. Unified EvidenceManifestV2 contract binding:
   - run_id, case_id, created_at, environment, intent, required_results,
     artifacts (with live SHA-256 and sizes), verification, acceptance, provenance.
2. Run Identity Binding:
   - Prohibits reusing older/mismatched runs (expected_run_id mismatch -> EVIDENCE_STALE).
3. Live Artifact Integrity:
   - Byte-level tampering detection (ODB or INP mutation -> EVIDENCE_TAMPERED).
   - Missing mandatory solver artifacts (.sta/.odb/.msg -> EVIDENCE_INCOMPLETE).
4. Stale Evidence Protection:
   - Enforces time freshness (max_age_seconds exceeded -> EVIDENCE_STALE).
5. Strong Acceptance Gate Binding:
   - Any evidence failure (tampered, incomplete, stale) forces:
     * gates["evidence_sufficiency"] = "FAIL"
     * status = "BLOCKED"
     * result_validity = "RESULT_INVALID"
     * passed = False
     * audit_summary displays Engineering Acceptance: FAIL
6. Report Synchronization:
   - Engineering report displays artifact provenance table and audit signature.
   - On evidence failure, report explicitly marks REJECTED (EVIDENCE_INVALID).
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.evidence import (
    DEFAULT_MANDATORY_ROLES,
    ArtifactRecord,
    EvidenceManifestV2,
    EvidenceVerificationReport,
    build_evidence_manifest_v2,
    compute_file_sha256,
    verify_evidence_integrity,
)
from abaqus_ai_agent.contracts.report import EngineeringReportData
from abaqus_ai_agent.reporting.renderer import render_markdown


def run_evidence_v2_qualification() -> Dict[str, Any]:
    manifest_results: Dict[str, Any] = {
        "schema_version": "evidence_v2_manifest_v1",
        "milestone": "GA-CL.4",
        "qualified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "qualification_tier": "REAL_ABAQUS_PROVENANCE_V2",
        "all_vectors_passed": False,
        "vectors_count": 7,
        "vectors": {},
    }

    # Locate real Abaqus 2025 solver artifacts from GA-2.6.3 Golden
    ga263_dir = ROOT / "machine_validation" / "ga263_workdir" / "GA263_Golden_Case"
    mandatory_fnames = [
        "GA263_Job.inp",
        "GA263_Job.odb",
        "GA263_Job.sta",
        "GA263_Job.msg",
        "GA263_Job.dat",
        "GA263_Job.log",
    ]
    for fname in mandatory_fnames:
        fpath = ga263_dir / fname
        if not fpath.is_file():
            raise FileNotFoundError(f"Missing real machine artifact: {fpath}")

    # =========================================================================
    # Vector 1: Valid EvidenceManifestV2 Creation & Verification
    # =========================================================================
    run_id_v1 = "run_ga263_20261004_v2_qualified"
    case_id_v1 = "GA-2.6.3_BoltPreloadTorque"
    created_at_v1 = datetime.datetime.now(datetime.timezone.utc).isoformat()

    values_v1 = {"preload_force": 5000.0, "axial_reaction": 2000.0, "torque_reaction": 100000.0}
    criteria_v1 = [
        {"name": "preload_force", "value_key": "preload_force", "operator": "<=", "limit": 6000.0},
        {"name": "torque_reaction", "value_key": "torque_reaction", "operator": "<=", "limit": 120000.0},
    ]

    manifest_v1 = build_evidence_manifest_v2(
        run_id=run_id_v1,
        case_id=case_id_v1,
        artifacts_dir=ga263_dir,
        artifact_filenames=mandatory_fnames,
        intent_summary={
            "model_name": "GA263_BoltModel",
            "job_name": "GA263_Job",
            "physics_domain": "multi_step",
            "steps": ["Step-Preload", "Step-Service"],
            "procedure": "bolt_pretension_fix_length_torque",
        },
        required_results={
            "required_fields": ["U", "S", "RF", "RM"],
            "required_metrics": ["preload_force", "axial_reaction", "torque_reaction"],
            "required_gates": ["execution", "odb", "procedure", "required_results", "evidence_sufficiency"],
        },
        verification={
            "preload_force_error": 1.53e-8,
            "torque_reaction_error": 9.16e-9,
            "procedure_verified": True,
        },
        acceptance={
            "passed": True,
            "status": "PASS",
            "result_validity": "VALID",
        },
        provenance={
            "solver": "Abaqus 2025 Standard",
            "host_os": "windows",
            "qualification": "REAL_ABAQUS",
        },
        created_at=created_at_v1,
    )

    verif_v1 = verify_evidence_integrity(
        manifest_v1,
        base_dir=ga263_dir,
        expected_run_id=run_id_v1,
        max_age_seconds=3600.0,
    )

    acc_v1 = evaluate_result_acceptance(
        result_status="completed",
        physics_domain="multi_step",
        values=values_v1,
        criteria=criteria_v1,
        procedure_verification=True,
        odb_fields=["U", "S", "RF", "RM"],
        evidence_manifest=manifest_v1,
        expected_run_id=run_id_v1,
        base_dir=ga263_dir,
    )

    manifest_results["vectors"]["V1_valid_manifest_qualification"] = {
        "valid": verif_v1.valid,
        "validity": verif_v1.validity,
        "audit_signature_valid": verif_v1.audit_signature_valid,
        "artifacts_checked_count": len(verif_v1.artifact_checks),
        "acceptance_passed": acc_v1.passed,
        "acceptance_status": acc_v1.status,
        "result_validity": acc_v1.result_validity,
        "evidence_gate": acc_v1.gates.get("evidence_sufficiency"),
        "audit_summary": acc_v1.audit_summary,
        "passed": verif_v1.valid and acc_v1.passed and acc_v1.gates.get("evidence_sufficiency") == "PASS",
    }

    # =========================================================================
    # Vector 2: Artifact Tampering Detection (Byte Mutation -> EVIDENCE_TAMPERED)
    # =========================================================================
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for fname in mandatory_fnames:
            shutil.copy2(ga263_dir / fname, tmp_path / fname)

        # Mutate 1 byte in ODB
        odb_file = tmp_path / "GA263_Job.odb"
        orig_bytes = odb_file.read_bytes()
        tampered_bytes = bytearray(orig_bytes)
        tampered_bytes[100] = (tampered_bytes[100] + 1) % 256
        odb_file.write_bytes(tampered_bytes)

        verif_v2 = verify_evidence_integrity(
            manifest_v1,
            base_dir=tmp_path,
            expected_run_id=run_id_v1,
        )

        acc_v2 = evaluate_result_acceptance(
            result_status="completed",
            physics_domain="multi_step",
            values=values_v1,
            criteria=criteria_v1,
            procedure_verification=True,
            odb_fields=["U", "S", "RF", "RM"],
            evidence_manifest=manifest_v1,
            expected_run_id=run_id_v1,
            base_dir=tmp_path,
        )

        manifest_results["vectors"]["V2_artifact_tamper_detection"] = {
            "valid": verif_v2.valid,
            "validity": verif_v2.validity,
            "tampered_artifacts": list(verif_v2.tampered_artifacts),
            "failures": list(verif_v2.failures),
            "acceptance_passed": acc_v2.passed,
            "acceptance_status": acc_v2.status,
            "result_validity": acc_v2.result_validity,
            "evidence_gate": acc_v2.gates.get("evidence_sufficiency"),
            "audit_summary": acc_v2.audit_summary,
            "fail_closed": (
                not verif_v2.valid
                and verif_v2.validity == "TAMPERED"
                and not acc_v2.passed
                and acc_v2.status == "BLOCKED"
                and acc_v2.result_validity == "RESULT_INVALID"
                and acc_v2.gates.get("evidence_sufficiency") == "FAIL"
            ),
        }

    # =========================================================================
    # Vector 3: Missing Critical Artifact (Missing File -> EVIDENCE_INCOMPLETE)
    # =========================================================================
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for fname in mandatory_fnames:
            if fname != "GA263_Job.sta":
                shutil.copy2(ga263_dir / fname, tmp_path / fname)

        verif_v3 = verify_evidence_integrity(
            manifest_v1,
            base_dir=tmp_path,
            expected_run_id=run_id_v1,
        )

        acc_v3 = evaluate_result_acceptance(
            result_status="completed",
            physics_domain="multi_step",
            values=values_v1,
            criteria=criteria_v1,
            procedure_verification=True,
            odb_fields=["U", "S", "RF", "RM"],
            evidence_manifest=manifest_v1,
            expected_run_id=run_id_v1,
            base_dir=tmp_path,
        )

        manifest_results["vectors"]["V3_missing_critical_artifact"] = {
            "valid": verif_v3.valid,
            "validity": verif_v3.validity,
            "missing_artifacts": list(verif_v3.missing_artifacts),
            "failures": list(verif_v3.failures),
            "acceptance_passed": acc_v3.passed,
            "acceptance_status": acc_v3.status,
            "result_validity": acc_v3.result_validity,
            "evidence_gate": acc_v3.gates.get("evidence_sufficiency"),
            "fail_closed": (
                not verif_v3.valid
                and verif_v3.validity == "INCOMPLETE"
                and not acc_v3.passed
                and acc_v3.status == "BLOCKED"
                and acc_v3.result_validity == "RESULT_INVALID"
                and acc_v3.gates.get("evidence_sufficiency") == "FAIL"
            ),
        }

    # =========================================================================
    # Vector 4: Stale Evidence Reuse / Run ID Mismatch (Run Binding)
    # =========================================================================
    mismatched_run_id = "run_20261004_new_active_job_different_id"
    verif_v4 = verify_evidence_integrity(
        manifest_v1,
        base_dir=ga263_dir,
        expected_run_id=mismatched_run_id,
    )

    acc_v4 = evaluate_result_acceptance(
        result_status="completed",
        physics_domain="multi_step",
        values=values_v1,
        criteria=criteria_v1,
        procedure_verification=True,
        odb_fields=["U", "S", "RF", "RM"],
        evidence_manifest=manifest_v1,
        expected_run_id=mismatched_run_id,
        base_dir=ga263_dir,
    )

    manifest_results["vectors"]["V4_run_identity_mismatch"] = {
        "valid": verif_v4.valid,
        "validity": verif_v4.validity,
        "stale": verif_v4.stale,
        "failures": list(verif_v4.failures),
        "acceptance_passed": acc_v4.passed,
        "acceptance_status": acc_v4.status,
        "result_validity": acc_v4.result_validity,
        "evidence_gate": acc_v4.gates.get("evidence_sufficiency"),
        "fail_closed": (
            not verif_v4.valid
            and verif_v4.validity == "STALE"
            and not acc_v4.passed
            and acc_v4.status == "BLOCKED"
            and acc_v4.result_validity == "RESULT_INVALID"
            and acc_v4.gates.get("evidence_sufficiency") == "FAIL"
        ),
    }

    # =========================================================================
    # Vector 5: Stale Evidence / Timestamp Expiry
    # =========================================================================
    old_timestamp = "2020-01-01T00:00:00Z"
    manifest_stale = build_evidence_manifest_v2(
        run_id="run_ancient_stale",
        case_id=case_id_v1,
        artifacts_dir=ga263_dir,
        artifact_filenames=mandatory_fnames,
        created_at=old_timestamp,
    )

    verif_v5 = verify_evidence_integrity(
        manifest_stale,
        base_dir=ga263_dir,
        max_age_seconds=3600.0,  # 1 hour max age, manifest is ~6 years old
    )

    acc_v5 = evaluate_result_acceptance(
        result_status="completed",
        evidence_manifest=manifest_stale,
        base_dir=ga263_dir,
        max_age_seconds=3600.0,
    )

    manifest_results["vectors"]["V5_timestamp_expiry_stale"] = {
        "valid": verif_v5.valid,
        "validity": verif_v5.validity,
        "stale": verif_v5.stale,
        "failures": list(verif_v5.failures),
        "acceptance_passed": acc_v5.passed,
        "acceptance_status": acc_v5.status,
        "result_validity": acc_v5.result_validity,
        "fail_closed": (
            not verif_v5.valid
            and verif_v5.validity == "STALE"
            and not acc_v5.passed
            and acc_v5.status == "BLOCKED"
            and acc_v5.result_validity == "RESULT_INVALID"
        ),
    }

    # =========================================================================
    # Vector 6: Manifest Audit Signature Tampering
    # =========================================================================
    tampered_manifest_dict = manifest_v1.to_dict()
    # Mutate intent without updating cryptographic signature
    tampered_manifest_dict["intent_summary"]["procedure"] = "unauthorized_forged_procedure"

    verif_v6 = verify_evidence_integrity(
        tampered_manifest_dict,
        base_dir=ga263_dir,
        expected_run_id=run_id_v1,
    )

    acc_v6 = evaluate_result_acceptance(
        result_status="completed",
        evidence_manifest=tampered_manifest_dict,
        expected_run_id=run_id_v1,
        base_dir=ga263_dir,
    )

    manifest_results["vectors"]["V6_manifest_signature_tamper"] = {
        "valid": verif_v6.valid,
        "validity": verif_v6.validity,
        "audit_signature_valid": verif_v6.audit_signature_valid,
        "failures": list(verif_v6.failures),
        "acceptance_passed": acc_v6.passed,
        "result_validity": acc_v6.result_validity,
        "fail_closed": (
            not verif_v6.valid
            and verif_v6.validity == "TAMPERED"
            and not acc_v6.passed
            and acc_v6.status == "BLOCKED"
            and acc_v6.result_validity == "RESULT_INVALID"
        ),
    }

    # =========================================================================
    # Vector 7: Engineering Report Synchronization & Anti-Fabrication
    # =========================================================================
    # Report 1: Valid Evidence
    report_valid_data = EngineeringReportData(
        title="Bolt Preload & Torque Engineering Report (Valid)",
        objective="Qualify GA-CL.4 Evidence V2 Provenance",
        acceptance=acc_v1.to_dict(),
        evidence=(manifest_v1.to_dict(),),
    )
    md_valid = render_markdown(report_valid_data)
    has_valid_table = "### Evidence Manifest Summary" in md_valid
    has_artifacts_table = "### Cryptographic Artifact Provenance" in md_valid
    has_verified_audit = "Verified Authentic & Intact" in md_valid
    has_pass_conclusion = "Acceptance criteria passed based on the structured evidence" in md_valid

    # Report 2: Tampered Evidence
    report_tampered_data = EngineeringReportData(
        title="Bolt Preload & Torque Engineering Report (Tampered)",
        objective="Verify Report Rejects Tampered Evidence",
        acceptance=acc_v2.to_dict(),
        evidence=(manifest_v1.to_dict(),),
    )
    md_tampered = render_markdown(report_tampered_data)
    has_tamper_warning = "EVIDENCE TAMPER DETECTED" in md_tampered
    has_rejected_verdict = "REJECTED (RESULT_INVALID)" in md_tampered
    no_false_pass = "Acceptance criteria passed based on the structured evidence" not in md_tampered

    manifest_results["vectors"]["V7_report_synchronization"] = {
        "valid_report_has_manifest_summary": has_valid_table,
        "valid_report_has_artifacts_table": has_artifacts_table,
        "valid_report_has_verified_audit": has_verified_audit,
        "valid_report_passed": has_pass_conclusion,
        "tampered_report_has_tamper_warning": has_tamper_warning,
        "tampered_report_rejected": has_rejected_verdict,
        "tampered_report_no_false_pass": no_false_pass,
        "fail_closed": (
            has_valid_table
            and has_artifacts_table
            and has_verified_audit
            and has_pass_conclusion
            and has_tamper_warning
            and has_rejected_verdict
            and no_false_pass
        ),
    }

    # Evaluate Overall Qualification
    all_pass = all(v.get("passed", v.get("fail_closed", False)) for v in manifest_results["vectors"].values())
    manifest_results["all_vectors_passed"] = all_pass

    # Save official qualification manifest
    manifest_path = ROOT / "machine_validation" / "evidence_v2_manifest.json"
    manifest_path.write_text(json.dumps(manifest_results, indent=2, ensure_ascii=False), encoding="utf-8")

    return manifest_results


if __name__ == "__main__":
    res = run_evidence_v2_qualification()
    print(json.dumps(res, indent=2))
    if not res["all_vectors_passed"]:
        sys.exit(1)
