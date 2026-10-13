# ===========================================================================
# Unit and Contract Tests for User Model Input Modes (Task 35.4)
# ===========================================================================
import hashlib
from pathlib import Path
import pytest

from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.execution.input_modes import (
    UserInputKind,
    WorkspaceTransaction,
    _compute_file_sha256,
    _parse_returncode,
    _verify_solver_dependencies,
    edit_and_solve_user_inp,
    open_user_cae_working_copy,
    postprocess_user_odb,
    solve_user_inp,
)
from abaqus_ai_agent.paths import ExternalProjectContext, create_external_project_context


class DummyInpExecutor:
    """Mock executor tracking run_input invocations."""

    def __init__(self):
        self.invocations = []
        self.workdir = None

    def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
        self.invocations.append({
            "input_path": input_path,
            "job_name": job_name,
            "timeout": timeout,
            "workdir": workdir,
        })
        target_dir = Path(workdir) if workdir else Path(input_path).parent
        name = job_name or Path(input_path).stem
        odb_file = target_dir / f"{name}.odb"
        if not odb_file.exists():
            odb_file.write_bytes(b"DUMMY_ODB_OUTPUT")
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
    # Contract verification: workdir was propagated into executor
    assert len(executor.invocations) == 1
    assert executor.invocations[0]["workdir"] == str((ctx.solver_dir / "run_inp_001").resolve())


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


def test_open_user_cae_from_arbitrary_external_path(tmp_path):
    """Verify open_user_cae_working_copy accepts source CAE located outside project input_dir."""
    ctx = _make_dummy_project(tmp_path)
    # External CAD directory completely outside project
    external_dir = tmp_path / "OtherVendorCAD"
    external_dir.mkdir()
    source_cae = external_dir / "chassis.cae"
    source_cae.write_bytes(b"AUTHENTIC_EXTERNAL_CHASSIS_CAE_DATA")
    orig_sha = hashlib.sha256(b"AUTHENTIC_EXTERNAL_CHASSIS_CAE_DATA").hexdigest()

    executor = DummyCaeExecutor()
    res = open_user_cae_working_copy(
        cae_path=source_cae,
        project_context=ctx,
        executor=executor,
        target_filename="chassis_work.cae",
    )

    assert res["status"] == "PREPARED"
    assert res["original_cae_sha256"] == orig_sha
    assert Path(res["working_cae_path"]).is_file()
    assert Path(res["working_cae_path"]).name == "chassis_work.cae"
    # Ensure source file remained intact in external dir
    assert source_cae.read_bytes() == b"AUTHENTIC_EXTERNAL_CHASSIS_CAE_DATA"
    # Ensure reference copy was archived in input_dir
    archived_in_input = ctx.input_dir / "chassis.cae"
    assert archived_in_input.is_file()
    assert archived_in_input.read_bytes() == b"AUTHENTIC_EXTERNAL_CHASSIS_CAE_DATA"


def test_solve_user_inp_fails_on_nonzero_exit_code_and_missing_odb(tmp_path):
    """P0 Contract: solve_user_inp must report FAILED when solver returns non-zero code or misses ODB."""
    ctx = _make_dummy_project(tmp_path)
    inp_file = ctx.input_dir / "bad_syntax.inp"
    inp_file.write_text("*HEADING\nBad INP syntax")

    # 1. Non-zero exit code
    class FailExecutor:
        def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
            return {"returncode": 143, "stdout": "", "stderr": "Abaqus error: syntax error on line 2"}

    res_fail = solve_user_inp(
        executor=FailExecutor(),
        inp_path=inp_file,
        project_context=ctx,
        run_id="run_inp_fail_01",
    )
    assert res_fail["status"] == "FAILED"
    assert res_fail["returncode"] == 143
    assert "non-zero exit code 143" in res_fail["error"]

    # 2. Returncode 0 but missing ODB
    class ZeroExitNoOdbExecutor:
        def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
            return {"returncode": 0, "stdout": "Check completed", "stderr": ""}

    res_no_odb = solve_user_inp(
        executor=ZeroExitNoOdbExecutor(),
        inp_path=inp_file,
        project_context=ctx,
        run_id="run_inp_no_odb",
    )
    assert res_no_odb["status"] == "FAILED"
    assert "expected ODB output was not found" in res_no_odb["error"]

    # 3. Solver exception (e.g. process launch failed or timeout)
    class TimeoutExecutor:
        def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
            raise TimeoutError("Solver execution timed out after 300s")

    res_exc = solve_user_inp(
        executor=TimeoutExecutor(),
        inp_path=inp_file,
        project_context=ctx,
        run_id="run_inp_timeout",
    )
    assert res_exc["status"] == "FAILED"
    assert "Solver invocation raised exception" in res_exc["error"]


