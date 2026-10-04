import hashlib
import json
import os
import pytest
from types import SimpleNamespace

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.evidence import build_evidence_manifest_v2
from abaqus_ai_agent.contracts.fatigue import FatigueResult, IntentFatigueSpec
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
from abaqus_ai_agent.contracts.results import get_physics_result_profile
from abaqus_ai_agent.fatigue import run_fatigue_postprocess
from abaqus_ai_agent.planning.compiler import (
    IntentBoundarySpec,
    IntentGeometrySpec,
    IntentLoadSpec,
    IntentMeshSpec,
    IntentStepSpec,
    compile_intent_to_actions,
)


class MockValue:
    def __init__(self, elementLabel, mises, data, integrationPoint=1, maxPrincipal=None, tresca=None):
        self.elementLabel = elementLabel
        self.mises = mises
        self.data = data
        self.integrationPoint = integrationPoint
        self.maxPrincipal = maxPrincipal
        self.tresca = tresca
        self.instance = SimpleNamespace(name="PART-1-1")


class MockFrame:
    def __init__(self, frameValue, s_field=None):
        self.frameValue = frameValue
        self.fieldOutputs = {"S": s_field} if s_field else {}


class MockField:
    def __init__(self, values):
        self.values = values


class MockStep:
    def __init__(self, frames):
        self.frames = frames


class MockOdb:
    def __init__(self, steps):
        self.steps = steps


