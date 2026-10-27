# ===========================================================================
# Unit and Contract Tests for User Model Input Modes (Task 35.4)
# ===========================================================================
import hashlib
from pathlib import Path
import pytest

from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.execution.input_modes import (
    RollbackError,
    UserInputKind,
    WorkspaceTransaction,
    _compute_file_sha256,
    _job_from_input_file_code,
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


def test_session_fallback_uses_job_from_input_file_not_a_cli_string():
    """Session transports execute Python, so ``abaqus job=...`` can only raise
    SyntaxError there. The documented in-session equivalent is the
    ``JobFromInputFile`` job object with a bounded wait."""
    code = _job_from_input_file_code("DeckJob", Path("/tmp/deck.inp"), None, 120)
    compile(code, "<test>", "exec")
    assert "JobFromInputFile(name='DeckJob'" in code
    assert "waitForCompletion(timeOut=120)" in code
    assert "abaqus job=" not in code
    assert "waitForCompletion()" not in code


def test_session_fallback_restores_cwd_even_on_failure(tmp_path):
    code = _job_from_input_file_code("DeckJob", Path("/tmp/deck.inp"), tmp_path, 60)
    compile(code, "<test>", "exec")
    assert "finally:" in code
    assert "_ai_os.chdir(_ai_prev_cwd)" in code
    # The restore must sit inside the finally block, after the wait.
    assert code.index("waitForCompletion") < code.index("_ai_os.chdir(_ai_prev_cwd)")


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


def test_solve_user_inp_rejects_undecodable_deck_before_assembly_audit(tmp_path):
    """An undecodable deck must fail closed, not be replacement-decoded and then audited."""
    from abaqus_ai_agent.validation.assembly_guard import AssemblyContractViolation

    inp_file = tmp_path / "bad_bytes.inp"
    inp_file.write_bytes(b"*HEADING\nBad\xff\xfe\n*STEP\n*STATIC\n*END STEP\n")

    executor = DummyInpExecutor()
    with pytest.raises(AssemblyContractViolation, match="not valid UTF-8"):
        solve_user_inp(
            executor=executor,
            inp_path=inp_file,
            job_name="BadBytesJob",
            assembly_scope={"parts": []},
        )

    # The solver must never be invoked when the pre-submission audit cannot read the deck.
    assert executor.invocations == []


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


def test_edit_and_solve_rollback_on_solver_failure_contract(tmp_path):
    """P0-1 Contract: Verify rollback_on_solver_failure controls rollback vs retention on solver failure."""
    ctx = _make_dummy_project(tmp_path)
    main_inp = ctx.input_dir / "deck_solver_fail.inp"
    main_inp.write_text("*HEADING\nFail Model\n*STEP, NAME=Step-1\n*STATIC\n*END STEP\n")

    class FailSolverExecutor:
        def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
            return {"returncode": 1, "stdout": "", "stderr": "Solver crashed"}

    # Case A: rollback_on_solver_failure=True -> rolls back newly created working INP
    target_a = ctx.working_dir / "deck_fail_rolled_back.inp"
    res_a = edit_and_solve_user_inp(
        executor=FailSolverExecutor(),
        inp_path=main_inp,
        operations=[{"category": "step", "target": "Step-1", "keyword": "*STATIC", "values": {"total_time": 2.0}}],
        project_context=ctx,
        target_filename=target_a.name,
        rollback_on_solver_failure=True,
    )
    assert res_a["status"] == "FAILED"
    assert res_a["rolled_back"] is True
    assert res_a["retained_for_diagnosis"] is False
    assert not target_a.exists()

    # Case B: rollback_on_solver_failure=False (default) -> retains file for diagnostic post-mortem
    target_b = ctx.working_dir / "deck_fail_retained.inp"
    res_b = edit_and_solve_user_inp(
        executor=FailSolverExecutor(),
        inp_path=main_inp,
        operations=[{"category": "step", "target": "Step-1", "keyword": "*STATIC", "values": {"total_time": 2.0}}],
        project_context=ctx,
        target_filename=target_b.name,
        rollback_on_solver_failure=False,
    )
    assert res_b["status"] == "FAILED"
    assert res_b["rolled_back"] is False
    assert res_b["retained_for_diagnosis"] is True
    assert target_b.is_file()


def test_workspace_transaction_rollback_error_raised(tmp_path, monkeypatch):
    """P0-1 Contract: Verify WorkspaceTransaction.rollback collects and raises RollbackError when recovery fails."""
    tx = WorkspaceTransaction()
    target_file = tmp_path / "protected_target.txt"
    target_file.write_bytes(b"INITIAL_BYTES")
    tx.prepare_write(target_file)
    target_file.write_bytes(b"ALTERED_BYTES")

    def mock_write_bytes(self, data):
        raise PermissionError("Access denied during file restoration")

    monkeypatch.setattr(Path, "write_bytes", mock_write_bytes)

    with pytest.raises(RollbackError) as exc_info:
        tx.rollback()

    assert "PermissionError" in str(exc_info.value)
    assert len(tx.errors) == 1


def test_multilevel_nested_include_target_directory_hierarchy(tmp_path):
    """P0-2 Contract: Verify multi-level nested *INCLUDE dependencies preserve relative subdirectories."""
    ctx = _make_dummy_project(tmp_path)
    src_dir = ctx.input_dir

    # Multi-level structure:
    # main.inp -> sub/part.inc -> deep/section.inc (relative to sub/)
    sub_dir = src_dir / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)
    deep_dir = sub_dir / "deep"
    deep_dir.mkdir(parents=True, exist_ok=True)

    deep_inc = deep_dir / "section.inc"
    deep_inc.write_text("*MATERIAL, NAME=STEEL\n*ELASTIC\n210000., 0.3\n")

    part_inc = sub_dir / "part.inc"
    part_inc.write_text("*INCLUDE, INPUT=deep/section.inc\n*SOLID SECTION, MATERIAL=STEEL\n")

    main_inp = src_dir / "assembly.inp"
    main_inp.write_text("*HEADING\nAssembly\n*INCLUDE, INPUT=sub/part.inc\n*STEP, NAME=Step-1\n*STATIC\n*END STEP\n")

    executor = DummyInpExecutor()
    res = edit_and_solve_user_inp(
        executor=executor,
        inp_path=main_inp,
        operations=[{"category": "step", "target": "Step-1", "keyword": "*STATIC", "values": {"total_time": 3.0}}],
        project_context=ctx,
        target_filename="assembly_edited.inp",
    )

    assert res["status"] == "COMPLETED"
    exec_deps = res["execution_dependencies"]
    logical_paths = [dep["logical_path"] for dep in exec_deps]
    assert "sub/part.inc" in logical_paths
    assert "sub/deep/section.inc" in logical_paths

    # Verify both files exist under solver workspace at correct hierarchical paths
    for dep in exec_deps:
        p = Path(dep["target_path"])
        assert p.is_file()
        assert _compute_file_sha256(p) == dep["target_sha256"]


