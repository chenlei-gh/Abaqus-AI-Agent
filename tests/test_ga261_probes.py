"""Tests for GA-2.6.1 Abaqus 2025 Physical API Probes & Solver Calibration Harness.

Validates:
- Probe 0 (P0): Multi-step DAG, state inheritance and load propagation.
- Probe 1 (P1): Bolt pretension two-stage lifecycle (APPLY_FORCE -> FIX_LENGTH).
- Probe 2 (P2): Analytical spatial load field (ExpressionField + FIELD distribution integration).
- Probe 3 (P3): Moment / torque transfer strategy (RP + Coupling on solid continuum).
- Fail-fast enforcement: strict refusal of silent fallback.
- Certified machine evidence manifest integrity in machine_validation/ga261_probe_evidence.json.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from tools.ga261_physical_api_probes import (
    execute_all_probes,
    run_probe_0,
    run_probe_1,
    run_probe_2,
    run_probe_3,
    check_launcher,
)

ROOT = Path(__file__).resolve().parent.parent


def test_ga261_probes_offline_execution(tmp_path: Path):
    """Verify all 4 physical probes pass contract validation in offline mode."""
    manifest = execute_all_probes(tmp_path, offline=True)
    assert manifest["phase"] == "GA-2.6.1"
    assert manifest["all_probes_passed"] is True
    assert manifest["probe_count"] == 4
    assert manifest["evidence_tier"] == "OFFLINE_EMULATED"

    probes = {p["probe"]: p for p in manifest["probes"]}
    assert "P0_MULTI_STEP_INHERITANCE" in probes
    assert "P1_BOLT_PRETENSION_LIFECYCLE" in probes
    assert "P2_SPATIAL_LOAD_FIELD" in probes
    assert "P3_MOMENT_COUPLING_STRATEGY" in probes

    # P0 verification
    p0 = probes["P0_MULTI_STEP_INHERITANCE"]
    assert p0["passed"] is True
    assert p0["steps_verified"] == ["Step-1", "Step-2"]
    assert p0["step1_error"] < 0.005
    assert p0["step2_error"] < 0.005

    # P1 verification
    p1 = probes["P1_BOLT_PRETENSION_LIFECYCLE"]
    assert p1["passed"] is True
    assert p1["preload_error"] < 0.001
    assert p1["service_error"] < 0.001

    # P2 verification
    p2 = probes["P2_SPATIAL_LOAD_FIELD"]
    assert p2["passed"] is True
    assert p2["integral_relative_error"] < 0.001

    # P3 verification
    p3 = probes["P3_MOMENT_COUPLING_STRATEGY"]
    assert p3["passed"] is True
    assert p3["torque_equilibrium_error"] < 0.001
    assert p3["net_shear_force"] < 1e-5


def test_ga261_fail_fast_on_missing_launcher(tmp_path: Path):
    """Verify live execution strictly fails fast when launcher does not exist."""
    fake_launcher = "non_existent_abaqus_launcher_9999"
    with pytest.raises(RuntimeError) as exc_info:
        run_probe_0(tmp_path, launcher=fake_launcher, offline=False)
    assert "FAIL-FAST" in str(exc_info.value) or "not found" in str(exc_info.value)


def test_ga261_probe_evidence_manifest_integrity():
    """Verify the persisted real-machine evidence file exists and passes strict criteria."""
    evidence_file = ROOT / "machine_validation" / "ga261_probe_evidence.json"
    assert evidence_file.is_file(), f"Evidence file missing at {evidence_file}"

    data = json.loads(evidence_file.read_text(encoding="utf-8"))
    assert data["phase"] == "GA-2.6.1"
    assert data["solver_version"] == "Abaqus 2025"
    assert data["evidence_tier"] == "REAL_ABAQUS"
    assert data["all_probes_passed"] is True
    assert data["probe_count"] == 4

    probes = {p["probe"]: p for p in data["probes"]}

    # P0 checks
    p0 = probes["P0_MULTI_STEP_INHERITANCE"]
    assert p0["evidence_tier"] == "REAL_ABAQUS"
    assert p0["passed"] is True
    assert p0["steps_verified"] == ["Step-1", "Step-2"]
    assert abs(p0["step1_rf_y"] - 1000.0) < 0.01
    assert abs(p0["step2_rf_y"] - 1500.0) < 0.01

    # P1 checks
    p1 = probes["P1_BOLT_PRETENSION_LIFECYCLE"]
    assert p1["evidence_tier"] == "REAL_ABAQUS"
    assert p1["passed"] is True
    assert abs(p1["rf_bottom_preload"] - (-5000.0)) < 0.01
    assert abs(p1["rf_top_preload"] - 5000.0) < 0.01
    assert abs(p1["rf_bottom_service"] - (-2000.0)) < 0.01
    assert abs(p1["rf_top_service"]) < 0.01

    # P2 checks
    p2 = probes["P2_SPATIAL_LOAD_FIELD"]
    assert p2["evidence_tier"] == "REAL_ABAQUS"
    assert p2["passed"] is True
    assert p2["analytical_reference"] == 15000.0
    assert abs(p2["actual_total_rf3"] - 15000.0) < 0.1
    assert p2["integral_relative_error"] < 1e-4

    # P3 checks
    p3 = probes["P3_MOMENT_COUPLING_STRATEGY"]
    assert p3["evidence_tier"] == "REAL_ABAQUS"
    assert p3["passed"] is True
    assert p3["applied_torque"] == 100000.0
    assert abs(abs(p3["reaction_torque"]) - 100000.0) < 1.0
    assert p3["torque_equilibrium_error"] < 1e-4
    assert p3["net_shear_force"] < 1e-6


def test_ga261_live_abaqus_real_machine(tmp_path: Path):
    """Live solver probe execution test on host machine when Abaqus 2025 is available."""
    launcher, is_live = check_launcher("abaqus")
    if not is_live:
        pytest.skip("Live Abaqus launcher not available on this machine.")

    # Run P2 (fastest analytical integration probe) on real machine to verify live test pass
    res = run_probe_2(tmp_path, launcher=launcher, offline=False)
    assert res["passed"] is True
    assert res["evidence_tier"] == "REAL_ABAQUS"
    assert abs(res["actual_total_rf3"] - 15000.0) < 0.1