def _create_cyclic_mock_odb():
    """Create a 10-frame cyclic stress history: 0 -> 250 -> 0 -> -250 -> 0 -> 250 -> 0 -> -250 -> 0 -> 100 MPa."""
    stress_seq = [
        (0.0, 0.0, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        (0.1, 150.0, [150.0, 50.0, 20.0, 0.0, 0.0, 0.0]),
        (0.2, 250.0, [250.0, 80.0, 30.0, 0.0, 0.0, 0.0]),
        (0.3, 100.0, [100.0, 30.0, 10.0, 0.0, 0.0, 0.0]),
        (0.4, 0.0, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        (0.5, 250.0, [-250.0, -80.0, -30.0, 0.0, 0.0, 0.0]),
        (0.6, 100.0, [-100.0, -30.0, -10.0, 0.0, 0.0, 0.0]),
        (0.7, 0.0, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        (0.8, 250.0, [250.0, 80.0, 30.0, 0.0, 0.0, 0.0]),
        (0.9, 0.0, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    ]
    frames = []
    for t, vm, data in stress_seq:
        val = MockValue(elementLabel=101, mises=vm, data=data, integrationPoint=1)
        # Add background element with lower stress to test hotspot detection
        val_bg = MockValue(elementLabel=102, mises=10.0, data=[10.0, 0.0, 0.0, 0.0, 0.0, 0.0], integrationPoint=1)
        field = MockField(values=[val_bg, val])
        frames.append(MockFrame(frameValue=t, s_field=field))
    return MockOdb(steps={"Step-Cyclic": MockStep(frames=frames)})


def _create_mock_artifacts(tmp_path, run_id="run_fatigue_01"):
    files = []
    for role in ("inp", "odb", "msg", "dat", "sta", "log"):
        fname = f"fatigue_job.{role}"
        fpath = tmp_path / fname
        fpath.write_text(f"mock content for {role} under {run_id}", encoding="utf-8")
        files.append(fname)
    return files


def test_fatigue_l4_full_agent_chain_golden(tmp_path):
    """GA-F4.5: Full Agent-chain qualification test for Fatigue L4.

    Validates:
    EngineeringIntent (IntentFatigueSpec)
    -> compile_intent_to_actions (verifies field output 'S' injection)
    -> ODB stress history extraction & hotspot detection
    -> Deterministic rainflow + Palmgren-Miner damage
    -> EvidenceManifestV2 creation & integrity check
    -> evaluate_result_acceptance (Gate 8 PASS + ODB fields PASS + Metrics PASS)
    -> Canonical ACCEPTED status
    """
    sn_curve = (
        (100.0, 1.0e7),
        (250.0, 1.0e6),
        (500.0, 1.0e4),
    )
    fatigue_spec = IntentFatigueSpec(
        target_cycles=1.0e5,
        allowable_damage=0.5,
        material_curve=sn_curve,
        ultimate_strength=800.0,
        mean_stress_correction="GOODMAN",
        measure="signed_mises",
    )

    # 1. EngineeringIntent Declaration
    intent = EngineeringIntent(
        id="intent_fatigue_bracket_01",
        kind="structural_fatigue",
        description="Bracket high-cycle fatigue life verification under cyclic loading",
        analysis_type="cyclic_fatigue",
        material={"name": "Steel_Fatigue", "elastic": {"youngs_modulus": 210000.0, "poissons_ratio": 0.3}},
        fatigue=fatigue_spec,
    )
    assert intent.fatigue is not None
    assert intent.fatigue.target_cycles == 1.0e5

    # 2. Autonomous Intent Compilation
    mat_def = MaterialDefinition(
        name="Steel_Fatigue",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
    )
    plan = compile_intent_to_actions(
        model_name="Model-Fatigue",
        part_name="Part-Bracket",
        job_name="Job-Fatigue",
        geometry=IntentGeometrySpec(shape="plate", length=120.0, width=40.0, thickness=5.0),
        material=mat_def,
        step=IntentStepSpec(name="Step-Cyclic", step_type="STATIC", time_period=1.0),
        bcs=[IntentBoundarySpec(name="FixedRoot", bc_type="ENCASTRE", region="Root")],
        loads=[IntentLoadSpec(name="CyclicTraction", load_type="PRESSURE", region="Tip", magnitude=50.0)],
        mesh=IntentMeshSpec(global_size=5.0),
        fatigue=intent.fatigue,
    )

    # Verify that the compiler injected 'S' into fieldOutputRequests
    assert "fieldOutputRequests" in plan.cae_script
    assert "'S'" in plan.cae_script
    assert plan.intent_summary["fatigue"] is not None
    assert plan.intent_summary["fatigue"]["target_cycles"] == 1.0e5

    # 3. Mock Solved ODB with Cyclic Stress Response
    mock_odb = _create_cyclic_mock_odb()

    # 4. Postprocess Bridge
    out_json = str(tmp_path / "fatigue_eval.json")
    fatigue_res, metrics = run_fatigue_postprocess(mock_odb, intent.fatigue, output_json_path=out_json)

    assert fatigue_res.passed is True
    assert fatigue_res.status == "pass"
    assert fatigue_res.damage is not None and fatigue_res.damage < 0.5
    assert fatigue_res.life_cycles is not None and fatigue_res.life_cycles >= 1.0e5
    assert metrics["hotspot_element"] == 101

    # 5. Evidence V2 Manifest Building
    run_id = "run_fatigue_l4_golden_01"
    files = _create_mock_artifacts(tmp_path, run_id=run_id)
    manifest = build_evidence_manifest_v2(
        run_id=run_id,
        case_id="MP-Fatigue-01",
        artifacts_dir=tmp_path,
        artifact_filenames=files,
        intent_summary=plan.intent_summary,
        required_results={"fields": ["S"], "metrics": ["fatigue_life", "damage"]},
        verification={"status": "pass", "metrics": metrics},
        acceptance={"passed": True},
    )

    criteria = [
        {"name": "min_life_gate", "value_key": "fatigue_life", "operator": ">=", "limit": 1.0e5},
        {"name": "max_damage_gate", "value_key": "damage", "operator": "<=", "limit": 0.5},
    ]

    # 6. Result Acceptance Evaluation
    profile = get_physics_result_profile("fatigue")
    acceptance = evaluate_result_acceptance(
        result_status="completed",
        values=metrics,
        criteria=criteria,
        fatigue=fatigue_res,
        odb_status="VALID",
        odb_fields=["S"],
        required_fields=profile.required_fields,
        physics_domain="fatigue",
        required_gates=profile.required_gates,
        required_metrics=profile.required_metrics,
        evidence_manifest=manifest.to_dict(),
        expected_run_id=run_id,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert acceptance.passed is True
    assert acceptance.status == "PASS"
    assert acceptance.gates["execution"] == "PASS"
    assert acceptance.gates["odb"] == "PASS"
    assert acceptance.gates["fatigue"] == "PASS"
    assert acceptance.gates["criteria"] == "PASS"
    assert acceptance.gates["evidence_sufficiency"] == "PASS"


def test_fatigue_l4_negative_probe_missing_required_s_field(tmp_path):
    """Negative Probe 1: ODB exists and solver completed, but missing mandatory field 'S' -> RESULT_INVALID."""
    run_id = "run_fatigue_neg_missing_s"
    files = _create_mock_artifacts(tmp_path, run_id=run_id)
    manifest = build_evidence_manifest_v2(
        run_id=run_id,
        case_id="MP-Fatigue-Neg-01",
        artifacts_dir=tmp_path,
        artifact_filenames=files,
    )

    fatigue_res = FatigueResult(status="pass", life_cycles=2.0e6, damage=0.01)
    acceptance = evaluate_result_acceptance(
        result_status="completed",
        values={"fatigue_life": 2.0e6, "damage": 0.01},
        criteria=[{"name": "min_life_gate", "value_key": "fatigue_life", "operator": ">=", "limit": 1.0e5}],
        fatigue=fatigue_res,
        odb_status="VALID",
        odb_fields=["U", "RF"],  # Missing 'S'
        required_fields=["S"],
        physics_domain="fatigue",
        required_gates=["execution", "odb", "fatigue", "criteria"],
        required_metrics=["fatigue_life", "damage"],
        evidence_manifest=manifest.to_dict(),
        expected_run_id=run_id,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert acceptance.passed is False
    assert acceptance.gates["required_results"] == "BLOCKED"
    assert "missing_required_field:S" in acceptance.failures
    assert acceptance.result_validity == "RESULT_INVALID"


def test_fatigue_l4_negative_probe_missing_mandatory_fatigue_gate(tmp_path):
    """Negative Probe 2: Fatigue gate is mandatory for domain 'fatigue', but fatigue result is omitted -> BLOCKED."""
    run_id = "run_fatigue_neg_missing_gate"
    files = _create_mock_artifacts(tmp_path, run_id=run_id)
    manifest = build_evidence_manifest_v2(
        run_id=run_id,
        case_id="MP-Fatigue-Neg-02",
        artifacts_dir=tmp_path,
        artifact_filenames=files,
    )

    acceptance = evaluate_result_acceptance(
        result_status="completed",
        values={"fatigue_life": 2.0e6, "damage": 0.01},
        criteria=[{"name": "min_life_gate", "value_key": "fatigue_life", "operator": ">=", "limit": 1.0e5}],
        fatigue=None,  # Omitted fatigue result
        odb_status="VALID",
        odb_fields=["S"],
        required_fields=["S"],
        physics_domain="fatigue",
        required_gates=["execution", "odb", "fatigue", "criteria"],
        required_metrics=["fatigue_life", "damage"],
        evidence_manifest=manifest.to_dict(),
        expected_run_id=run_id,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert acceptance.passed is False
    assert acceptance.gates["fatigue"] == "BLOCKED"
    assert "missing_mandatory_gate:fatigue" in acceptance.failures
    assert "missing_mandatory_gate:fatigue" in acceptance.blocked


def test_fatigue_l4_negative_probe_damage_exceeded_or_life_short(tmp_path):
    """Negative Probe 3: Severe cyclic stress exceeds damage limit / life threshold -> FAIL."""
    run_id = "run_fatigue_neg_damage_fail"
    files = _create_mock_artifacts(tmp_path, run_id=run_id)
    manifest = build_evidence_manifest_v2(
        run_id=run_id,
        case_id="MP-Fatigue-Neg-03",
        artifacts_dir=tmp_path,
        artifact_filenames=files,
    )

    mock_odb = _create_cyclic_mock_odb()
    strict_spec = IntentFatigueSpec(
        target_cycles=1.0e12,  # Unattainably high target
        allowable_damage=1.0e-8,  # Extremely strict damage threshold
        material_curve=((100.0, 1.0e6), (250.0, 1.0e4)),
    )
    fatigue_res, metrics = run_fatigue_postprocess(mock_odb, strict_spec)

    assert fatigue_res.passed is False
    assert fatigue_res.status == "fail"

    acceptance = evaluate_result_acceptance(
        result_status="completed",
        values=metrics,
        criteria=[{"name": "strict_life_gate", "value_key": "fatigue_life", "operator": ">=", "limit": 1.0e12}],
        fatigue=fatigue_res,
        odb_status="VALID",
        odb_fields=["S"],
        required_fields=["S"],
        physics_domain="fatigue",
        required_gates=["execution", "odb", "fatigue", "criteria"],
        required_metrics=["fatigue_life", "damage"],
        evidence_manifest=manifest.to_dict(),
        expected_run_id=run_id,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert acceptance.passed is False
    assert acceptance.gates["fatigue"] == "FAIL"
    assert "fatigue_verification_failed" in acceptance.failures


def test_fatigue_l4_negative_probe_tampered_evidence(tmp_path):
    """Negative Probe 4: EvidenceManifest artifact tampered -> EVIDENCE_TAMPERED -> BLOCKED."""
    run_id = "run_fatigue_neg_tamper"
    files = _create_mock_artifacts(tmp_path, run_id=run_id)
    manifest = build_evidence_manifest_v2(
        run_id=run_id,
        case_id="MP-Fatigue-Neg-04",
        artifacts_dir=tmp_path,
        artifact_filenames=files,
    )

    # Tamper with the ODB file after manifest generation
    odb_path = tmp_path / "fatigue_job.odb"
    odb_path.write_text("tampered malicious content", encoding="utf-8")

    fatigue_res = FatigueResult(status="pass", life_cycles=2.0e6, damage=0.01)
    acceptance = evaluate_result_acceptance(
        result_status="completed",
        values={"fatigue_life": 2.0e6, "damage": 0.01},
        criteria=[{"name": "min_life_gate", "value_key": "fatigue_life", "operator": ">=", "limit": 1.0e5}],
        fatigue=fatigue_res,
        odb_status="VALID",
        odb_fields=["S"],
        required_fields=["S"],
        physics_domain="fatigue",
        required_gates=["execution", "odb", "fatigue", "criteria"],
        required_metrics=["fatigue_life", "damage"],
        evidence_manifest=manifest.to_dict(),
        expected_run_id=run_id,
        base_dir=str(tmp_path),
        require_evidence=True,
    )

    assert acceptance.passed is False
    assert acceptance.gates["evidence_sufficiency"] == "FAIL"
    assert any("hash_mismatch" in f for f in acceptance.failures)


def test_analysis_runner_fatigue_auto_bridge(tmp_path):
    """Verify AnalysisRunner automatically invokes fatigue postprocessing when intent has fatigue."""
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner, AnalysisRunState

    class MockFatigueExecutor:
        def __init__(self, mock_odb):
            self.mock_odb = mock_odb

        def snapshot(self):
            return None

        def execute(self, code, timeout=120):
            if "status" in code and "mdb.jobs" in code:
                return "COMPLETED"
            return {"status": "COMPLETED"}

        def inspect_odb(self, path):
            return self.mock_odb

    sn_curve = (
        (100.0, 1.0e7),
        (250.0, 1.0e6),
    )
    fatigue_spec = IntentFatigueSpec(
        target_cycles=1.0e5,
        allowable_damage=0.5,
        material_curve=sn_curve,
        ultimate_strength=800.0,
        mean_stress_correction="GOODMAN",
        measure="signed_mises",
    )
    intent = EngineeringIntent(
        id="intent_runner_fatigue",
        kind="structural_fatigue",
        description="Auto fatigue verification",
        analysis_type="cyclic_fatigue",
        fatigue=fatigue_spec,
    )

    mock_odb = _create_cyclic_mock_odb()
    executor = MockFatigueExecutor(mock_odb)
    runner = AnalysisRunner(executor)

    # Create dummy artifacts so evidence manifest v2 builds cleanly
    for ext in ("inp", "odb", "sta", "msg", "dat", "log"):
        (tmp_path / f"Job-AutoFatigue.{ext}").write_text(f"dummy content for {ext}", encoding="utf-8")

    run = runner.run(
        model_name="Model-1",
        job_name="Job-AutoFatigue",
        odb_path=str(tmp_path / "Job-AutoFatigue.odb"),
        engineering_intent=intent,
        workdir=str(tmp_path),
    )

    assert run.state == AnalysisRunState.ACCEPTED
    assert run.acceptance_passed is True
    assert run.get_metric("fatigue_life") is not None
    assert run.get_metric("damage") is not None
    assert run.acceptance.gates["fatigue"] == "PASS"
    assert run.acceptance.gates["execution"] == "PASS"
    assert run.acceptance.gates["odb"] == "PASS"
