"""Tests for Production Delivery Full-Chain Acceptance Contracts and Tooling (REQ-ISO-002, REQ-P1-036)."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import pytest

from abaqus_ai_agent.paths import (
    ExternalProjectContext,
    get_repo_root,
)
from abaqus_ai_agent.execution.solver import find_abaqus_executable
from abaqus_ai_agent.execution.odb_extractor import (
    _resolve_safe_odb_region,
    _extract_single_requirement_in_process,
    OdbExtractionError,
    ExtractionFieldNotFoundError,
)
from abaqus_ai_agent.contracts.results import ResultRequirement
from abaqus_ai_agent.acceptance import (
    evaluate_production_acceptance,
    ResultValidity,
)
from abaqus_ai_agent.contracts.evidence import build_evidence_manifest_v2
from tools.production_delivery_e2e import (
    build_production_delivery_cae_script,
    run_production_delivery_e2e,
    sanitize_report_paths,
)


def test_production_delivery_script_ast_structure(tmp_path: Path):
    """Verify that build_production_delivery_cae_script produces valid, compilable AST."""
    project_root = tmp_path / "mock_project_root"
    project_root.mkdir(parents=True)
    code = build_production_delivery_cae_script(project_root=project_root)

    # Must compile into a valid Python AST module
    parsed = ast.parse(code)
    assert isinstance(parsed, ast.Module)
    assert len(parsed.body) > 10


def test_safe_odb_region_ast_parser_whitelist():
    """Verify safe ODB region parser correctly traverses authentic structural whitelist."""
    class DummySet:
        def __init__(self, name: str):
            self.name = name

    class DummyAssembly:
        def __init__(self):
            self.nodeSets = {"TIP_NODES": DummySet("TIP_NODES")}
            self.instances = {
                "BEAM-1": type("DummyInst", (), {
                    "elementSets": {"ROOT_ELEM": DummySet("ROOT_ELEM")}
                })()
            }

    dummy_odb = type("DummyOdb", (), {"rootAssembly": DummyAssembly()})()

    # 1. Valid nodeSets subscript traversal
    res1 = _resolve_safe_odb_region(dummy_odb, "odb.rootAssembly.nodeSets['TIP_NODES']")
    assert isinstance(res1, DummySet)
    assert res1.name == "TIP_NODES"

    # 2. Valid instance elementSets traversal
    res2 = _resolve_safe_odb_region(dummy_odb, "odb.rootAssembly.instances['BEAM-1'].elementSets['ROOT_ELEM']")
    assert isinstance(res2, DummySet)
    assert res2.name == "ROOT_ELEM"

    # 3. Missing set raises ExtractionFieldNotFoundError (Fail-Closed)
    with pytest.raises(ExtractionFieldNotFoundError, match="Key 'NON_EXISTENT' not found"):
        _resolve_safe_odb_region(dummy_odb, "odb.rootAssembly.nodeSets['NON_EXISTENT']")

    # 4. Missing attribute raises ExtractionFieldNotFoundError (Fail-Closed)
    with pytest.raises(ExtractionFieldNotFoundError, match="Attribute 'unknown_attr' not found"):
        _resolve_safe_odb_region(dummy_odb, "odb.unknown_attr")

    # 5. Non-string object is returned directly
    direct_set = DummySet("DIRECT")
    assert _resolve_safe_odb_region(dummy_odb, direct_set) is direct_set


def test_safe_odb_region_ast_parser_blocks_malicious_code():
    """Verify AST whitelist blocks arbitrary execution, dunder access, calls, and foreign identifiers."""
    dummy_odb = type("DummyOdb", (), {"rootAssembly": None})()

    disallowed_expressions = [
        "__import__('os').system('whoami')",
        "eval('1 + 1')",
        "odb.__class__.__bases__[0]",
        "1 + 2",
        "odb.rootAssembly.nodeSets.keys()",  # Function/method call forbidden
        "unknown_root.nodeSets['SET']",       # Foreign root identifier forbidden
        "",                                   # Empty forbidden
        "   ",
        "lambda: odb",
        "[odb for _ in range(1)]",
    ]

    for expr in disallowed_expressions:
        with pytest.raises(OdbExtractionError):
            _resolve_safe_odb_region(dummy_odb, expr)


def test_production_acceptance_tampered_manifest_fails_closed(tmp_path: Path):
    """Verify that evaluate_production_acceptance fails closed and refuses delivery on tampered manifest."""
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True)
    inp_file = art_dir / "Job-1.inp"
    inp_file.write_text("*HEADING\nCantilever Benchmark\n", encoding="utf-8")

    manifest = build_evidence_manifest_v2(
        run_id="run-prod-001",
        case_id="Job-1",
        artifacts_dir=art_dir,
        artifact_filenames=["Job-1.inp"],
        intent_summary={"model": "Cantilever"},
        required_results={"criteria": []},
    )

    # Tamper with the manifest payload without updating the signature
    manifest_dict = manifest.to_dict()
    manifest_dict["run_id"] = "tampered-run-999"

    class MockRun:
        id = "run-prod-001"
        job_status = type("MockStatus", (), {"state": "completed"})()
        state = "completed"
        odb_path = str(art_dir / "Job-1.odb")
        provenance = type("MockProv", (), {"input_hash": manifest.artifacts["Job-1.inp"].sha256})()
        metrics = ()

    res = evaluate_production_acceptance(
        analysis_run=MockRun(),
        result_status="completed",
        evidence_manifest=manifest_dict,
        values={"stress": 100.0},
        criteria=[{"name": "stress", "limit": 200.0, "operator": "<="}],
    )

    assert res.deliverable is False
    assert res.acceptance_status in ("FAIL", "BLOCKED", "RESULT_INVALID")
    assert res.acceptance_status != "PASS"
    assert str(res.result_validity) in ("EVIDENCE_TAMPERED", "RESULT_INVALID")


def test_odb_extractor_missing_getsubset_fails_closed():
    """Verify that in-process ODB extraction fails closed when subset/filtering methods are missing."""
    class DummyFieldOutputWithoutSubset:
        values = []

    class DummyFrame:
        fieldOutputs = {"S": DummyFieldOutputWithoutSubset()}

    class DummyStep:
        frames = [DummyFrame()]

    dummy_odb = type("DummyOdb", (), {"steps": {"Step-1": DummyStep()}})()

    # 1. Position requested but getSubset missing
    req_pos = ResultRequirement(
        name="test_pos",
        value_key="stress",
        field="S",
        position="INTEGRATION_POINT",
    )
    with pytest.raises(OdbExtractionError, match="does not support position filtering"):
        _extract_single_requirement_in_process(dummy_odb, req_pos)

    # 2. Region requested but getSubset missing
    req_reg = ResultRequirement(
        name="test_reg",
        value_key="stress",
        field="S",
        region="odb.rootAssembly.nodeSets['SET']",
    )
    with pytest.raises(OdbExtractionError, match="does not support region filtering"):
        _extract_single_requirement_in_process(dummy_odb, req_reg)

    # 3. Invariant requested but getScalarField missing
    req_inv = ResultRequirement(
        name="test_inv",
        value_key="stress",
        field="S",
        invariant="MISES",
    )
    with pytest.raises(OdbExtractionError, match="does not support invariant extraction"):
        _extract_single_requirement_in_process(dummy_odb, req_inv)

    # 4. Component requested but getScalarField missing
    req_comp = ResultRequirement(
        name="test_comp",
        value_key="stress",
        field="S",
        component="S11",
    )
    with pytest.raises(OdbExtractionError, match="does not support component extraction"):
        _extract_single_requirement_in_process(dummy_odb, req_comp)


def test_production_acceptance_mismatched_odb_fails_closed(tmp_path: Path):
    """Verify that evaluate_production_acceptance fails closed when ODB live hash does not match manifest."""
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True)
    inp_file = art_dir / "Job-1.inp"
    inp_file.write_text("*HEADING\nCantilever Benchmark\n", encoding="utf-8")
    odb_file = art_dir / "Job-1.odb"
    odb_file.write_bytes(b"DUMMY_AUTHENTIC_SIMULIA_ODB_BINARY_CONTENT")

    manifest = build_evidence_manifest_v2(
        run_id="run-prod-002",
        case_id="Job-1",
        artifacts_dir=art_dir,
        artifact_filenames=["Job-1.inp", "Job-1.odb"],
        intent_summary={"model": "Cantilever"},
        required_results={"criteria": []},
    )

    # Now tamper with the ODB file on disk (or simulate swapped/corrupted ODB)
    odb_file.write_bytes(b"TAMPERED_SUBSTITUTED_ODB_CONTENT")

    class MockRun:
        id = "run-prod-002"
        job_status = type("MockStatus", (), {"state": "completed"})()
        state = "completed"
        odb_path = str(odb_file)
        provenance = type("MockProv", (), {"input_hash": manifest.artifacts["Job-1.inp"].sha256})()
        metrics = ()

    res = evaluate_production_acceptance(
        analysis_run=MockRun(),
        result_status="completed",
        evidence_manifest=manifest,
        values={"stress": 100.0},
        criteria=[{"name": "stress", "limit": 200.0, "operator": "<="}],
    )

    assert res.deliverable is False
    assert res.acceptance_status in ("FAIL", "BLOCKED", "RESULT_INVALID")
    assert res.acceptance_status != "PASS"
    assert str(res.result_validity) in ("EVIDENCE_TAMPERED", "RESULT_INVALID")
    assert any("evidence_tampered" in str(f) or "sha256_mismatch" in str(f) for f in res.findings.failures)


def test_production_delivery_context_isolation_contracts():
    """Verify that ExternalProjectContext strictly rejects repository-internal roots in production."""
    repo_root = get_repo_root()
    internal_target = repo_root / "runs" / "unauthorized_production_root"

    with pytest.raises((PermissionError, ValueError), match="escapes external root|Security violation|outside repository"):
        ExternalProjectContext.create(
            project_root=internal_target,
            project_name="ViolatingProject",
            enforce_outside_repo=True,
        )


def test_production_delivery_launcher_missing_fails_closed(tmp_path: Path):
    """Verify that production delivery execution fails closed if launcher is missing or invalid."""
    with pytest.raises(RuntimeError, match="Authentic Abaqus launcher not found"):
        run_production_delivery_e2e(launcher="non_existent_abaqus_binary_xyz_123")


@pytest.mark.skipif(
    not bool(find_abaqus_executable()),
    reason="Authentic SIMULIA Abaqus launcher required on host for live production delivery e2e",
)
@pytest.mark.live
def test_production_delivery_live_e2e_gate():
    """Live full-chain acceptance gate running against authentic Abaqus 2025."""
    report = run_production_delivery_e2e(timeout=1800)
    assert report["status"] == "pass"
    assert report["run_state"].lower() == "accepted"
    assert report["engineering_status"] == "RESULT_VALID"
    assert report["deliverable"] is True
    assert report["acceptance_status"] == "PASS"
    assert report["result_validity"] == "VALID"
    assert report["reaction_balance_passed"] is True
    assert report["manifest_signature_verified"] is True
    assert report["causal_run_id_bound"] is True
    assert bool(report.get("actual_odb_sha256") or report.get("odb_sha256"))
    assert bool(report.get("inp_hash"))


# --- Remediation review: causal run-id binding is a mandatory PASS gate -------


def _passing_delivery_report() -> dict:
    return {
        "status": "pass",
        "run_state": "ACCEPTED",
        "engineering_status": "RESULT_VALID",
        "deliverable": True,
        "acceptance_status": "PASS",
        "result_validity": "VALID",
        "reaction_balance_passed": True,
        "manifest_integrity_verified": True,
        "manifest_signature_verified": True,
        "causal_run_id_bound": True,
        "odb_hash_matches_manifest": True,
        "actual_odb_sha256": "ab" * 32,
        "manifest_odb_sha256": "ab" * 32,
        "inp_hash": "cd" * 32,
    }


def test_delivery_contracts_accept_fully_bound_report():
    from tools.production_delivery_e2e import assert_production_delivery_contracts

    assert_production_delivery_contracts(_passing_delivery_report())


def test_delivery_contracts_reject_foreign_run_manifest():
    """A manifest belonging to a different run must fail closed even when its
    signature and ODB hash are otherwise valid."""
    from tools.production_delivery_e2e import assert_production_delivery_contracts

    report = _passing_delivery_report()
    report["causal_run_id_bound"] = False
    with pytest.raises(AssertionError, match="run ID binding"):
        assert_production_delivery_contracts(report)


def test_cae_template_binds_run_id_into_pass_condition(tmp_path: Path):
    """The CAE-side status computation must include causal_run_id_bound."""
    code = build_production_delivery_cae_script(project_root=tmp_path / "mock_project_root2")
    ast.parse(code)
    status_idx = code.index("'status': 'pass' if (")
    status_block = code[status_idx:status_idx + 800]
    assert "causal_run_id_bound" in status_block


# --- Published evidence must not carry host-absolute paths --------------------


def _report_with_absolute_paths(project_root: Path) -> dict:
    run_dir = project_root / "solver" / "run-1"
    return {
        "status": "pass",
        "odb_path": str(run_dir / "Job.odb"),
        "artifacts": [
            {"suffix": ".inp", "path": str(run_dir / "Job.inp")},
            {"suffix": ".odb", "path": str(run_dir / "Job.odb")},
        ],
        "metrics": {"root_mises_sanity": 471.214080810547},
    }


def test_sanitize_report_paths_strips_project_absolute_prefix(tmp_path: Path):
    project_root = tmp_path / "external_project"
    project_root.mkdir()
    report = _report_with_absolute_paths(project_root)

    sanitize_report_paths(report, project_root=project_root)

    assert report["odb_path"] == "<PROJECT_ROOT>/solver/run-1/Job.odb"
    assert [a["path"] for a in report["artifacts"]] == [
        "<PROJECT_ROOT>/solver/run-1/Job.inp",
        "<PROJECT_ROOT>/solver/run-1/Job.odb",
    ]
    for artifact in report["artifacts"]:
        assert str(tmp_path) not in artifact["path"]


def test_sanitize_report_paths_preserves_verdict_fields(tmp_path: Path):
    project_root = tmp_path / "external_project"
    project_root.mkdir()
    report = _report_with_absolute_paths(project_root)

    sanitize_report_paths(report, project_root=project_root)

    assert report["status"] == "pass"
    assert report["metrics"]["root_mises_sanity"] == 471.214080810547


def test_sanitize_report_paths_leaves_foreign_paths_visible(tmp_path: Path):
    """A path outside the project root is a containment violation, not a path to rewrite."""
    project_root = tmp_path / "external_project"
    project_root.mkdir()
    outside = tmp_path / "elsewhere" / "Job.odb"
    report = {"odb_path": str(outside), "artifacts": []}

    sanitize_report_paths(report, project_root=project_root)

    assert report["odb_path"] == str(outside)


def test_sanitize_report_paths_handles_missing_and_null_paths(tmp_path: Path):
    project_root = tmp_path / "external_project"
    project_root.mkdir()
    report = {"odb_path": None, "artifacts": [{"suffix": ".odb", "path": ""}]}

    sanitize_report_paths(report, project_root=project_root)

    assert report["odb_path"] is None
    assert report["artifacts"][0]["path"] == ""


def test_persisted_delivery_evidence_has_no_user_profile_path():
    """Committed delivery evidence is published and must stay host-independent."""
    import re

    evidence = Path(__file__).resolve().parent.parent / "machine_validation" / "prod_deliv_kn_phase_b.json"
    assert evidence.is_file()
    text = evidence.read_text(encoding="utf-8")
    assert re.search(r"[A-Za-z]:\\{1,2}Users\\{1,2}", text) is None
    assert "AppData" not in text
    assert "<PROJECT_ROOT>/solver/" in text
