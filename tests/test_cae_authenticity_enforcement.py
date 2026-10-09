"""Rigorous validation tests enforcing authentic CAE execution and forbidding deceptive shortcuts.

Verifies Universal Engineering Architecture Contracts:
1. Universal Abaqus batch job solver never synthesizes fake solver logs (.sta, .msg, .dat, .log, .odb) when offline.
2. Universal solver fails closed (RuntimeError) when require_live=True and no Abaqus executable is available.
3. ODB authenticator strictly rejects plaintext JSON, XML, or undersized mock files.
4. Universal mesh auditor performs genuine 3D isoparametric Jacobian determinants and INP deck parsing.
5. Inverted/distorted elements parsed from real INP decks fail the pre-solver mesh gatekeeper.
6. Anti-Cheat scan: No code in the entire repository serializes JSON into an .odb file.
7. Production acceptance kernel strictly rejects delivery if metrics lack authentic ResultExtraction lineage.
8. Production acceptance kernel enforces exact unit consistency between Criteria and Extractions.
9. ODB required fields gatekeeper enforces exact equality matching, completely eliminating substring loopholes.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.mesh_audit import (
    audit_hex_element,
    audit_quad_element,
    parse_and_audit_inp_deck,
    audit_inp_mesh_quality,
)
from abaqus_ai_agent.execution.solver import (
    AbaqusBatchJob,
    execute_abaqus_batch_job,
    is_authentic_binary_odb,
)
from abaqus_ai_agent.acceptance import (
    evaluate_production_acceptance,
    evaluate_result_acceptance,
)
from abaqus_ai_agent.contracts.results import ResultRequirement, ResultExtraction
from abaqus_ai_agent.contracts.evidence import ArtifactRecord, EvidenceManifestV2
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
from abaqus_ai_agent.execution.jobs import JobStatus, JobState
from abaqus_ai_agent.contracts.provenance import AnalysisProvenance


def test_universal_solver_dry_run_never_synthesizes_fake_solver_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Universal solver must NEVER synthesize fake .sta, .msg, .dat, .log, or .odb files when offline."""
    import abaqus_ai_agent.execution.solver as solver_module

    # Force solver to offline branch regardless of host machine
    monkeypatch.setattr(solver_module, "find_abaqus_executable", lambda *args, **kwargs: None)

    inp_path = tmp_path / "test_model.inp"
    inp_path.write_text("*HEADING\n*NODE\n1,0,0,0\n*ELEMENT,TYPE=MASS\n1,1\n", encoding="utf-8")

    job = AbaqusBatchJob(
        job_name="authentic_job",
        inp_path=inp_path,
        workdir=tmp_path,
    )

    res = execute_abaqus_batch_job(job, require_live=False, launcher_cmd=None)

    assert res.state == "DRY_RUN"
    assert res.is_live is False

    # In offline mode, no fake solver logs must be created on disk
    fake_log_extensions = [".sta", ".msg", ".dat", ".log", ".odb"]
    for ext in fake_log_extensions:
        found_files = list(tmp_path.glob(f"*{ext}"))
        assert len(found_files) == 0, f"Deceptive fake solver output {ext} detected in offline workdir: {found_files}"


