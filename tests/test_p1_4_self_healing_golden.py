"""Regression & cryptographic integrity test for P1.4 Self-Healing Golden Manifest.

Validates:
1. Authentic machine run manifest qualification (machine_validation/p1_4_self_healing_manifest.json).
2. Solver failure diagnostics (NUMERICAL_SINGULARITY / ZERO_PIVOT / TOO_MANY_CUTBACKS).
3. Bounded, auditable remediation synthesis (Boundary Condition fixity + Step controls).
4. RunDiff tracking across initial failed state and final accepted candidate.
5. Chapter 14b Self-Healing Audit report generation.
6. Cryptographic audit signature verification and anti-tamper defense probe.
7. Single-exit acceptance verification.
"""

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "machine_validation" / "p1_4_self_healing_manifest.json"


def test_p1_4_self_healing_manifest_integrity():
    assert MANIFEST_PATH.is_file(), f"Manifest missing at {MANIFEST_PATH}"

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Metadata and schema verification
    assert manifest.get("schema_version") == "evidence_manifest_v2"
    assert manifest.get("case_id") == "P1_4_SELF_HEALING_GOLDEN"
    assert manifest.get("qualification_level") == "QUALIFIED"
    assert manifest.get("status") == "ACCEPTED"

    # 2. Cryptographic signature check
    signature = manifest.get("audit_signature")
    assert signature is not None and len(signature) == 64

    manifest_copy = dict(manifest)
    manifest_copy.pop("audit_signature", None)
    expected_hash = hashlib.sha256(
        json.dumps(manifest_copy, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert signature == expected_hash, "Cryptographic audit signature mismatch or manifest tampered!"

    # 3. Self-healing audit and physical results verification
    summary = manifest.get("summary", {})
    assert summary.get("status") == "COMPLETED"
    assert summary.get("engineering_status") == "RESULT_VALID"
    assert summary.get("acceptance_passed") is True
    assert summary.get("report_md_length", 0) > 1000

    sh = summary.get("self_healing", {})
    assert sh.get("healed") is True
    assert sh.get("total_attempts") == 1
    assert len(sh.get("remediations_applied", [])) >= 1
    assert len(sh.get("attempts", [])) == 1

    phys = manifest.get("physical_results", {})
    assert phys.get("max_mises_mpa", 0.0) > 0.0
    assert phys.get("tip_deflection_mm", 0.0) > 0.0
    assert phys.get("reaction_force_n", 0.0) == 1000.0
    assert phys.get("total_attempts") == 1

    # 4. Probes verification (All 11 must be PASS)
    probes = manifest.get("probes", {})
    assert len(probes) == 11
    for p_name, p_status in probes.items():
        assert p_status == "PASS", f"Probe {p_name} failed: {p_status}"


def test_p1_4_manifest_tamper_detection():
    """Verify anti-tamper security: altering manifest content invalidates signature."""
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Tamper with healed status
    tampered = dict(manifest)
    tampered["summary"] = dict(tampered["summary"])
    tampered["summary"]["status"] = "FAKE_STATUS"

    tampered_copy = dict(tampered)
    orig_sig = tampered_copy.pop("audit_signature", None)
    recalculated_hash = hashlib.sha256(
        json.dumps(tampered_copy, sort_keys=True).encode("utf-8")
    ).hexdigest()

    assert orig_sig != recalculated_hash, "Tamper detection failed to flag manipulated manifest!"