def test_solve_user_inp_stale_preexisting_odb_rejected(tmp_path):
    """P0-3 Contract: Pre-existing stale ODB with untouched timestamp MUST NOT be accepted as valid output."""
    ctx = _make_dummy_project(tmp_path)
    main_inp = ctx.input_dir / "stale_test.inp"
    main_inp.write_text("*HEADING\nStale Test\n")

    class StaleLeavingExecutor:
        """Simulates solver completing with returncode=0 but failing to produce a new ODB."""
        def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
            # Does not touch or overwrite candidate ODB
            return {"returncode": 0, "stdout": "Job finished", "stderr": ""}

    run_id = "test_run_stale_001"
    solver_dir = ctx.solver_dir / run_id
    solver_dir.mkdir(parents=True, exist_ok=True)
    stale_odb = solver_dir / "stale_test.odb"
    stale_odb.write_bytes(b"ANCIENT_PRE_EXISTING_ODB_FROM_PAST")

    res = solve_user_inp(
        executor=StaleLeavingExecutor(),
        inp_path=main_inp,
        project_context=ctx,
        run_id=run_id,
    )

    assert res["status"] == "FAILED"
    assert res["odb_path"] is None
    assert res["odb_valid"] is False
    assert "stale" in res["error"]


def test_audit_record_points_to_solver_execution_dependencies(tmp_path):
    """P0-4 Contract: audit_record.include_dependencies MUST point to solver/<run_id>/ workspace files."""
    ctx = _make_dummy_project(tmp_path)
    src_dir = ctx.input_dir

    inc_file = src_dir / "props.inc"
    inc_file.write_text("*MATERIAL, NAME=ALU\n*ELASTIC\n70000., 0.33\n")

    main_inp = src_dir / "audit_test.inp"
    main_inp.write_text("*HEADING\nAudit Test\n*INCLUDE, INPUT=props.inc\n*STEP, NAME=Step-1\n*STATIC\n*END STEP\n")

    executor = DummyInpExecutor()
    res = edit_and_solve_user_inp(
        executor=executor,
        inp_path=main_inp,
        operations=[{"category": "step", "target": "Step-1", "keyword": "*STATIC", "values": {"total_time": 1.5}}],
        project_context=ctx,
        target_filename="audit_test_edited.inp",
    )

    assert res["status"] == "COMPLETED"
    audit_record = res["audit_record"]

    # Verify audit_record.include_dependencies points to solver workspace
    solver_deps = audit_record.include_dependencies
    assert len(solver_deps) == 1
    dep = solver_deps[0]

    target_p = Path(dep["target_path"])
    assert target_p.is_file()
    assert "solver" in target_p.parts
    assert _compute_file_sha256(target_p) == dep["target_sha256"]

    # Verify edited_include_dependencies points to working workspace
    edited_deps = res["edited_include_dependencies"]
    assert len(edited_deps) == 1
    working_p = Path(edited_deps[0]["target_path"])
    assert working_p.is_file()
    assert "working" in working_p.parts


