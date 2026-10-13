# ===========================================================================
# Unit and Contract Tests for User Model Input Modes (Task 35.4)
# ===========================================================================
import hashlib
from pathlib import Path
import pytest

from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.execution.input_modes import (
    UserInputKind,
    _compute_file_sha256,
    open_user_cae_working_copy,
    postprocess_user_odb,
    solve_user_inp,
)
from abaqus_ai_agent.paths import ExternalProjectContext, create_external_project_context


class DummyInpExecutor:
    """Mock executor tracking run_input invocations."""

    def __init__(self):
        self.invocations = []

    def run_input(self, input_path, job_name=None, timeout=None):
        self.invocations.append({
            "input_path": input_path,
            "job_name": job_name,
            "timeout": timeout,
        })
        return {"returncode": 0, "stdout": "Job completed successfully", "stderr": ""}


class DummyCaeExecutor:
    """Mock executor tracking script execution."""

    def __init__(self):
        self.executed_scripts = []

    def execute(self, code):
        self.executed_scripts.append(code)
        return '{"models": ["Model-1"], "parts": ["Part-1"], "jobs": ["Job-1"]}'


def _make_dummy_project(tmp_path: Path) -> ExternalProjectContext:
    root = tmp_path / "ExternalDemo"
    return create_external_project_context(root)


def test_solve_user_inp_direct_solver_preserves_source(tmp_path):
    """Verify solve_user_inp calls executor.run_input directly and source INP is not mutated."""
    inp_content = b"*HEADING\nDirect INP Test\n*NODE\n1, 0., 0., 0.\n*STEP\n*STATIC\n*END STEP\n"
    inp_file = tmp_path / "cantilever.inp"
    inp_file.write_bytes(inp_content)
    orig_sha = hashlib.sha256(inp_content).hexdigest()

    executor = DummyInpExecutor()
    res = solve_user_inp(
        executor=executor,
        inp_path=inp_file,
        job_name="CantileverJob",
    )

    assert res["status"] == "COMPLETED"
    assert res["input_kind"] == UserInputKind.INP_SOLVER_DIRECT.value
    assert res["job_name"] == "CantileverJob"
    assert res["inp_sha256"] == orig_sha
    # Verify executor was called with run_input directly
    assert len(executor.invocations) == 1
    assert executor.invocations[0]["input_path"] == str(inp_file.resolve())
    assert executor.invocations[0]["job_name"] == "CantileverJob"
    # Ensure source file content is completely intact
    assert inp_file.read_bytes() == inp_content


def test_solve_user_inp_with_external_project_context(tmp_path):
    """Verify solve_user_inp establishes isolated solver workspace under project_context."""
    ctx = _make_dummy_project(tmp_path)
    inp_file = ctx.input_dir / "bracket.inp"
    inp_file.write_text("*HEADING\nBracket Job\n")

    executor = DummyInpExecutor()
    res = solve_user_inp(
        executor=executor,
        inp_path=inp_file,
        project_context=ctx,
        run_id="run_inp_001",
    )

    assert res["run_id"] == "run_inp_001"
    assert res["workdir"] == str((ctx.solver_dir / "run_inp_001").resolve())
    assert (ctx.solver_dir / "run_inp_001").is_dir()


def test_postprocess_user_odb_readonly_mode(tmp_path, monkeypatch):
    """Verify postprocess_user_odb enforces read-only mode and does not launch solvers."""
    ctx = _make_dummy_project(tmp_path)
    dummy_odb = ctx.input_dir / "result.odb"
    dummy_odb.write_bytes(b"AUTHENTIC_DUMMY_ODB_CONTENT_12345")
    odb_sha = hashlib.sha256(b"AUTHENTIC_DUMMY_ODB_CONTENT_12345").hexdigest()

    # Postprocess without extraction requirements
    res = postprocess_user_odb(
        odb_path=dummy_odb,
        project_context=ctx,
        run_id="run_post_001",
    )

    assert res["status"] == "COMPLETED"
    assert res["input_kind"] == UserInputKind.ODB_READONLY.value
    assert res["odb_sha256"] == odb_sha
    assert (ctx.evidence_dir / "run_post_001").is_dir()
    # ODB remains unchanged
    assert dummy_odb.read_bytes() == b"AUTHENTIC_DUMMY_ODB_CONTENT_12345"


def test_open_user_cae_working_copy_zero_mutation(tmp_path):
    """Verify open_user_cae_working_copy clones into working/ and generates openMdb script."""
    ctx = _make_dummy_project(tmp_path)
    src_cae = ctx.input_dir / "model.cae"
    src_cae.write_bytes(b"DUMMY_CAE_DATABASE_V1")
    src_sha = hashlib.sha256(b"DUMMY_CAE_DATABASE_V1").hexdigest()

    executor = DummyCaeExecutor()
    res = open_user_cae_working_copy(
        cae_path=src_cae,
        project_context=ctx,
        executor=executor,
        target_filename="model_working.cae",
    )

    assert res["status"] == "PREPARED"
    assert res["input_kind"] == UserInputKind.CAE_WORKING_COPY.value
    assert res["original_cae_sha256"] == src_sha
    assert Path(res["working_cae_path"]).is_file()
    assert Path(res["working_cae_path"]).name == "model_working.cae"
    # Working CAE is inside working_dir
    assert Path(res["working_cae_path"]).parent == ctx.working_dir.resolve()
    # openMdb script was emitted and executed
    assert "openMdb(pathName=" in res["open_script"]
    assert len(executor.executed_scripts) >= 1
    assert "openMdb(pathName=" in executor.executed_scripts[0]
    assert res["model_info"] is not None
    # Original file is untouched
    assert src_cae.read_bytes() == b"DUMMY_CAE_DATABASE_V1"


def test_agent_user_input_wrappers_integration(tmp_path):
    """Verify AbaqusAIAgent exposes solve_user_inp, postprocess_user_odb, prepare_user_cae."""
    ctx = _make_dummy_project(tmp_path)
    executor = DummyInpExecutor()
    agent = AbaqusAIAgent(executor=executor)

    # 1. Agent solve_user_inp
    test_inp = ctx.input_dir / "plate.inp"
    test_inp.write_text("*HEADING\nPlate\n")
    inp_res = agent.solve_user_inp(test_inp, project_context=ctx)
    assert inp_res["status"] == "COMPLETED"

    # 2. Agent postprocess_user_odb
    test_odb = ctx.input_dir / "plate.odb"
    test_odb.write_text("ODB_CONTENT")
    odb_res = agent.postprocess_user_odb(test_odb, project_context=ctx)
    assert odb_res["status"] == "COMPLETED"

    # 3. Agent prepare_user_cae
    test_cae = ctx.input_dir / "plate.cae"
    test_cae.write_text("CAE_CONTENT")
    cae_res = agent.prepare_user_cae(test_cae, project_context=ctx)
    assert cae_res["status"] == "PREPARED"
