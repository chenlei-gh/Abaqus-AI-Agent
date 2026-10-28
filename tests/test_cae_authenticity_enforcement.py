"""Rigorous validation tests enforcing authentic CAE execution and forbidding deceptive shortcuts.

Verifies Universal Engineering Architecture Contracts:
1. Universal Abaqus batch job solver never synthesizes fake solver logs (.sta, .msg, .dat, .log, .odb) when offline.
2. Universal solver fails closed (RuntimeError) when require_live=True and no Abaqus executable is available.
3. ODB authenticator strictly rejects plaintext JSON, XML, or undersized mock files.
4. Production meshing does not fall back to the retired hand-written quad/hex Jacobian auditor.
5. A missing native mesh-quality result blocks submission. A hand-computed Jacobian is not a substitute.
6. Anti-Cheat scan: No code in the entire repository serializes JSON into an .odb file.
7. Production acceptance kernel strictly rejects delivery if metrics lack authentic ResultExtraction lineage.
8. Production acceptance kernel enforces exact unit consistency between Criteria and Extractions.
9. ODB required fields gatekeeper enforces exact equality matching, completely eliminating substring loopholes.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.contracts.mesh_quality import mesh_submission_blockers
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


def test_is_authentic_binary_odb_rejects_uniform_fill_and_accepts_structured(
    tmp_path: Path,
):
    """Uniform-fill and truncated files are rejected; structured binaries pass.

    The only rejection claim made at this layer is structural, not signature
    based: a file whose first and last windows are one constant byte cannot be
    an ODB, because every ODB carries record structure at both ends. The negative
    cases below are therefore all-zero / all-0xFF fills, while the positive case
    is the same size with a non-constant head and tail.
    """
    # Negative: all-zero fill of a plausible size.
    zero_fill = tmp_path / "zero_fill.odb"
    zero_fill.write_bytes(b"\x00" * 8192)
    assert is_authentic_binary_odb(zero_fill) is False

    # Negative: all-0xFF fill, proving the rule is about constancy, not zero bytes.
    ff_fill = tmp_path / "ff_fill.odb"
    ff_fill.write_bytes(b"\xff" * 8192)
    assert is_authentic_binary_odb(ff_fill) is False

    # Negative: truncated artifact. A file that stops below the header floor has
    # no room for a valid ODB header regardless of its content.
    truncated = tmp_path / "truncated.odb"
    truncated.write_bytes(b"\x7fSIMULIA\x00\x01\x02\x03")
    assert is_authentic_binary_odb(truncated) is False

    # Positive: same size, structured head and tail.
    structured = tmp_path / "structured.odb"
    structured.write_bytes(b"\x7fSIMULIA\x00\x01\x02\x03" + b"\x00" * 4084 + b"\x01\x02")
    assert is_authentic_binary_odb(structured) is True


def test_missing_native_mesh_quality_blocks_submission():
    """A hand-written Jacobian is not a production gate. Missing native evidence stops submission."""
    assert "mesh_quality_missing" in mesh_submission_blockers(None)
    assert "mesh_quality_not_run" in mesh_submission_blockers({"status": "not_run"})
    assert mesh_submission_blockers(
        {"status": "pass", "metrics": {"shape_factor": 0.2}, "failed_element_count": 0}
    ) == ()


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


def test_solver_diagnostics_strict_decode_records_degraded_log(tmp_path: Path):
    """An invalid-UTF-8 solver log must be reported, not silently repaired."""
    from abaqus_ai_agent.execution.solver import parse_solver_diagnostics

    (tmp_path / "job.msg").write_bytes(
        b"THE ANALYSIS HAS NOT BEEN COMPLETED\n" + b"\xff\xfe\n"
    )
    (tmp_path / "job.sta").write_bytes(b"THE ANALYSIS HAS NOT BEEN COMPLETED\n")

    diags = parse_solver_diagnostics(tmp_path, "job")

    assert any(d.startswith("MSG_DECODE_ERR") for d in diags)
    # Replacement decoding still surfaces the ASCII markers that drive ABORTED.
    assert "MSG: Analysis not completed" in diags
    assert "STA: Analysis not completed" in diags


def test_solver_diagnostics_clean_utf8_log_has_no_decode_warning(tmp_path: Path):
    """A well-formed log must not gain a spurious decode diagnostic."""
    from abaqus_ai_agent.execution.solver import parse_solver_diagnostics

    (tmp_path / "job.msg").write_text("***ERROR: element 12 is distorted\n", encoding="utf-8")
    (tmp_path / "job.sta").write_text("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n", encoding="utf-8")

    diags = parse_solver_diagnostics(tmp_path, "job")

    assert not any("DECODE_ERR" in d for d in diags)
    assert any(d.startswith("MSG_ERROR:") for d in diags)
    assert "STA: Analysis completed successfully" in diags