def test_open_user_cae_collision_preserves_existing_benchmark(tmp_path):
    """P0 Contract: Importing an external CAE with the same filename but different content
    MUST NOT overwrite the existing reference baseline in input_dir.
    """
    ctx = _make_dummy_project(tmp_path)

    # 1. Pre-existing baseline in input_dir
    baseline_cae = ctx.input_dir / "part.cae"
    baseline_cae.write_bytes(b"HISTORICAL_BASELINE_V1")
    baseline_sha = hashlib.sha256(b"HISTORICAL_BASELINE_V1").hexdigest()

    # 2. External new CAE with identical name but different bytes
    ext_dir = tmp_path / "IncomingDrop"
    ext_dir.mkdir()
    new_cae = ext_dir / "part.cae"
    new_cae.write_bytes(b"NEW_INCOMING_DIFFERENT_V2")
    new_sha = hashlib.sha256(b"NEW_INCOMING_DIFFERENT_V2").hexdigest()

    executor = DummyCaeExecutor()
    res = open_user_cae_working_copy(
        cae_path=new_cae,
        project_context=ctx,
        executor=executor,
        target_filename="part_working.cae",
    )

    assert res["status"] == "PREPARED"
    # Crucial: Existing historical baseline is 100% UNTOUCHED
    assert baseline_cae.read_bytes() == b"HISTORICAL_BASELINE_V1"
    assert _compute_file_sha256(baseline_cae) == baseline_sha

    # Working copy derived from the new input content
    working_file = Path(res["working_cae_path"])
    assert working_file.is_file()
    assert working_file.read_bytes() == b"NEW_INCOMING_DIFFERENT_V2"


def test_parse_returncode_contract_matrix():
    """Verify _parse_returncode enforces strict typing and value constraints."""
    # Valid returncodes
    assert _parse_returncode(0) == 0
    assert _parse_returncode(-1) == -1
    assert _parse_returncode(127) == 127
    assert _parse_returncode("0") == 0
    assert _parse_returncode("-1") == -1
    assert _parse_returncode("127") == 127
    assert _parse_returncode("  42  ") == 42

    # Strictly rejected: bool (bool is subclass of int)
    with pytest.raises(ValueError, match="returncode must not be bool"):
        _parse_returncode(True)
    with pytest.raises(ValueError, match="returncode must not be bool"):
        _parse_returncode(False)

    # Strictly rejected: float and float strings
    with pytest.raises(ValueError, match="Invalid solver returncode"):
        _parse_returncode(0.0)
    with pytest.raises(ValueError, match="Invalid solver returncode"):
        _parse_returncode(0.5)
    with pytest.raises(ValueError, match="Invalid solver returncode"):
        _parse_returncode(1.0)
    with pytest.raises(ValueError, match="Invalid solver returncode"):
        _parse_returncode("0.5")

    # Strictly rejected: None, empty string, non-numeric strings, collections
    with pytest.raises(ValueError, match="Invalid solver returncode"):
        _parse_returncode(None)
    with pytest.raises(ValueError, match="Invalid solver returncode"):
        _parse_returncode("")
    with pytest.raises(ValueError, match="Invalid solver returncode"):
        _parse_returncode("   ")
    with pytest.raises(ValueError, match="Invalid solver returncode"):
        _parse_returncode("abc")
    with pytest.raises(ValueError, match="Invalid solver returncode"):
        _parse_returncode([0])


def test_workspace_transaction_lifecycle_and_rollback(tmp_path):
    """Verify WorkspaceTransaction tracks new files and restores overwritten files on rollback."""
    tx = WorkspaceTransaction()

    # 1. Existing file
    orig_file = tmp_path / "baseline.txt"
    orig_bytes = b"ORIGINAL_BYTES_12345"
    orig_file.write_bytes(orig_bytes)
    orig_sha = hashlib.sha256(orig_bytes).hexdigest()

    # 2. New file that does not yet exist
    new_file = tmp_path / "new_artifact.txt"

    tx.prepare_write(orig_file)
    tx.prepare_write(new_file)

    # Mutate existing file and write new file
    orig_file.write_bytes(b"MUTATED_BYTES_TEMPORARY")
    new_file.write_bytes(b"NEW_TEMPORARY_CONTENT")

    assert orig_file.read_bytes() == b"MUTATED_BYTES_TEMPORARY"
    assert new_file.is_file()

    # Trigger rollback
    tx.rollback()

    # Existing file must be 100% restored to original exact bytes and hash
    assert orig_file.is_file()
    assert orig_file.read_bytes() == orig_bytes
    assert _compute_file_sha256(orig_file) == orig_sha

    # New file must be unlinked
    assert not new_file.exists()


def test_workspace_transaction_commit_clears_state(tmp_path):
    """Verify WorkspaceTransaction commit clears backups and new files tracker."""
    tx = WorkspaceTransaction()
    target_file = tmp_path / "committed.txt"
    target_file.write_bytes(b"ORIG")

    tx.prepare_write(target_file)
    target_file.write_bytes(b"UPDATED")
    tx.commit()

    assert len(tx.backups) == 0
    assert len(tx.newly_created) == 0

    # Rollback after commit does not revert committed changes
    tx.rollback()
    assert target_file.read_bytes() == b"UPDATED"


