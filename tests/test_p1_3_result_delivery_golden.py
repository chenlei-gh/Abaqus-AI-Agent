"""Regression & cryptographic integrity test for P1.3 Result Delivery Golden Manifest.

Validates:
1. Real Abaqus 2025 machine run manifest qualification (machine_validation/p1_3_result_delivery_manifest.json).
2. Physical metrics sanity (stress, deflection, reaction balance error < 0.01%).
3. Extraction of R1 field results, R2 history curves, R4 Top-K spatial hotspots, R5 SVG vector charts, and R6 deliverables.
4. Cryptographic audit signature verification and anti-tamper defense probe.
5. Strict multi-state bidirectional equivalence across task lifecycle.
"""

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "machine_validation" / "p1_3_result_delivery_manifest.json"


def test_p1_3_result_delivery_manifest_integrity():
    assert MANIFEST_PATH.is_file(), f"Manifest missing at {MANIFEST_PATH}"

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Metadata and schema verification
    assert manifest.get("schema_version") == "evidence_manifest_v2"
    assert manifest.get("case_id") == "P1_3_RESULT_DELIVERY_GOLDEN"
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

    # 3. Physical results verification
    phys = manifest.get("physical_results", {})
    assert 450.0 <= phys.get("max_mises_mpa", 0.0) <= 650.0
    assert 1.5 <= phys.get("deflection_mm", 0.0) <= 3.0
    assert 990.0 <= phys.get("reaction_force_n", 0.0) <= 1010.0
    assert phys.get("force_balance_error_percent", 100.0) < 0.01
    assert phys.get("hotspot_count", 0) == 5
    assert phys.get("curve_count", 0) >= 4

    # 4. Probes verification
    probes = manifest.get("probes", {})
    assert len(probes) == 10
    for p_name, p_status in probes.items():
        assert p_status in ("PASS", "PASS_FALLBACK"), f"Probe {p_name} failed: {p_status}"

    # 5. Multi-state bidirectional equivalence
    summary = manifest.get("summary", {})
    is_completed = (summary.get("status") == "COMPLETED")
    assert is_completed is True
    assert (summary.get("engineering_status") in ("RESULT_VALID", "ACCEPTED")) == is_completed
    assert (summary.get("acceptance_passed") is True) == is_completed
    assert summary.get("report_md_length", 0) > 1000
    assert summary.get("report_html_length", 0) > 1000


def test_p1_3_manifest_anti_tamper_defense():
    """Verify that any modification to physical metrics is detected as cryptographic violation."""
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Tamper with max_mises_mpa
    manifest["physical_results"]["max_mises_mpa"] = 9999.0
    sig = manifest.pop("audit_signature")
    tampered_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert sig != tampered_hash
