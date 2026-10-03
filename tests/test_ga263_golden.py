"""Tests for Phase GA-2.6.3 End-to-End Golden Case (Bolt Pretension -> FIX_LENGTH -> Moment -> Acceptance).

Validates the complete 5-layer engineering verification chain:
1. Procedure: Initial -> Step-Preload -> Step-Service DAG dependency & state inheritance.
2. Bolt: Preload step APPLY_FORCE (5000 N) -> Service step FIX_LENGTH state persistence.
3. External Load: Service step external tension (2000 N) + RP-coupling torque (100000 N*mm).
4. Physical Acceptance: Deterministic acceptance against RF balance, RM balance, and non-zero fields.
5. Evidence: Cryptographic SHA-256 provenance of .inp, .odb, logs, and acceptance JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from tools.ga263_e2e_golden_case import check_launcher, execute_ga263_golden_case
from abaqus_ai_agent.contracts.procedure import (
    BoltPretensionLifecycleSpec,
    MultiStepProcedureSpec,
    StepDependency,
)
from abaqus_ai_agent.planning.compiler import (
    IntentBoundarySpec,
    IntentGeometrySpec,
    IntentMeshSpec,
    compile_intent_to_actions,
)
from abaqus_ai_agent.contracts.material import MaterialDefinition, ElasticProperties
from abaqus_ai_agent.validation.preflight import preflight_plan

ROOT = Path(__file__).resolve().parent.parent


def test_ga263_golden_case_offline(tmp_path: Path):
    """Verify GA-2.6.3 Golden Case 5-layer pipeline under deterministic offline mode."""
    res = execute_ga263_golden_case(tmp_path, offline=True)
    assert res["status"] == "QUALIFIED"
    assert res["evidence_tier"] == "OFFLINE_EMULATED"
    assert res["case_id"] == "GA263_BOLT_PRETENSION_MOMENT_ACCEPTANCE"

    five = res["five_layers_verification"]

    # Layer 1: Procedure
    assert five["layer_1_procedure"]["verified"] is True
    assert five["layer_1_procedure"]["steps_present"] == ["Step-Preload", "Step-Service"]

    # Layer 2: Bolt Pretension
    assert five["layer_2_bolt_pretension"]["verified"] is True
    assert five["layer_2_bolt_pretension"]["preload_method"] == "APPLY_FORCE"
    assert five["layer_2_bolt_pretension"]["service_method"] == "FIX_LENGTH"
    assert five["layer_2_bolt_pretension"]["target_preload_n"] == 5000.0
    assert five["layer_2_bolt_pretension"]["preload_relative_error"] < 0.005

    # Layer 3: External Load
    assert five["layer_3_external_load"]["verified"] is True
    assert five["layer_3_external_load"]["applied_tension_n"] == 2000.0
    assert five["layer_3_external_load"]["applied_torque_nmm"] == 100000.0
    assert five["layer_3_external_load"]["moment_strategy"] == "RP_COUPLING"

    # Layer 4: Physical Acceptance
    assert five["layer_4_physical_acceptance"]["verified"] is True
    assert five["layer_4_physical_acceptance"]["axial_equilibrium_error"] < 0.005
    assert five["layer_4_physical_acceptance"]["torque_equilibrium_error"] < 0.005
    assert five["layer_4_physical_acceptance"]["max_mises_stress_mpa"] > 0.0
    assert five["layer_4_physical_acceptance"]["max_displacement_mm"] > 0.0
    assert five["layer_4_physical_acceptance"]["mesh_element_count"] > 0

    # Layer 5: Evidence & Traceability
    assert len(five["layer_5_evidence_traceability"]["script_sha256"]) == 64
    assert res["acceptance"]["status"] in ("PASS", "WARNING")
    assert res["acceptance"]["passed"] is True


def test_ga263_preflight_blocks_invalid_bolt_lifecycle():
    """Verify preflight gate fails closed when bolt lifecycle order is violated."""
    from abaqus_ai_agent.actions import builders
    # Orphaned bolt_load_set_values without prior APPLY_FORCE definition
    proc_action = builders.static_step(model="M", name="Step-2", previous="Initial")
    orphan_action = builders.bolt_load_set_values(
        model="M",
        name="OrphanBolt",
        step="Step-2",
        bolt_method="FIX_LENGTH",
    )
    pf = preflight_plan([proc_action, orphan_action])
    assert pf.passed is False
    assert any("bolt_pretension_lifecycle_valid" in b["name"] for b in pf.blockers)


def test_ga263_golden_evidence_manifest_structure():
    """Verify ga263_golden_evidence.json matches required 5-layer qualification schema."""
    manifest_path = ROOT / "machine_validation" / "ga263_golden_evidence.json"
    if not manifest_path.is_file():
        pytest.skip("Manifest ga263_golden_evidence.json has not been generated yet.")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["phase"] == "GA-2.6.3"
    assert data["status"] in ("QUALIFIED", "FAILED")
    assert "five_layers_verification" in data
    five = data["five_layers_verification"]
    assert "layer_1_procedure" in five
    assert "layer_2_bolt_pretension" in five
    assert "layer_3_external_load" in five
    assert "layer_4_physical_acceptance" in five
    assert "layer_5_evidence_traceability" in five
    assert len(five["layer_5_evidence_traceability"]["script_sha256"]) == 64


def test_ga263_golden_case_live_abaqus_real_machine(tmp_path: Path):
    """Verify GA-2.6.3 Golden Case executes on real live Abaqus 2025 and extracts physical evidence."""
    launcher, is_live = check_launcher("abaqus")
    if not is_live:
        pytest.skip(f"Live Abaqus launcher not available at '{launcher}' on this host.")

    res = execute_ga263_golden_case(tmp_path, launcher=launcher, offline=False)
    assert res["status"] == "QUALIFIED"
    assert res["evidence_tier"] == "REAL_ABAQUS"

    five = res["five_layers_verification"]
    assert five["layer_1_procedure"]["verified"] is True
    assert five["layer_2_bolt_pretension"]["verified"] is True
    assert five["layer_3_external_load"]["verified"] is True
    assert five["layer_4_physical_acceptance"]["verified"] is True

    # Check physical values in live solver results
    assert abs(five["layer_2_bolt_pretension"]["preload_relative_error"]) < 0.005
    assert abs(five["layer_4_physical_acceptance"]["axial_equilibrium_error"]) < 0.005
    assert abs(five["layer_4_physical_acceptance"]["torque_equilibrium_error"]) < 0.005
    assert five["layer_4_physical_acceptance"]["max_mises_stress_mpa"] > 10.0
    assert five["layer_4_physical_acceptance"]["max_displacement_mm"] > 0.001