def test_solve_user_inp_require_verified_odb_contract(tmp_path):
    """P0 Contract: Verify require_verified_odb fails closed when readability validator is absent or failing."""
    ctx = _make_dummy_project(tmp_path)
    main_inp = ctx.input_dir / "odb_verify_model.inp"
    main_inp.write_text("*HEADING\nODB Verify\n")

    executor = DummyInpExecutor()

    # Case A: require_verified_odb=True without validator -> Fails closed
    res_a = solve_user_inp(
        executor=executor,
        inp_path=main_inp,
        project_context=ctx,
        require_verified_odb=True,
    )
    assert res_a["status"] == "FAILED"
    assert res_a["odb_present"] is True  # File exists on disk, but is rejected by strict validation
    assert res_a["odb_path"] is None     # Not accepted as canonical deliverable output
    assert res_a["odb_verified"] is False
    assert res_a["odb_valid"] is False
    assert "no readability validator" in res_a["error"]

    # Case B: require_verified_odb=True with passing validator -> Passes
    def mock_odb_reader(p: Path) -> bool:
        return p.name.endswith(".odb") and p.stat().st_size > 0

    res_b = solve_user_inp(
        executor=executor,
        inp_path=main_inp,
        project_context=ctx,
        odb_validator=mock_odb_reader,
        require_verified_odb=True,
    )
    assert res_b["status"] == "COMPLETED"
    assert res_b["odb_present"] is True
    assert res_b["odb_verified"] is True
    assert res_b["odb_verification_mode"] == "readability_verified"
    assert res_b["odb_valid"] is True

    # Case C: require_verified_odb=False (default) without validator -> Honest unverified_file_only flag
    res_c = solve_user_inp(
        executor=executor,
        inp_path=main_inp,
        project_context=ctx,
        require_verified_odb=False,
    )
    assert res_c["status"] == "COMPLETED"
    assert res_c["odb_present"] is True
    assert res_c["odb_verified"] is False
    assert res_c["odb_verification_mode"] == "unverified_file_only"
    assert res_c["odb_valid"] is True