def test_pre_solve_dependency_tamper_guard_fails_closed(tmp_path):
    """Verify _verify_solver_dependencies detects disk-level tampering or missing dependency."""
    dep_file = tmp_path / "inc.txt"
    dep_file.write_bytes(b"GENUINE_CONTENT")
    genuine_sha = hashlib.sha256(b"GENUINE_CONTENT").hexdigest()

    valid_record = [{
        "logical_path": "inc.txt",
        "source_path": str(dep_file),
        "target_path": str(dep_file),
        "target_sha256": genuine_sha,
    }]

    # Unaltered file passes verification
    _verify_solver_dependencies(valid_record)

    # 1. Disk-level tampering (modified bytes)
    dep_file.write_bytes(b"TAMPERED_CONTENT_MALICIOUS")
    with pytest.raises(RuntimeError, match="Pre-solve integrity violation: dependency file tampered"):
        _verify_solver_dependencies(valid_record)

    # 2. Missing dependency file
    dep_file.unlink()
    with pytest.raises(RuntimeError, match="Pre-solve integrity violation: dependency file missing"):
        _verify_solver_dependencies(valid_record)


def test_solve_user_inp_odb_validator_hook_positive_and_negative(tmp_path):
    """Verify solve_user_inp integrates odb_validator hook correctly."""
    ctx = _make_dummy_project(tmp_path)
    inp_file = ctx.input_dir / "valid_job.inp"
    inp_file.write_text("*HEADING\nValid Job\n")

    executor = DummyInpExecutor()

    # 1. Positive validation
    res_pos = solve_user_inp(
        executor=executor,
        inp_path=inp_file,
        project_context=ctx,
        run_id="run_val_pos",
        odb_validator=lambda odb_p: odb_p.is_file(),
    )
    assert res_pos["status"] == "COMPLETED"
    assert res_pos["odb_valid"] is True

    # 2. Negative validation (validator returns False)
    res_neg = solve_user_inp(
        executor=executor,
        inp_path=inp_file,
        project_context=ctx,
        run_id="run_val_neg",
        odb_validator=lambda odb_p: False,
    )
    assert res_neg["status"] == "FAILED"
    assert res_neg["odb_valid"] is False
    assert "failed validity verification" in res_neg["error"]

    # 3. Failing validator (validator raises exception)
    def broken_validator(odb_p):
        raise RuntimeError("Corrupt ODB header structure detected")

    res_exc = solve_user_inp(
        executor=executor,
        inp_path=inp_file,
        project_context=ctx,
        run_id="run_val_exc",
        odb_validator=broken_validator,
    )
    assert res_exc["status"] == "FAILED"
    assert res_exc["odb_valid"] is False
    assert "validity verification raised exception" in res_exc["error"]


def test_edit_and_solve_user_inp_transactional_rollback_on_missing_include(tmp_path):
    """Verify edit_and_solve_user_inp rolls back newly created working INP when include preflight fails."""
    ctx = _make_dummy_project(tmp_path)
    main_inp = ctx.input_dir / "missing_inc_model.inp"
    main_inp.write_text("*HEADING\n*INCLUDE, INPUT=non_existent_file.inc\n*STEP, NAME=Step-1\n*STATIC\n*END STEP\n")

    target_working = ctx.working_dir / "missing_inc_model_edited.inp"
    assert not target_working.exists()

    executor = DummyInpExecutor()
    with pytest.raises(FileNotFoundError, match="Missing required \\*INCLUDE dependency"):
        edit_and_solve_user_inp(
            executor=executor,
            inp_path=main_inp,
            operations=[{"category": "step", "target": "Step-1", "keyword": "*STATIC", "values": {"total_time": 2.0}}],
            project_context=ctx,
            target_filename=target_working.name,
        )

    # Target working INP must be rolled back (deleted) because dependency planning failed
    assert not target_working.exists()


def test_edit_and_solve_user_inp_transactional_rollback_preserves_overwritten_file(tmp_path):
    """Verify edit_and_solve_user_inp restores existing file on transactional failure."""
    ctx = _make_dummy_project(tmp_path)
    main_inp = ctx.input_dir / "fail_model.inp"
    main_inp.write_text("*HEADING\n*INCLUDE, INPUT=ghost.inc\n*STEP, NAME=Step-1\n*STATIC\n*END STEP\n")

    target_working = ctx.working_dir / "fail_model_edited.inp"
    target_working.write_bytes(b"PRE_EXISTING_IMPORTANT_DATA_V1")
    target_sha = hashlib.sha256(b"PRE_EXISTING_IMPORTANT_DATA_V1").hexdigest()

    executor = DummyInpExecutor()
    with pytest.raises(FileNotFoundError):
        edit_and_solve_user_inp(
            executor=executor,
            inp_path=main_inp,
            operations=[{"category": "step", "target": "Step-1", "keyword": "*STATIC", "values": {"total_time": 2.0}}],
            project_context=ctx,
            target_filename=target_working.name,
            overwrite=True,
        )

    # File was overwritten during edit, but rollback must have restored the exact original bytes!
    assert target_working.is_file()
    assert target_working.read_bytes() == b"PRE_EXISTING_IMPORTANT_DATA_V1"
    assert _compute_file_sha256(target_working) == target_sha
