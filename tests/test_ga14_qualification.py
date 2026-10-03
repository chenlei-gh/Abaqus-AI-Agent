"""Tests for Phase GA-1.4 Real-Machine Mesh Qualification Harness 2.0 (M1 ~ M4).

Validates:
- M1 Plain Block baseline mesh & native post-mesh quality gate evaluation.
- M2 Plate + Hole: GA-1.4 suggested_size (~0.25D) -> Abaqus local seeding -> actual hole element size measurement proving refinement trend (<0.70).
- M3 Plate + Fillet: GA-1.4 suggested_size (~0.5R) -> Abaqus local seeding -> actual fillet span refinement (<0.60).
- M4 Defective Geometry: Non-manifold defect -> GA-1.4 fail-closed BLOCKED -> mesh generation strictly prevented.
- Fail-fast enforcement: Live mode strictly fails when launcher is unavailable or execution fails (zero silent fallback).
- ga14_real_machine_evidence.json manifest structural integrity and qualification criteria.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from tools.ga14_real_machine_qualification import (
    execute_m1_plain_block,
    execute_m2_plate_with_hole,
    execute_m3_plate_with_fillet,
    execute_m4_defective_fail_closed,
    execute_step_hole_qualification,
    execute_step_fillet_qualification,
    run_ga14_qualification_suite,
)

ROOT = Path(__file__).resolve().parent.parent


def test_m1_plain_block_qualification(tmp_path: Path):
    """Verify M1 Plain Block executes baseline mesh, extracts metrics, and passes mesh gate."""
    res = execute_m1_plain_block(tmp_path, offline=True)
    assert res["passed"] is True
    assert res["case_id"] == "M1_PlainBlock"
    assert res["meshability_status"] == "supported"
    assert res["is_meshable"] is True
    assert res["global_seed_applied"] == 5.0
    assert res["mesh_gate_status"] == "PASS"
    assert res["actual_elements"] > 0
    assert res["actual_nodes"] > 0
    assert res["evidence_tier"] == "OFFLINE_EMULATED"
    assert res["native_metrics"]["min_jacobian"] >= 0.5
    assert res["native_metrics"]["max_aspect_ratio"] <= 5.0


def test_m2_plate_hole_local_refinement_qualification(tmp_path: Path):
    """Verify M2 Plate + Hole derives 0.25D seed, meshes, and proves local refinement trend."""
    res = execute_m2_plate_with_hole(tmp_path, offline=True)
    assert res["passed"] is True
    assert res["case_id"] == "M2_PlateHole"
    assert res["hole_diameter"] == 20.0
    assert res["ga14_suggested_size"] == 5.0
    assert res["refinement_verified"] is True
    assert res["measured_refinement_ratio"] < 0.70
    assert res["actual_hole_element_size"] < res["actual_global_element_size"]
    assert res["evidence_tier"] == "OFFLINE_EMULATED"
    assert res["mesh_gate_status"] == "PASS"


def test_m3_plate_fillet_local_refinement_qualification(tmp_path: Path):
    """Verify M3 Plate + Fillet derives 0.5R seed, meshes, and proves fillet refinement."""
    res = execute_m3_plate_with_fillet(tmp_path, offline=True)
    assert res["passed"] is True
    assert res["case_id"] == "M3_PlateFillet"
    assert res["fillet_radius"] == 6.0
    assert res["ga14_suggested_size"] == 3.0
    assert res["refinement_verified"] is True
    assert res["measured_refinement_ratio"] < 0.60
    assert res["actual_fillet_span_size"] < res["actual_far_field_size"]
    assert res["evidence_tier"] == "OFFLINE_EMULATED"
    assert res["mesh_gate_status"] == "PASS"


def test_m4_defective_fail_closed_qualification(tmp_path: Path):
    """Verify M4 non-manifold defect is strictly BLOCKED by GA-1.4 and prevents meshing."""
    res = execute_m4_defective_fail_closed(tmp_path)
    assert res["passed"] is True
    assert res["case_id"] == "M4_DefectiveGeometry"
    assert res["is_meshable"] is False
    assert res["meshability_status"] == "blocked"
    assert res["recommended_strategy"] == "BLOCKED"
    assert res["conversion_blocked_verified"] is True
    assert res["mesh_generation_attempted"] is False
    assert res["safety_guard_enforced"] is True


def test_step_hole_end_to_end_cad_qualification(tmp_path: Path):
    """Verify autonomous STEP file ingestion -> Hole recognition -> Meshability -> Abaqus local refinement."""
    res = execute_step_hole_qualification(tmp_path, offline=True)
    assert res["passed"] is True
    assert res["case_id"] == "STEP_HOLE"
    assert res["cad_source"] == "plate_with_hole.step"
    assert len(res["cad_sha256"]) == 64
    assert res["hole_diameter"] == 20.0
    assert res["ga14_suggested_size"] == 5.0
    assert res["refinement_verified"] is True
    assert res["measured_refinement_ratio"] < 0.70
    assert res["actual_hole_element_size"] < res["actual_global_element_size"]
    assert res["mesh_gate_status"] == "PASS"


def test_step_fillet_end_to_end_cad_qualification(tmp_path: Path):
    """Verify autonomous STEP file ingestion -> Fillet recognition -> Meshability -> Abaqus local refinement."""
    res = execute_step_fillet_qualification(tmp_path, offline=True)
    assert res["passed"] is True
    assert res["case_id"] == "STEP_FILLET"
    assert res["cad_source"] == "stepped_fillet_bar.step"
    assert len(res["cad_sha256"]) == 64
    assert res["fillet_radius"] == 5.0
    assert res["ga14_suggested_size"] == 2.5
    assert res["refinement_verified"] is True
    assert res["measured_refinement_ratio"] < 0.60
    assert res["actual_fillet_span_size"] < res["actual_far_field_size"]
    assert res["mesh_gate_status"] == "PASS"


def test_fail_fast_no_silent_fallback(tmp_path: Path):
    """Verify live mode strictly raises RuntimeError without falling back when launcher is missing."""
    fake_launcher = "nonexistent_abaqus_binary_xyz"
    with pytest.raises(RuntimeError, match="Abaqus launcher not found"):
        execute_m1_plain_block(tmp_path, launcher=fake_launcher, offline=False)

    with pytest.raises(RuntimeError, match="Abaqus launcher not found"):
        execute_m2_plate_with_hole(tmp_path, launcher=fake_launcher, offline=False)


def test_ga14_real_machine_evidence_manifest():
    """Verify audited ga14_real_machine_evidence.json manifest matches strict engineering requirements."""
    manifest_path = ROOT / "machine_validation" / "ga14_real_machine_evidence.json"
    assert manifest_path.is_file(), "GA-1.4 Real-Machine Evidence manifest missing!"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert data["suite_name"] == "Phase GA-1.4 Real-Machine Mesh Qualification Suite"
    assert data["harness_version"] == "2.0_hardened"
    assert data["status"] in ("QUALIFIED", "OFFLINE_VERIFIED")
    assert data["all_passed"] is True
    assert data["benchmarks_total"] == 6
    assert data["benchmarks_passed"] == 6

    # Check limitation disclaimer explicitly recorded
    assert "limitation_disclaimer" in data
    assert "Does NOT claim universal arbitrary CAD qualification" in data["limitation_disclaimer"]

    # Verify M1 ~ M4 + STEP entries
    results = data["results"]
    assert "M1" in results and results["M1"]["passed"] is True
    assert "M2" in results and results["M2"]["passed"] is True
    assert "M3" in results and results["M3"]["passed"] is True
    assert "M4" in results and results["M4"]["passed"] is True
    assert "STEP-HOLE" in results and results["STEP-HOLE"]["passed"] is True
    assert "STEP-FILLET" in results and results["STEP-FILLET"]["passed"] is True

    # Detailed M2 dynamic topological verification in manifest
    assert results["M2"]["refinement_verified"] is True
    assert results["M2"]["measured_refinement_ratio"] < 0.70
    assert results["M2"]["actual_hole_element_size"] < results["M2"]["actual_global_element_size"]
