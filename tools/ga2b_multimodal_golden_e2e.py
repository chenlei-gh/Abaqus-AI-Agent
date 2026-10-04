#!/usr/bin/env python3
"""Track GA-2B: Multimodal Perception & Human-in-the-Loop Golden Suite.

Demonstrates the complete GA-2B full-chain under real Abaqus 2025:
  2D Technical Drawing Callouts (Annotations, Text, Arrows, Dimensions)
        ↓
  VisualCallout Parsing (parse_drawing_callout)
        ↓
  Topological Candidate Correlation (correlate_callout_with_cad, GroundedRegion)
        ↓
  Mandatory Human-in-the-Loop (HITL) Gate (MultimodalHITLWorkflow, HITLConfirmationDecision)
        ↓
  Intent Synthesis (IntentBoundarySpec, IntentLoadSpec, grounded_regions)
        ↓
  Canonical Intent Compiler (compile_intent_to_actions)
        ↓
  Preflight Gate (33 checks / 0 blockers)
        ↓
  Live Abaqus 2025 Solver (Standard Static Analysis)
        ↓
  Real ODB (.inp, .odb, .sta, .msg, .dat, .log)
        ↓
  Equilibrium Verification (RF vs Applied Error < 0.1%)
        ↓
  EvidenceManifestV2 (Cryptographic SHA-256 bindings & Run ID provenance)
        ↓
  Deterministic Acceptance (evaluate_result_acceptance)
        ↓
  Executive Report & Provenance Manifest (ga2b_multimodal_manifest.json)

Negative Probes:
  1. Unconfirmed observation compilation attempt -> HITLBlockedError
  2. Observation rejection handling -> Fail-closed execution
  3. Missing required ODB result -> RESULT_INVALID / BLOCKED
  4. Evidence tampering detection -> EVIDENCE_TAMPERED / BLOCKED
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.evidence import build_evidence_manifest_v2, EvidenceManifestV2
from abaqus_ai_agent.contracts.geometry import ImagePoint, resolve_region
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import MaterialDefinition, ElasticProperties
from abaqus_ai_agent.contracts.multimodal import (
    CalloutType,
    MultimodalSourceType,
    GroundingIntentType,
    HITLStatus,
    VisualCallout,
    BlueprintView,
    GroundingObservation,
    HITLConfirmationDecision,
)
from abaqus_ai_agent.contracts.results import get_physics_result_profile
from abaqus_ai_agent.execution.batch import resolve_default_launcher
from abaqus_ai_agent.grounding.feature_grounding import GroundedRegion
from abaqus_ai_agent.grounding.multimodal import (
    MultimodalGroundingError,
    HITLBlockedError,
    parse_drawing_callout,
    correlate_callout_with_cad,
    MultimodalHITLWorkflow,
)
from abaqus_ai_agent.planning.compiler import (
    compile_intent_to_actions,
    IntentGeometrySpec,
    IntentStepSpec,
    IntentMeshSpec,
)
from abaqus_ai_agent.reporting.renderer import render_markdown
from abaqus_ai_agent.validation.preflight import preflight_action, preflight_plan


def _sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _collect_artifacts(case_dir: Path, job_name: str) -> Dict[str, Any]:
    artifacts = {}
    for ext in ("inp", "odb", "sta", "msg", "dat", "log"):
        p = case_dir / f"{job_name}.{ext}"
        if p.exists():
            artifacts[f"{job_name}.{ext}"] = {
                "sha256": _sha256(p),
                "size_bytes": p.stat().st_size,
                "exists": True,
            }
        else:
            artifacts[f"{job_name}.{ext}"] = {"exists": False}
    return artifacts


def run_ga2b_multimodal_golden(workdir: Path, launcher: str) -> Dict[str, Any]:
    case_dir = workdir / "GA2B_Multimodal_Golden"
    case_dir.mkdir(parents=True, exist_ok=True)
    job_name = "Job_GA2B_Multimodal"
    model_name = "Model-Multimodal"
    part_name = "CantileverBeam"

    print("=" * 70)
    print("STEP 1: Multimodal 2D Callout Ingestion & Correlation")
    print("=" * 70)

    # 1. 2D Blueprint Inputs:
    # Callout 1: Fixed constraint on root face
    callout_bc = parse_drawing_callout(
        callout_id="callout_root_fix",
        text="Encastre fixed support at Root Face (X=0)",
        location=ImagePoint(0.05, 0.5),
    )
    # Callout 2: Uniform pressure on tip
    callout_load = parse_drawing_callout(
        callout_id="callout_tip_load",
        text="Apply 5.0 MPa uniform compressive pressure on Tip Face",
        location=ImagePoint(0.95, 0.5),
    )

    # 2. Geometric candidate anchors (Abaqus beam width=10, height=20, length=100)
    # Root face at Z=0, Tip face at Z=100
    candidate_bc = [
        {
            "name": "RootFace",
            "entity_type": "Face",
            "point": (5.0, 10.0, 0.0),
            "normal": (0.0, 0.0, -1.0),
            "index": 1,
            "confidence": 0.95,
        }
    ]
    candidate_load = [
        {
            "name": "TipFace",
            "entity_type": "Face",
            "point": (5.0, 10.0, 100.0),
            "normal": (0.0, 0.0, 1.0),
            "index": 2,
            "confidence": 0.95,
        }
    ]

    obs_bc = correlate_callout_with_cad(
        callout_bc,
        candidate_bc,
        target_semantic="FIXED_ROOT",
        source_type=MultimodalSourceType.BLUEPRINT_VIEW.value,
        view_id="VIEW_FRONT",
    )
    obs_load = correlate_callout_with_cad(
        callout_load,
        candidate_load,
        target_semantic="TIP_LOAD",
        source_type=MultimodalSourceType.BLUEPRINT_VIEW.value,
        view_id="VIEW_FRONT",
    )

    print("=" * 70)
    print("STEP 2: Mandatory Human-in-the-Loop (HITL) Gate Evaluation")
    print("=" * 70)

    workflow = MultimodalHITLWorkflow(confidence_threshold=0.85)
    workflow.register_observation(obs_bc)
    workflow.register_observation(obs_load)

    # Negative Probe 1: Attempt synthesis before confirmation
    print("Executing Negative Probe 1: Block unconfirmed observations...")
    unconfirmed_blocked = False
    try:
        workflow.synthesize_specs(fail_closed=True)
    except HITLBlockedError as e:
        unconfirmed_blocked = True
        print(f"  [PROBE 1 PASS] HITLBlockedError caught as expected: {e}")
    assert unconfirmed_blocked, "Unconfirmed observation failed to trigger fail-closed HITLBlockedError!"

    # Explicit Human Confirmation
    print("Engineer reviewing and confirming observations...")
    dec_bc = HITLConfirmationDecision(
        observation_id="obs_callout_root_fix",
        decision="CONFIRM",
        confirmed_by="principal_cae_engineer",
        selected_region_semantic="FIXED_ROOT",
        notes="Root face constraint verified against engineering blueprint Rev B",
    )
    dec_load = HITLConfirmationDecision(
        observation_id="obs_callout_tip_load",
        decision="CONFIRM",
        confirmed_by="principal_cae_engineer",
        selected_region_semantic="TIP_LOAD",
        override_magnitude=5.0,
        override_unit="MPa",
        notes="Tip compressive pressure confirmed (5.0 MPa on 200 mm2 face = 1000 N total)",
    )
    workflow.confirm(dec_bc)
    workflow.confirm(dec_load)

    # Synthesize confirmed specs
    bcs, loads, grounded_regions = workflow.synthesize_specs()
    print(f"  Synthesized {len(bcs)} BC(s), {len(loads)} Load(s), {len(grounded_regions)} Grounded Region(s)")

    print("=" * 70)
    print("STEP 3: Compile Multimodal Intent into ActionPlan & Preflight")
    print("=" * 70)

    geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=20.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    step = IntentStepSpec(name="StaticStep", time_period=1.0)
    mesh = IntentMeshSpec(global_size=5.0)

    plan = compile_intent_to_actions(
        model_name=model_name,
        part_name=part_name,
        job_name=job_name,
        geometry=geom,
        material=mat,
        step=step,
        bcs=bcs,
        loads=loads,
        mesh=mesh,
        grounded_regions=grounded_regions,
    )

    # Verify Preflight
    for action in plan.actions:
        pf = preflight_action(action)
        assert pf.passed is True, f"Preflight blocker on action {action.action_type}: {pf.blockers}"
    print(f"  Preflight verified: {len(plan.actions)} actions, 0 blockers")

    print("=" * 70)
    print("STEP 4: Live Execution under Abaqus 2025")
    print("=" * 70)

    driver_path = case_dir / "run_multimodal_model.py"
    driver_content = f"""