def test_edit_and_solve_rollback_scope_separation_contract(tmp_path):
    """P0 Contract: Verify rollback_on_solver_failure rolls back working copy while retaining solver sandbox."""
    ctx = _make_dummy_project(tmp_path)
    main_inp = ctx.input_dir / "scope_model.inp"
    main_inp.write_text("*HEADING\nScope Model\n*STEP, NAME=Step-1\n*STATIC\n*END STEP\n")

    class FailWithLogsExecutor:
        """Simulates solver failing after emitting diagnostic log in solver sandbox."""
        def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
            if workdir:
                log_file = Path(workdir) / f"{job_name or 'job'}.log"
                log_file.write_text("Solver encountered fatal divergence in increment 4")
            return {"returncode": -1, "stdout": "", "stderr": "Divergence abort"}

    target_working = ctx.working_dir / "scope_model_edited.inp"
    res = edit_and_solve_user_inp(
        executor=FailWithLogsExecutor(),
        inp_path=main_inp,
        operations=[{"category": "step", "target": "Step-1", "keyword": "*STATIC", "values": {"total_time": 1.0}}],
        project_context=ctx,
        target_filename=target_working.name,
        rollback_on_solver_failure=True,
    )

    assert res["status"] == "FAILED"
    # Working copy mutation is cleaned up and rolled back
    assert res["working_copy_rolled_back"] is True
    assert not target_working.exists()

    # Solver workspace containing diagnostic log is retained for analysis
    assert res["solver_workspace_retained"] is True
    solver_dir = Path(res["workdir"])
    assert solver_dir.is_dir()
    diagnostic_log = solver_dir / f"{res['job_name']}.log"
    assert diagnostic_log.is_file()
    assert "fatal divergence" in diagnostic_log.read_text()


def test_batch_result_multi_interface_contract():
    """Verify BatchResult polymorphism: supports both attributes and dict-like indexing."""
    from abaqus_ai_agent.execution.batch import BatchResult
    res = BatchResult(command=("abaqus", "job=test"), return_code=0, stdout="ok", stderr="")

    # Attribute access
    assert res.return_code == 0
    assert res.returncode == 0
    assert res.succeeded is True

    # Dict-like access
    assert res["returncode"] == 0
    assert res["return_code"] == 0
    assert res["stdout"] == "ok"
    assert res.get("returncode") == 0
    assert res.get("return_code") == 0
    assert res.get("non_existent", "default") == "default"


def test_figure_selector_default_animation_and_keypoint_hotspot(tmp_path):
    """Verify FigureSelector defaults to include_animation=True and creates keypoint detail on hotspot."""
    from abaqus_ai_agent.reporting.figure_selector import FigureSelector

    selector = FigureSelector()
    # 1. Default should maintain backward-compatibility (static PNGs only)
    default_res = selector.select_figures(domain="structural", run_id="run_default")
    default_types = [spec.visualization_type for spec in default_res.specs]
    assert "deformation_animation" not in default_types
    assert "keypoint_hotspot_detail" not in default_types

    # 2. When enabled with hotspot info, animation and keypoint hotspot detail are generated
    res = selector.select_figures(
        domain="structural",
        run_id="run_test_fig",
        include_animation=True,
        include_keypoint_detail=True,
        hotspot_info={
            "element_id": 42,
            "node_id": 108,
            "hotspot_location": (10.0, 20.0, 30.0),
        },
    )

    types = [spec.visualization_type for spec in res.specs]
    assert "deformation_animation" in types
    assert "keypoint_hotspot_detail" in types

    # Check keypoint detail spec binding
    kp_spec = next(s for s in res.specs if s.visualization_type == "keypoint_hotspot_detail")
    assert kp_spec.element_id == 42
    assert kp_spec.node_id == 108
    assert kp_spec.hotspot_location == (10.0, 20.0, 30.0)


def test_solve_user_inp_generate_report_pipeline_integration(tmp_path):
    """Verify solve_user_inp(generate_report=True) automatically orchestrates deliverable report assembly."""
    ctx = _make_dummy_project(tmp_path)
    main_inp = ctx.input_dir / "report_model.inp"
    main_inp.write_text("*HEADING\nReport Model\n*STEP, NAME=Step-1\n*STATIC\n*END STEP\n")

    class ReportingMockExecutor:
        def run_input(self, input_path, job_name=None, timeout=None, workdir=None):
            target_dir = Path(workdir) if workdir else Path(input_path).parent
            name = job_name or Path(input_path).stem
            odb_file = target_dir / f"{name}.odb"
            odb_file.write_bytes(b"DUMMY_ODB_VALID_CONTENT")
            return {"returncode": 0, "stdout": "Job completed", "stderr": ""}

    res = solve_user_inp(
        executor=ReportingMockExecutor(),
        inp_path=main_inp,
        project_context=ctx,
        job_name="ReportJob",
        generate_report=True,
        report_title="悬臂梁工程测试交付报告",
    )

    assert res["status"] == "COMPLETED"
    assert "report_path" in res or "report_generation_error" in res
