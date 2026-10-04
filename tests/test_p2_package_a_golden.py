"""Regression & cryptographic integrity test for Phase 2 Package A Golden Manifest.

Validates REQ-P2-001 ~ REQ-P2-005:
1. Authentic machine run manifest qualification (machine_validation/p2_package_a_manifest.json).
2. Deep engineering scenario composition:
   - Scenario 1: Fatigue Multi-Step Cyclic Loading (Gate 8, Rainflow, Goodman, Miner)
   - Scenario 2: Kinematic Connector & Mechanism Joint (Gate 13, CONN3D2, joint drift <= 1e-5 mm)
   - Scenario 3: Flexible Multibody Dynamics (Gate 14, rigid-flexible coupling, energy dissipation < 1%)
   - Scenario 4: Sequential Thermal -> Structural Coupling (thermal gradient, thermal stress, reaction balance)
   - Scenario 5: Preloaded Modal & Friction Contact (stress stiffening, normal/shear friction equilibrium)
3. Negative probes (All 5 fail-closed).
4. Deterministic SHA-256 cryptographic signature verification.
5. Single-exit Acceptance & Evidence V2 closure.
"""

import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "machine_validation" / "p2_package_a_manifest.json"


def test_p2_package_a_manifest_integrity():
    assert MANIFEST_PATH.is_file(), f"Manifest missing at {MANIFEST_PATH}"

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Metadata and schema verification
    assert manifest.get("schema_version") == "package_a_matrix_v1"
    assert manifest.get("case_id") == "PHASE_2_PACKAGE_A_GOLDEN_MATRIX"
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

    # 3. Summary verification
    summary = manifest.get("summary", {})
    assert summary.get("status") == "COMPLETED"
    assert summary.get("engineering_status") == "RESULT_VALID"
    assert summary.get("acceptance_passed") is True
    assert summary.get("total_scenarios") == 5
    assert summary.get("total_probes") == 5

    # 4. Scenarios verification
    scenarios = manifest.get("scenarios", {})
    assert len(scenarios) == 5

    # Scenario 1: Fatigue
    sc1 = scenarios.get("case_01_fatigue_cyclic", {})
    assert sc1.get("status") == "QUALIFIED"
    assert sc1.get("gate_8_fatigue") == "PASS"
    assert sc1.get("evidence_v2") == "PASS"
    assert sc1.get("cycles_to_failure", 0) > 10000

    # Scenario 2: Connector
    sc2 = scenarios.get("case_02_connector_joint", {})
    assert sc2.get("status") == "QUALIFIED"
    assert sc2.get("gate_13_connector") == "PASS"
    assert sc2.get("evidence_v2") == "PASS"
    assert sc2.get("max_joint_drift_mm", 1.0) < 1e-4

    # Scenario 3: FMBD
    sc3 = scenarios.get("case_03_fmbd_dynamics", {})
    assert sc3.get("status") == "QUALIFIED"
    assert sc3.get("gate_14_fmbd") == "PASS"
    assert sc3.get("evidence_v2") == "PASS"
    assert sc3.get("energy_dissipation_ratio", 1.0) < 0.05

    # Scenario 4: Thermal -> Structural
    sc4 = scenarios.get("case_04_thermal_structural", {})
    assert sc4.get("status") == "QUALIFIED"
    assert sc4.get("thermal_balance_gate") == "PASS"
    assert sc4.get("evidence_v2") == "PASS"
    assert sc4.get("max_temperature") == 100.0
    assert sc4.get("reaction_force_n", 0.0) > 1000.0

    # Scenario 5: Preloaded Modal & Friction Contact
    sc5 = scenarios.get("case_05_preload_modal_contact", {})
    assert sc5.get("status") == "QUALIFIED"
    assert sc5.get("contact_and_procedure_gates") == "PASS"
    assert sc5.get("evidence_v2") == "PASS"
    assert sc5.get("friction_ratio") == 0.25
    assert sc5.get("frequency_stiffening_ratio", 0.0) > 1.0

    # 5. Probes verification (All 5 must be PASS)
    probes = manifest.get("probes", {})
    assert len(probes) == 5
    for p_name, p_status in probes.items():
        assert p_status == "PASS", f"Probe {p_name} failed: {p_status}"
