"""Regression verification for authentic Abaqus 2025 Multi-Physics Golden Suite (GA-CL.1)."""

import json
from pathlib import Path
import pytest

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "machine_validation" / "multi_physics_golden_manifest.json"


@pytest.fixture(scope="module")
def manifest():
    assert MANIFEST_PATH.exists(), f"Multi-Physics Golden Manifest not found at {MANIFEST_PATH}"
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data


def test_multi_physics_manifest_schema_and_overall_status(manifest):
    assert manifest["schema_version"] == "multi_physics_golden_v1"
    assert manifest["evidence_tier"] == "REAL_ABAQUS"
    assert manifest["solver_version"] == "Abaqus 2025"
    assert manifest["total_cases"] == 4
    assert manifest["all_golden_pass"] is True
    assert manifest["all_negative_probes_fail_closed"] is True

    required_cases = {
        "MP1_ThermalStructural",
        "MP2_FrictionContact",
        "MP3_PreloadedModal",
        "MP4_ExplicitDynamic",
    }
    assert set(manifest["cases"].keys()) == required_cases


@pytest.mark.parametrize("case_key", [
    "MP1_ThermalStructural",
    "MP2_FrictionContact",
    "MP3_PreloadedModal",
    "MP4_ExplicitDynamic",
])
def test_each_case_golden_pass_and_fail_closed(manifest, case_key):
    case = manifest["cases"][case_key]
    assert case["solver_completed"] is True
    assert case["golden_pass"] is True
    assert case["report_unforgeable"] is True

    acc = case["acceptance"]
    assert acc["passed"] is True
    assert acc["status"] == "PASS"
    assert acc["result_validity"] == "VALID"
    assert "Solver: PASS | ODB: PASS | Required Result: PASS | Engineering Acceptance: PASS" in acc["audit_summary"]

    neg = case["negative_probe"]
    assert neg["fail_closed"] is True
    assert neg["passed"] is False
    assert neg["status"] == "BLOCKED"
    assert neg["result_validity"] == "RESULT_INVALID"
    assert "Engineering Acceptance: FAIL" in neg["audit_summary"]

    # Check cryptographic artifacts provenance
    artifacts = case["artifacts"]
    for ext in (".inp", ".odb", ".sta", ".msg", ".dat", ".log"):
        matching = [name for name in artifacts if name.endswith(ext)]
        assert len(matching) == 1, f"Missing artifact with extension {ext} for {case_key}"
        art_info = artifacts[matching[0]]
        assert art_info["exists"] is True
        assert len(art_info["sha256"]) == 64
        assert art_info["size_bytes"] > 0


def test_mp1_thermal_structural_physics(manifest):
    mp1 = manifest["cases"]["MP1_ThermalStructural"]
    metrics = mp1["physical_metrics"]

    assert metrics["max_temperature"] == pytest.approx(100.0, rel=1e-3)
    assert metrics["min_temperature"] == pytest.approx(20.0, rel=1e-3)
    assert metrics["max_mises"] > 50.0  # Thermal expansion constraint generates significant stress
    assert metrics["reaction_force"] > 5000.0
    assert abs(metrics["reaction_equilibrium_sum"]) < 1e-3  # Global equilibrium: sum(RF) == 0


def test_mp2_frictional_contact_physics(manifest):
    mp2 = manifest["cases"]["MP2_FrictionContact"]
    metrics = mp2["physical_metrics"]

    assert metrics["contact_pressure"] > 1.0  # Active normal contact
    assert metrics["reaction_force"] == pytest.approx(1000.0, rel=1e-2)  # Applied normal load balance
    # Coulomb friction law: tau = mu * p (mu = 0.25)
    coulomb_ratio = metrics["frictional_shear"] / metrics["contact_pressure"]
    assert coulomb_ratio == pytest.approx(0.25, rel=1e-2)
    assert mp2["coulomb_error"] < 0.01


def test_mp3_preloaded_modal_physics(manifest):
    mp3 = manifest["cases"]["MP3_PreloadedModal"]
    metrics = mp3["physical_metrics"]

    # Target axial tension is 10000 N, reaction equilibrium check
    assert metrics["preload_reaction"] == pytest.approx(10000.0, rel=1e-3)
    assert metrics["frequency"] > 300.0  # Fundamental mode frequency in Hz
    assert len(metrics["mode_frequencies"]) >= 3


def test_mp4_explicit_dynamic_physics(manifest):
    mp4 = manifest["cases"]["MP4_ExplicitDynamic"]
    metrics = mp4["physical_metrics"]

    assert metrics["kinetic_energy"] > 0.0
    assert metrics["internal_energy"] > 0.0
    assert metrics["work_input"] > 0.0
    # Energy conservation balance: |ALLKE + ALLIE - ALLWK| / max(ALLKE + ALLIE) < 5%
    assert metrics["energy_balance_error"] < 0.05
    energy_sum = metrics["kinetic_energy"] + metrics["internal_energy"]
    assert energy_sum == pytest.approx(metrics["work_input"], rel=0.05)
