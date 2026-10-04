"""Regression tests for RC Evidence Freeze & Bypass Closure (P0/P1 Integrity Remediations).

Verifies the 8 mandatory fail-closed and bypass-prevention scenarios:
1. No EvidenceManifest + values all correct -> BLOCKED, RESULT_INVALID.
2. EvidenceManifest missing an artifact on disk -> BLOCKED, RESULT_INVALID.
3. EvidenceManifest hash mismatch -> BLOCKED, RESULT_INVALID.
4. external_input with all values correct -> cannot transition to ACCEPTED.
5. Preflight blocking failure -> Abaqus job is never created or submitted.
6. MP Golden without evidence binding -> BLOCKED.
7. Legacy V1 manifest (golden_matrix_manifest.json) -> rejected as RC evidence.
8. Normal REAL_ABAQUS + V2 -> ACCEPTED, PASS.
"""

from __future__ import annotations

import json
from pathlib import Path

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.evidence import (
    EvidenceManifestV2,
    build_evidence_manifest_v2,
    verify_evidence_integrity,
)
from abaqus_ai_agent.engineering_status import EngineeringStatus
from abaqus_ai_agent.execution.analysis_run import AnalysisRunState, AnalysisRunner


def test_scenario_1_no_evidence_manifest_with_valid_numbers_is_blocked():
    """Scenario 1: No EvidenceManifest + numerical values all correct -> BLOCKED."""
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_displacement": 0.05, "max_mises": 50.0, "reaction_force": 1000.0},
        criteria=[
            {"name": "disp", "value_key": "max_displacement", "operator": "<=", "limit": 0.1},
            {"name": "stress", "value_key": "max_mises", "operator": "<=", "limit": 100.0},
        ],
        require_evidence=True,
        evidence_manifest=None,
        evidence=None,
    )
    assert res.passed is False
    assert res.status == "BLOCKED"
    assert res.result_validity == "RESULT_INVALID"
    assert "missing_required_evidence" in res.blocked
    assert res.gates["evidence_sufficiency"] == "BLOCKED"
    assert res.audit_summary == "Solver: PASS | ODB: PASS | Required Result: FAIL | Engineering Acceptance: FAIL"


def test_scenario_2_evidence_manifest_missing_artifact_is_blocked(tmp_path: Path):
    """Scenario 2: EvidenceManifest missing artifact on disk -> BLOCKED."""
    for ext in ("inp", "odb", "sta", "dat", "log"):
        (tmp_path / f"job.{ext}").write_bytes(b"mock content")
    fnames = [f"job.{ext}" for ext in ("inp", "odb", "sta", "dat", "log")]

    manifest = build_evidence_manifest_v2(
        run_id="run_missing_artifact",
        case_id="case_missing_artifact",
        artifacts_dir=tmp_path,
        artifact_filenames=fnames,
    )

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"stress": 50.0},
        criteria=[{"name": "s", "value_key": "stress", "operator": "<=", "limit": 100.0}],
        evidence_manifest=manifest,
        base_dir=tmp_path,
        require_evidence=True,
    )
    assert res.passed is False
    assert res.status == "BLOCKED"
    assert res.result_validity == "RESULT_INVALID"
    assert res.gates["evidence_sufficiency"] == "FAIL"
    assert any("missing_mandatory_role" in f for f in res.failures)


def test_scenario_3_evidence_manifest_hash_mismatch_is_blocked(tmp_path: Path):
    """Scenario 3: EvidenceManifest hash mismatch -> BLOCKED."""
    for ext in ("inp", "odb", "sta", "msg", "dat", "log"):
        (tmp_path / f"job.{ext}").write_bytes(b"original content")
    fnames = [f"job.{ext}" for ext in ("inp", "odb", "sta", "msg", "dat", "log")]

    manifest = build_evidence_manifest_v2(
        run_id="run_tamper",
        case_id="case_tamper",
        artifacts_dir=tmp_path,
        artifact_filenames=fnames,
    )

    # Mutate byte on disk
    (tmp_path / "job.odb").write_bytes(b"tampered content")

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"stress": 50.0},
        criteria=[{"name": "s", "value_key": "stress", "operator": "<=", "limit": 100.0}],
        evidence_manifest=manifest,
        base_dir=tmp_path,
        require_evidence=True,
    )
    assert res.passed is False
    assert res.status == "BLOCKED"
    assert res.result_validity == "RESULT_INVALID"
    assert res.gates["evidence_sufficiency"] == "FAIL"
    assert any("hash_mismatch" in f or "tampered" in f for f in res.failures)


def test_scenario_4_external_input_strictly_prohibits_accepted_state():
    """Scenario 4: external_input with all values correct -> cannot transition to ACCEPTED."""
    from abaqus_ai_agent.execution.client import AbaqusExecutor

    class MockExecutor(AbaqusExecutor):
        def __init__(self):
            self.executed_commands = []

        def execute(self, code, timeout=120):
            self.executed_commands.append(code)
            if "mdb.jobs[" in code and "status" in code:
                return "COMPLETED"
            return {"status": "completed"}

        def inspect_odb(self, path):
            return {"status": "available", "steps": ["Step-1"]}

    runner = AnalysisRunner(MockExecutor())
    run_res = runner.run(
        model_name="Model-1",
        job_name="Job-Injected",
        odb_path="dummy.odb",
        result_values={"max_mises": 50.0, "max_displacement": 0.01},
        criteria=[
            {"name": "stress", "value_key": "max_mises", "operator": "<=", "limit": 100.0},
            {"name": "disp", "value_key": "max_displacement", "operator": "<=", "limit": 0.1},
        ],
    )
    assert run_res.state != AnalysisRunState.ACCEPTED
    assert run_res.state == AnalysisRunState.RESULTS_EXTRACTED
    assert run_res.engineering_status == EngineeringStatus.RESULT_SUSPICIOUS.value
    assert run_res.acceptance_passed is False