def test_universal_solver_fails_closed_when_require_live_and_no_solver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Universal solver must raise RuntimeError fail-closed when live execution is strictly required."""
    import abaqus_ai_agent.execution.solver as solver_module

    monkeypatch.setattr(solver_module, "find_abaqus_executable", lambda *args, **kwargs: None)

    inp_path = tmp_path / "model.inp"
    inp_path.write_text("*HEADING\n", encoding="utf-8")

    job = AbaqusBatchJob(job_name="job_must_fail", inp_path=inp_path, workdir=tmp_path)

    with pytest.raises(RuntimeError, match="Abaqus solver executable not found"):
        execute_abaqus_batch_job(job, require_live=True, launcher_cmd=None)


def test_is_authentic_binary_odb_rejects_fake_json_and_small_files(tmp_path: Path):
    """ODB authenticator must reject plaintext JSON mocks and files below valid size."""
    # 1. Non-existent file
    assert is_authentic_binary_odb(tmp_path / "missing.odb") is False

    # 2. Small file < 1024 bytes
    small_odb = tmp_path / "small.odb"
    small_odb.write_bytes(b"A" * 100)
    assert is_authentic_binary_odb(small_odb) is False

    # 3. Plaintext JSON disguised as ODB
    json_odb = tmp_path / "fake_json.odb"
    json_data = json.dumps({"stress": [100.0, 200.0], "model": "fake"}).encode("utf-8")
    json_odb.write_bytes(json_data + b" " * 2000)
    assert is_authentic_binary_odb(json_odb) is False

    # 4. Valid binary file
    valid_odb = tmp_path / "valid.odb"
    valid_odb.write_bytes(b"\x7fSIMULIA\x00\x01\x02\x03" + b"\x00" * 4096)
    assert is_authentic_binary_odb(valid_odb) is True


def test_hex_mesh_audit_computes_genuine_3d_jacobian():
    """Verify Hex element audit uses genuine isoparametric shape function derivatives and determinant."""
    # Ideal unit cube [0, 1]^3: min_det == 1.0, AR == 1.0, Jacobian ratio == 1.0
    pts_cube = (
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
    )
    res_cube = audit_hex_element(1, pts_cube)
    assert res_cube.aspect_ratio == 1.0
    assert res_cube.jacobian_ratio >= 0.99
    assert res_cube.min_angle_deg == 90.0
    assert res_cube.max_angle_deg == 90.0

    # Stretched hex: 3x1x1 -> AR == 3.0
    pts_stretched = (
        (0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0), (3.0, 0.0, 1.0), (3.0, 1.0, 1.0), (0.0, 1.0, 1.0),
    )
    res_str = audit_hex_element(2, pts_stretched)
    assert res_str.aspect_ratio == 3.0
    assert res_str.jacobian_ratio >= 0.99

    # Inverted hex (top and bottom nodes swapped along Z -> negative volume)
    pts_inverted = (
        (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
    )
    res_inv = audit_hex_element(3, pts_inverted)
    assert res_inv.jacobian_ratio <= 0.0, "Inverted element must yield zero or negative Jacobian ratio"


def test_parse_and_audit_inp_deck_detects_real_deck_topologies(tmp_path: Path):
    """Verify INP parser reads *NODE and *ELEMENT lines and audits elements deterministically."""
    inp_content = """*HEADING
