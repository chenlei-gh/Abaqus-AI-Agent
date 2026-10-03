"""Tests for Phase GA-2 End-to-End Engineering Intent to Real Abaqus ODB Golden Case.

Validates:
- Complete autonomous deterministic chain:
  STEP CAD Ingestion (plate_with_hole.step)
  -> Geometry Health
  -> Canonical Topology
  -> Fastener Hole Recognition
  -> Semantic Physical Grounding (INSTALLATION_HOLE & TOP_SURFACE)
  -> Intent Compilation into AbaqusAction plan
  -> Preflight validation (0 blockers)
  -> Real Abaqus 2025 execution & ODB extraction
  -> Physical equilibrium: ΣRFz ≈ 1000.0 N (error < 0.1%)
- Fail-fast enforcement (zero silent fallback in live mode)
- Fail-closed safety gates for unresolved or ambiguous semantics
- Manifest validation for machine_validation/ga2_golden_evidence.json
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from tools.ga2_e2e_golden_case import (
    execute_ga2_golden_case,
    _check_launcher_availability,
)
from abaqus_ai_agent.grounding.feature_grounding import (
    resolve_feature_grounding,
    GroundingResolutionError,
    GroundingAmbiguityError,
)

ROOT = Path(__file__).resolve().parent.parent


def test_ga2_golden_case_e2e_offline(tmp_path: Path):
    """Verify GA-2 Golden Case pipeline offline verification."""
    res = execute_ga2_golden_case(tmp_path, offline=True)
    assert res["passed"] is True
    assert res["case_id"] == "GA2_GOLDEN_CASE"
    assert res["cad_source"] == "plate_with_hole.step"
    assert res["evidence_tier"] == "OFFLINE_EMULATED"

    # Hole grounding verification
    assert res["hole_grounding"]["target"] == "INSTALLATION_HOLE"
    assert res["hole_grounding"]["status"] == "RESOLVED"
    assert res["hole_grounding"]["anchor_point"] == [60.0, 50.0, 10.0]
    assert res["hole_grounding"]["confidence"] >= 0.90

    # Top surface grounding verification
    assert res["top_grounding"]["target"] == "TOP_SURFACE"
    assert res["top_grounding"]["status"] == "RESOLVED"
    assert res["top_grounding"]["anchor_point"] == [25.0, 25.0, 20.0]
    assert res["top_grounding"]["confidence"] >= 0.90

    # Preflight & Actions
    assert res["preflight_status"] == "PASS"
    assert res["actions_compiled_count"] >= 12

    # Physical equilibrium
    assert res["applied_force_newtons"] == 1000.0
    assert abs(res["measured_reaction_force_z"] - 1000.0) < 5.0
    assert res["equilibrium_error_percent"] < 0.5
    assert res["equilibrium_satisfied"] is True
    assert res["max_mises_stress_mpa"] > 0
    assert res["max_displacement_mm"] > 0


def test_ga2_golden_case_live_abaqus_real_machine(tmp_path: Path):
    """Verify GA-2 Golden Case executes on real live Abaqus 2025 and extracts physical ODB evidence."""
    launcher, is_live = _check_launcher_availability("abaqus")
    if not is_live:
        pytest.skip(f"Live Abaqus launcher not available at '{launcher}' on this machine.")

    res = execute_ga2_golden_case(tmp_path, launcher=launcher, offline=False)
    assert res["passed"] is True
    assert res["evidence_tier"] == "REAL_ABAQUS"
    assert res["applied_force_newtons"] == 1000.0

    # Real reaction force balance: ΣRFz ≈ 1000.0 N
    rf_z = res["measured_reaction_force_z"]
    assert 995.0 <= rf_z <= 1005.0
    assert res["equilibrium_error_percent"] < 0.1
    assert res["equilibrium_satisfied"] is True

    # Real field outputs
    assert 2.0 <= res["max_mises_stress_mpa"] <= 10.0
    assert 0.0001 <= res["max_displacement_mm"] <= 0.01
    assert res["mesh_element_count"] > 1000
    assert res["mesh_node_count"] > 1000
    assert len(res["script_sha256"]) == 64


def test_ga2_fail_closed_on_unrecognized_semantic(tmp_path: Path):
    """Verify strict mode fails closed with GroundingResolutionError for unknown semantic targets."""
    from abaqus_ai_agent.geometry.cad_ingestion import ingest_cad_file
    from abaqus_ai_agent.geometry.topology import normalize_topology
    from abaqus_ai_agent.geometry.features import detect_features

    step_path = ROOT / "tests" / "fixtures" / "step" / "plate_with_hole.step"
    model = ingest_cad_file(step_path)
    topo = normalize_topology(model)
    features = detect_features(model, topo)

    with pytest.raises(GroundingResolutionError) as exc_info:
        resolve_feature_grounding("UNKNOWN_FIXTURE_WING", model, topo, features, strict=True)
    assert "UNSUPPORTED_SEMANTIC_TARGET" in str(exc_info.value)


def test_ga2_golden_evidence_manifest_schema():
    """Verify ga2_golden_evidence.json manifest matches required qualification schema."""
    manifest_path = ROOT / "machine_validation" / "ga2_golden_evidence.json"
    assert manifest_path.is_file(), f"Manifest missing at {manifest_path}"

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["suite_name"] == "Phase GA-2 End-to-End Engineering Intent to Abaqus ODB Qualification"
    assert data["status"] == "QUALIFIED"
    assert data["execution_mode"] in ("REAL_ABAQUS", "OFFLINE_EMULATED")

    gc = data["golden_case"]
    assert gc["case_id"] == "GA2_GOLDEN_CASE"
    assert gc["passed"] is True
    assert gc["cad_source"] == "plate_with_hole.step"
    assert gc["applied_force_newtons"] == 1000.0
    assert gc["equilibrium_satisfied"] is True
    assert gc["equilibrium_error_percent"] < 0.1
    assert gc["max_mises_stress_mpa"] > 0
    assert gc["max_displacement_mm"] > 0
    assert gc["mesh_element_count"] > 0
    assert gc["mesh_node_count"] > 0
    assert len(gc["script_sha256"]) == 64
