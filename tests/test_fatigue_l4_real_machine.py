"""Regression verification for authentic Abaqus 2025 Fatigue L4 Golden Suite (GA-F4)."""

import json
from pathlib import Path
import pytest

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "machine_validation" / "fatigue_l4_golden_manifest.json"


@pytest.fixture(scope="module")
def manifest():
    assert MANIFEST_PATH.exists(), f"Fatigue L4 Golden Manifest not found at {MANIFEST_PATH}"
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data


def test_fatigue_l4_manifest_schema_and_overall_status(manifest):
    assert manifest["schema_version"] == "fatigue_l4_golden_v1"
    assert manifest["evidence_tier"] == "REAL_ABAQUS"
    assert manifest["solver_version"] == "Abaqus 2025"
    assert manifest["compiler_chain_verified"] is True
    assert manifest["golden_pass"] is True
    assert manifest["all_negative_probes_fail_closed"] is True
    assert manifest["case_id"] == "MP_Fatigue_L4_Golden"


def test_fatigue_l4_physical_metrics(manifest):
    metrics = manifest["physical_metrics"]
    assert metrics["hotspot_element"] is not None
    assert metrics["peak_mises"] > 150.0  # Significant cyclic bending stress
    assert metrics["max_stress_range"] > 200.0
    assert metrics["fatigue_life"] >= 1.0e5  # Satisfies target life of 100,000 cycles
    assert metrics["cumulative_damage"] <= 0.5  # Well within allowable damage 0.5
    assert set(metrics["available_fields"]).issuperset({"S", "U", "RF"})


def test_fatigue_l4_artifacts_integrity(manifest):
    artifacts = manifest["artifacts"]
    required_exts = (".inp", ".odb", ".sta", ".msg", ".dat", ".log")
    for ext in required_exts:
        matching = [name for name in artifacts if name.endswith(ext)]
        assert len(matching) == 1, f"Missing or duplicate artifact for extension {ext}"
        art_info = artifacts[matching[0]]
        assert art_info["exists"] is True
        assert len(art_info["sha256"]) == 64
        assert art_info["size_bytes"] > 0


def test_fatigue_l4_acceptance_gates(manifest):
    acc = manifest["acceptance"]
    assert acc["passed"] is True
    assert acc["status"] == "PASS"
    assert acc["result_validity"] == "VALID"
    assert "Solver: PASS | ODB: PASS | Required Result: PASS | Engineering Acceptance: PASS" in acc["audit_summary"]

    gates = acc["gates"]
    assert gates["execution"] == "PASS"
    assert gates["odb"] == "PASS"
    assert gates["evidence_sufficiency"] == "PASS"
    assert gates["fatigue"] == "PASS"
    assert gates["required_results"] == "PASS"
    assert gates["criteria"] == "PASS"


def test_fatigue_l4_negative_probes(manifest):
    probes = manifest["negative_probes"]

    # Probe 1: Missing 'S' field output
    p1 = probes["probe_1_missing_required_s"]
    assert p1["fail_closed"] is True
    assert p1["passed"] is False
    assert p1["status"] == "BLOCKED"
    assert p1["result_validity"] == "RESULT_INVALID"
    assert "missing_required_field:S" in p1["failures"]

    # Probe 2: Life/Damage violation
    p2 = probes["probe_2_life_damage_violation"]
    assert p2["fail_closed"] is True
    assert p2["passed"] is False
    assert p2["status"] == "FAIL"
    assert "fatigue_verification_failed" in p2["failures"]

    # Probe 3: Tampered manifest
    p3 = probes["probe_3_tampered_manifest"]
    assert p3["fail_closed"] is True
    assert p3["passed"] is False
    assert p3["status"] == "BLOCKED"
    assert any("evidence_tampered" in f for f in p3["failures"])

    # Probe 4: Missing mandatory fatigue gate
    p4 = probes["probe_4_missing_gate_fatigue"]
    assert p4["fail_closed"] is True
    assert p4["passed"] is False
    assert p4["status"] == "BLOCKED"
    assert "missing_mandatory_gate:fatigue" in p4["failures"]