Test Deck
*PART, NAME=Part-1
*NODE
1, 0.0, 0.0, 0.0
2, 10.0, 0.0, 0.0
3, 10.0, 10.0, 0.0
4, 0.0, 10.0, 0.0
*ELEMENT, TYPE=S4R, ELSET=ShellSet
101, 1, 2, 3, 4
*END PART
"""
    inp_file = tmp_path / "test_model.inp"
    inp_file.write_text(inp_content, encoding="utf-8")

    parsed = parse_and_audit_inp_deck(inp_file)
    assert parsed["nodes_count"] == 4
    assert parsed["quad_elements_count"] == 1
    assert len(parsed["audited_quads"]) == 1
    quad = parsed["audited_quads"][0]
    assert quad.element_id == 101
    assert quad.aspect_ratio == 1.0
    assert quad.jacobian_ratio >= 0.99


def test_audit_inp_mesh_quality_fails_closed_on_inverted_quad(tmp_path: Path):
    """A generated INP deck containing distorted elements must fail the pre-solver mesh gate."""
    # Quad with node 4 severely pulled inward creating a concave, inverted corner (non-convex inverted quad)
    inverted_inp = tmp_path / "inverted.inp"
    inverted_inp.write_text(
        "*NODE\n"
        "1, 0.0, 0.0, 0.0\n"
        "2, 10.0, 0.0, 0.0\n"
        "3, 10.0, 10.0, 0.0\n"
        "4, 8.0, 1.0, 0.0\n"  # Concave interior angle > 180 degrees / inverted corner
        "*ELEMENT, TYPE=S4R\n"
        "1, 1, 2, 3, 4\n",
        encoding="utf-8",
    )

    gate_eval, report = audit_inp_mesh_quality(inverted_inp)
    assert gate_eval.passed is False
    assert gate_eval.status == "BLOCKED"
    assert any("Inverted element detected" in v for v in gate_eval.violations)


def test_no_json_dumps_to_odb_across_entire_repo():
    """Anti-Cheat scan: No Python file in the codebase may serialize JSON directly into an .odb file."""
    root = Path(__file__).resolve().parent.parent
    src_dir = root / "src"
    py_files = list(src_dir.rglob("*.py"))

    for py_file in py_files:
        text = py_file.read_text(encoding="utf-8")
        assert "odb_path.write_text(json.dumps" not in text, f"Fake JSON ODB writer found in {py_file}"
        assert ".odb.write_text(json.dumps" not in text, f"Fake JSON ODB writer found in {py_file}"


def test_production_acceptance_fails_closed_without_extractions():
    """Production acceptance gate strictly forbids delivering results without ResultExtraction lineage."""
    inp_sha = "a" * 64
    manifest = EvidenceManifestV2(
        run_id="RUN-PROD-001",
        created_at="2026-10-09T00:00:00Z",
        artifacts={
            "job.inp": ArtifactRecord(name="job.inp", path="/path/job.inp", role="inp", exists=True, size_bytes=100, sha256=inp_sha, mandatory=True),
            "job.odb": ArtifactRecord(name="job.odb", path="/path/job.odb", role="odb", exists=True, size_bytes=5000, sha256="b"*64, mandatory=True),
        },
    ).with_signature()

    run = AnalysisRun(
        id="RUN-PROD-001",
        model_name="M",
        job_name="J",
        state=AnalysisRunState.COMPLETED,
        job_status=JobStatus(name="J", state=JobState.COMPLETED),
        provenance=AnalysisProvenance(run_id="RUN-PROD-001", model_name="M", job_name="J", input_hash=inp_sha),
    )

    criteria = [{"name": "max_stress", "value_key": "max_mises", "operator": "<=", "limit": 250.0, "unit": "MPa"}]

    # Injected values without ResultExtractions must be blocked
    res = evaluate_production_acceptance(
        analysis_run=run,
        values={"max_mises": 150.0},
        criteria=criteria,
        evidence_manifest=manifest,
        result_extractions=None,  # Missing lineage
    )

    assert res.passed is False
    assert res.deliverable is False
    assert res.status == "BLOCKED"
    assert any("missing_required_result_extractions" in b for b in res.findings.blocked)


def test_production_acceptance_unit_mismatch_blocks_delivery():
    """Unit discrepancy between engineering Criterion and Extraction lineage must block production deliverable."""
    inp_sha = "a" * 64
    manifest = EvidenceManifestV2(
        run_id="RUN-PROD-002",
        created_at="2026-10-09T00:00:00Z",
        artifacts={
            "job.inp": ArtifactRecord(name="job.inp", path="/path/job.inp", role="inp", exists=True, size_bytes=100, sha256=inp_sha, mandatory=True),
            "job.odb": ArtifactRecord(name="job.odb", path="/path/job.odb", role="odb", exists=True, size_bytes=5000, sha256="b"*64, mandatory=True),
        },
    ).with_signature()

    run = AnalysisRun(
        id="RUN-PROD-002",
        model_name="M",
        job_name="J",
        state=AnalysisRunState.COMPLETED,
        job_status=JobStatus(name="J", state=JobState.COMPLETED),
        provenance=AnalysisProvenance(run_id="RUN-PROD-002", model_name="M", job_name="J", input_hash=inp_sha),
    )

    req = ResultRequirement(name="max_stress", value_key="max_mises", field="S", unit="GPa")  # Discrepancy! Criterion expects MPa
    extraction = ResultExtraction(requirement=req, value=0.150, locator={"field": "S", "step": "Step-1"})

    criteria = [{"name": "max_stress", "value_key": "max_mises", "operator": "<=", "limit": 250.0, "unit": "MPa"}]

    res = evaluate_production_acceptance(
        analysis_run=run,
        values={"max_mises": 150.0},
        criteria=criteria,
        evidence_manifest=manifest,
        result_extractions=[extraction],
    )

    assert res.passed is False
    assert res.deliverable is False
    assert res.status == "BLOCKED"
    assert any("unit_mismatch" in b for b in res.findings.blocked)


def test_odb_required_fields_exact_match_not_substring():
    """Verifies that ODB field evaluation strictly matches exact field names and eliminates substring matching."""
    # "S" (Stress) is required, but available fields only contain "CSHEAR"
    res = evaluate_result_acceptance(
        result_status="completed",
        require_evidence=False,
        required_fields=["S"],
        odb_fields=["CSHEAR", "STATUS"],
    )
    assert res.passed is False
    assert "S" in res.missing_required_fields
    assert "missing_required_field:S" in res.failures

    # When ODB fields is empty list and required fields exist, it must fail-closed immediately
    res_empty = evaluate_result_acceptance(
        result_status="completed",
        require_evidence=False,
        required_fields=["S", "U"],
        odb_fields=[],
    )
    assert res_empty.passed is False
    assert set(res_empty.missing_required_fields) == {"S", "U"}