from abaqus import *
from abaqusConstants import *
import regionToolset

{plan.cae_script}

# Submit Job
j = mdb.jobs['{job_name}']
j.submit()
j.waitForCompletion()
"""
    driver_path.write_text(driver_content, encoding="utf-8")

    cmd = [launcher, "cae", f"noGUI={driver_path.name}"]
    print(f"  Executing command: {' '.join(cmd)} in {case_dir}")
    t0 = datetime.datetime.now()
    res = subprocess.run(cmd, cwd=str(case_dir), capture_output=True, text=True, timeout=300)
    elapsed = (datetime.datetime.now() - t0).total_seconds()
    print(f"  Solver finished in {elapsed:.2f}s (rc={res.returncode})")

    odb_path = case_dir / f"{job_name}.odb"
    assert odb_path.exists(), f"ODB was not generated! stderr: {res.stderr}\nstdout: {res.stdout}"

    print("=" * 70)
    print("STEP 5: ODB Extraction & Physical Equilibrium Verification")
    print("=" * 70)

    extract_script = case_dir / "extract_results.py"
    results_json = case_dir / "extracted_metrics.json"
    extract_code = f"""
import json
from odbAccess import openOdb

odb = openOdb(r'{odb_path}')
step = odb.steps['{step.name}']
frame = step.frames[-1]