def test_scenario_5_preflight_blocking_failure_aborts_before_job():
    """Scenario 5: Preflight blocking failure -> job is never created or submitted."""
    class MockExecutorWithJobTracking:
        def __init__(self):
            self.job_created = False
            self.job_submitted = False

        def execute(self, code):
            if "mdb.Job(" in code:
                self.job_created = True
            if ".submit(" in code:
                self.job_submitted = True
            return ""

    mock_exec = MockExecutorWithJobTracking()
    runner = AnalysisRunner(mock_exec)

    invalid_plan = [
        {
            "action_type": "static_step",
            "model_name": "Model-1",
            "target": "Step-2",
            "parameters": {"name": "Step-2", "previous": "NonExistentStep"},
        }
    ]

    run_res = runner.run(
        model_name="Model-1",
        job_name="Job-PreflightFail",
        action_plan=invalid_plan,
    )
    assert run_res.state == AnalysisRunState.FAILED
    assert run_res.engineering_status == EngineeringStatus.EXECUTION_FAILED.value
    assert mock_exec.job_created is False
    assert mock_exec.job_submitted is False
    assert any("preflight_blocker" in d for d in run_res.diagnostics)


def test_scenario_6_mp_golden_without_evidence_binding_is_blocked():
    """Scenario 6: MP Golden without evidence binding -> BLOCKED."""
    extracted = {
        "max_temperature": 100.0,
        "reaction_force": 10080.0,
        "max_mises": 75.0,
        "reaction_equilibrium_sum": 0.0,
        "available_fields": ["NT", "U", "S", "RF"],
    }
    res = evaluate_result_acceptance(
        result_status="completed",
        physics_domain="thermal_structural",
        odb_status="valid",
        values=extracted,
        odb_fields=extracted["available_fields"],
        criteria=[
            {"name": "temperature_gradient", "value_key": "max_temperature", "operator": ">=", "limit": 99.0},
            {"name": "thermal_reaction_balance", "value_key": "reaction_force", "operator": ">=", "limit": 9000.0},
        ],
        thermal_balance=type("TB", (), {"passed": True})(),
        require_evidence=True,
        evidence_manifest=None,
    )
    assert res.passed is False
    assert res.status == "BLOCKED"
    assert res.result_validity == "RESULT_INVALID"
    assert res.gates["evidence_sufficiency"] == "BLOCKED"
    assert "missing_required_evidence" in res.blocked


def test_scenario_7_legacy_v1_manifest_rejected_as_rc_evidence():
    """Scenario 7: legacy V1 manifest (golden_matrix_manifest.json) -> rejected as RC evidence."""
    legacy_manifest_path = Path(__file__).resolve().parent.parent / "machine_validation" / "golden_matrix_manifest.json"
    manifest_data = json.loads(legacy_manifest_path.read_text(encoding="utf-8"))

    report = verify_evidence_integrity(manifest_data)
    assert report.valid is False
    assert report.validity == "INCOMPLETE"
    assert "unsupported_legacy_manifest:schema_v1_deprecated_for_rc" in report.failures

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"tip_displacement": 1.0},
        criteria=[{"name": "disp", "value_key": "tip_displacement", "operator": "<=", "limit": 2.0}],
        evidence_manifest=manifest_data,
        require_evidence=True,
    )
    assert res.passed is False
    assert res.status == "BLOCKED"
    assert res.result_validity == "RESULT_INVALID"
    assert res.gates["evidence_sufficiency"] == "FAIL"
    assert "unsupported_legacy_manifest:schema_v1_deprecated_for_rc" in res.failures


def test_scenario_8_normal_real_abaqus_and_v2_accepted(tmp_path: Path):
    """Scenario 8: Normal REAL_ABAQUS + V2 -> ACCEPTED, PASS."""
    for ext in ("inp", "odb", "sta", "msg", "dat", "log"):
        (tmp_path / f"job.{ext}").write_bytes(f"Content of {ext}".encode("utf-8"))
    fnames = [f"job.{ext}" for ext in ("inp", "odb", "sta", "msg", "dat", "log")]

    manifest = build_evidence_manifest_v2(
        run_id="run_valid_rc",
        case_id="Job-RC-Valid",
        artifacts_dir=tmp_path,
        artifact_filenames=fnames,
        environment={"os": "windows", "solver_version": "Abaqus 2025"},
    )

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"tip_disp": 1.25, "root_stress": 85.0},
        criteria=[
            {"name": "disp", "value_key": "tip_disp", "operator": "<=", "limit": 2.0},
            {"name": "stress", "value_key": "root_stress", "operator": "<=", "limit": 100.0},
        ],
        evidence_manifest=manifest,
        base_dir=tmp_path,
        require_evidence=True,
    )
    assert res.passed is True
    assert res.status == "PASS"
    assert res.result_validity == "VALID"
    assert res.gates["evidence_sufficiency"] == "PASS"
    assert res.audit_summary == "Solver: PASS | ODB: PASS | Required Result: PASS | Engineering Acceptance: PASS"