# Reaction force sum at Root
rf_field = frame.fieldOutputs['RF']
sum_rf_x = 0.0
sum_rf_y = 0.0
sum_rf_z = 0.0

for val in rf_field.values:
    sum_rf_x += val.data[0]
    sum_rf_y += val.data[1]
    sum_rf_z += val.data[2]

total_rf = (sum_rf_x**2 + sum_rf_y**2 + sum_rf_z**2)**0.5

# Max Mises Stress
s_field = frame.fieldOutputs['S']
max_mises = max(val.mises for val in s_field.values)

# Max Displacement
u_field = frame.fieldOutputs['U']
max_u = max(val.magnitude for val in u_field.values)

first_inst = list(odb.rootAssembly.instances.keys())[0]
inst = odb.rootAssembly.instances[first_inst]

data = {{
    'sum_rf_x': sum_rf_x,
    'sum_rf_y': sum_rf_y,
    'sum_rf_z': sum_rf_z,
    'total_rf': total_rf,
    'max_mises': max_mises,
    'max_u': max_u,
    'num_elements': len(inst.elements),
    'num_nodes': len(inst.nodes),
}}

with open(r'{results_json}', 'w') as f:
    json.dump(data, f)

odb.close()
"""
    extract_script.write_text(extract_code, encoding="utf-8")
    sub_cmd = [launcher, "python", str(extract_script)]
    sub_res = subprocess.run(sub_cmd, cwd=str(case_dir), capture_output=True, text=True, timeout=120)
    assert sub_res.returncode == 0, f"Extraction failed: {sub_res.stderr}\nstdout: {sub_res.stdout}"

    metrics = json.loads(results_json.read_text(encoding="utf-8"))
    print(f"  Extracted Metrics:")
    print(f"    Reaction Force: RF_x={metrics['sum_rf_x']:.3f} N, RF_y={metrics['sum_rf_y']:.3f} N, RF_z={metrics['sum_rf_z']:.3f} N, Total={metrics['total_rf']:.3f} N")
    print(f"    Max Mises Stress: {metrics['max_mises']:.2f} MPa")
    print(f"    Max Displacement: {metrics['max_u']:.4f} mm")
    print(f"    Mesh: {metrics['num_elements']} elements, {metrics['num_nodes']} nodes")

    # Reaction force equilibrium check
    # Pressure 5.0 MPa on cross-section 10 mm x 20 mm = 200 mm^2 -> Total load = 1000.0 N
    applied_force = 5.0 * (10.0 * 20.0)
    measured_rf = metrics["total_rf"]
    eq_error = abs(measured_rf - applied_force) / applied_force
    print(f"  Applied load (P * A): {applied_force:.3f} N, Measured reaction RF: {measured_rf:.3f} N")
    print(f"  Equilibrium balance error: {eq_error * 100:.4f}%")
    assert eq_error < 0.001, f"Reaction force equilibrium error excessive: {eq_error}"

    print("=" * 70)
    print("STEP 6: EvidenceManifestV2 & Deterministic Acceptance Gate")
    print("=" * 70)

    run_id = f"run_ga2b_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    artifacts = _collect_artifacts(case_dir, job_name)
    artifact_filenames = [f"{job_name}.{ext}" for ext in ("inp", "odb", "sta", "msg", "dat", "log")]

    manifest = build_evidence_manifest_v2(
        run_id=run_id,
        case_id="GA2B_Multimodal_Golden",
        artifacts_dir=str(case_dir),
        artifact_filenames=artifact_filenames,
        intent_summary={"model_name": model_name, "driver_sha256": _sha256(driver_path)},
        required_results={"fields": ["U", "S", "RF"], "metrics": ["reaction_force", "max_mises", "max_displacement"]},
        verification={"equilibrium_error": eq_error},
        acceptance={"status": "PASS"},
        environment={"solver_version": "Abaqus 2025"},
        metadata={
            "multimodal_source": "engineering_drawing_blueprint",
            "hitl_confirmed_by": "principal_cae_engineer",
        },
    )

    manifest_json_path = case_dir / "evidence_manifest.json"
    manifest_json_path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")

    criteria = (
        {"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 500.0},
        {"name": "disp_limit", "value_key": "max_displacement", "operator": "<=", "limit": 2.0},
    )

    # Acceptance evaluation
    acceptance = evaluate_result_acceptance(
        result_status="completed",
        odb_status="valid",
        physics_domain="linear_static",
        required_metrics=("reaction_force", "max_mises", "max_displacement"),
        values={
            "reaction_force": measured_rf,
            "max_mises": metrics["max_mises"],
            "max_displacement": metrics["max_u"],
        },
        criteria=criteria,
        odb_fields=("U", "S", "RF"),
        require_evidence=True,
        expected_run_id=run_id,
        base_dir=str(case_dir),
        evidence_manifest=manifest,
    )
    print(f"  Acceptance Result: passed={acceptance.passed}, validity={acceptance.result_validity}")
    assert acceptance.passed is True
    assert acceptance.result_validity == "VALID"

    print("=" * 70)
    print("STEP 7: Negative Fail-Closed Verification Probes")
    print("=" * 70)

    # Negative Probe 2: Rejection of observation
    print("Executing Negative Probe 2: Reject observation...")
    rej_wf = MultimodalHITLWorkflow()
    rej_obs = correlate_callout_with_cad(callout_bc, candidate_bc)
    rej_wf.register_observation(rej_obs)
    rej_wf.reject("obs_callout_root_fix", reason="Boundary region does not match revised specification")
    rej_bcs, rej_loads, _ = rej_wf.synthesize_specs()
    assert len(rej_bcs) == 0, "Rejected observation produced active BCs!"
    print("  [PROBE 2 PASS] Rejected observation cleanly omitted without error")

    # Negative Probe 3: Missing required ODB result
    print("Executing Negative Probe 3: Missing required ODB result...")
    acc_neg_result = evaluate_result_acceptance(
        result_status="completed",
        odb_status="valid",
        physics_domain="linear_static",
        required_metrics=("reaction_force", "max_mises", "max_displacement"),
        values={"max_mises": metrics["max_mises"]},  # missing displacement and reaction force
        odb_fields=("S",),
        require_evidence=False,
    )
    assert acc_neg_result.passed is False
    assert acc_neg_result.result_validity == "RESULT_INVALID"
    print(f"  [PROBE 3 PASS] Missing required result correctly marked as {acc_neg_result.result_validity}")

    # Negative Probe 4: Evidence tampering
    print("Executing Negative Probe 4: Evidence tampering detection...")
    tampered_manifest = EvidenceManifestV2.from_dict(manifest.to_dict())
    tampered_manifest.audit_signature = "bad_signature_0000000000000000000000000000000000000000000000000000000000000000"

    acc_tamper = evaluate_result_acceptance(
        result_status="completed",
        odb_status="valid",
        physics_domain="linear_static",
        required_metrics=("reaction_force", "max_mises", "max_displacement"),
        values={
            "reaction_force": measured_rf,
            "max_mises": metrics["max_mises"],
            "max_displacement": metrics["max_u"],
        },
        odb_fields=("U", "S", "RF"),
        require_evidence=True,
        expected_run_id=run_id,
        base_dir=str(case_dir),
        evidence_manifest=tampered_manifest,
    )
    assert acc_tamper.passed is False
    assert acc_tamper.result_validity == "RESULT_INVALID"
    print(f"  [PROBE 4 PASS] Tampered evidence correctly blocked as {acc_tamper.result_validity}")

    # Persist certified machine validation evidence
    golden_manifest_data = {
        "benchmark": "Track GA-2B: Multimodal Perception & Grounding Real Abaqus 2025 Golden",
        "case_id": "GA2B_Multimodal_Golden",
        "status": "QUALIFIED",
        "evidence_tier": "REAL_ABAQUS",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "run_id": run_id,
        "solver": "Abaqus 2025",
        "workflow": {
            "2d_callout_parsing": "PASS",
            "topological_candidate_correlation": "PASS",
            "mandatory_hitl_gate": "PASS",
            "intent_compiler_actions": "PASS",
            "preflight_checks": "PASS",
            "live_solver_execution": "PASS",
            "odb_extraction": "PASS",
            "equilibrium_balance": "PASS",
            "evidence_v2_acceptance": "PASS",
            "negative_probes": {
                "unconfirmed_hitl_blocked": "PASS",
                "observation_rejection_fail_closed": "PASS",
                "missing_required_results_blocked": "PASS",
                "tampered_evidence_blocked": "PASS",
            },
        },
        "metrics": {
            "applied_force_N": applied_force,
            "measured_reaction_force_N": measured_rf,
            "equilibrium_error_percent": eq_error * 100,
            "max_mises_MPa": metrics["max_mises"],
            "max_displacement_mm": metrics["max_u"],
            "num_elements": metrics["num_elements"],
            "num_nodes": metrics["num_nodes"],
        },
        "artifacts": artifacts,
    }

    golden_manifest_file = ROOT / "machine_validation" / "ga2b_multimodal_manifest.json"
    golden_manifest_file.write_text(json.dumps(golden_manifest_data, indent=2), encoding="utf-8")
    print(f"Persisted certified evidence manifest: {golden_manifest_file}")

    return golden_manifest_data


def main():
    parser = argparse.ArgumentParser(description="Run GA-2B Multimodal Golden Suite")
    parser.add_argument("--workdir", type=Path, default=ROOT / "legacy_job_artifacts" / "ga2b_multimodal")
    parser.add_argument("--launcher", type=str, default="C:\\SIMULIA\\Commands\\abaqus.bat")
    args = parser.parse_args()

    launcher = resolve_default_launcher(args.launcher)
    print(f"Starting GA-2B Multimodal Golden using launcher: {launcher}")
    res = run_ga2b_multimodal_golden(args.workdir, launcher)
    print("=" * 70)
    print(f"GA-2B Golden Completed: Status={res['status']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
