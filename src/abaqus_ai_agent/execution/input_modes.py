# ===========================================================================
# User-Supplied Model Input Modes & Lightweight Postprocessing Contracts
# (Phase P1.4 - Task 35.4 Governance)
# ===========================================================================
from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from ..paths import ExternalProjectContext


class UserInputKind(str, Enum):
    """Categorization of user-supplied model inputs."""
    INP_SOLVER_DIRECT = "inp_solver_direct"      # User provides .inp: direct solve without Python modeling
    ODB_READONLY = "odb_readonly"                # User provides .odb: purely read-only postprocessing, no solve
    CAE_WORKING_COPY = "cae_working_copy"        # User provides .cae: openMdb on working copy, original read-only


def _parse_returncode(value: object) -> int:
    """Strictly parse solver returncode according to exact type and value contracts.

    Contract:
    1. bool is a subclass of int in Python, MUST be rejected explicitly.
    2. Exact int is accepted.
    3. Exact integer strings (e.g. "0", "-1", "127") are accepted.
    4. Floats (e.g. 0.0, 0.5, 1.0) and float strings ("0.5") are strictly rejected.
    5. None, empty string, or non-numeric types are rejected.
    """
    if isinstance(value, bool):
        raise ValueError("returncode must not be bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text and (
            text.isdigit()
            or (text.startswith("-") and text[1:].isdigit())
        ):
            return int(text)
    raise ValueError(f"Invalid solver returncode: {value!r}")


@dataclass(frozen=True)
class IncludeDependencyPlan:
    """Immutable plan for an external *INCLUDE dependency file."""
    logical_path: str
    source_path: str
    target_path: str
    source_sha256: str


class RollbackError(RuntimeError):
    """Raised when one or more file restoration or cleanup steps fail during rollback."""


class WorkspaceTransaction:
    """Transactional staging, backup, and rollback manager for workspace files.

    Strict Guarantees:
    1. Newly created files are tracked and unlinked on rollback.
    2. Overwritten existing files are backed up and 100% restored to exact bytes on rollback.
    3. Untouched files remain untouched.
    4. Rollback errors are recorded and raised rather than silently suppressed.
    """
    def __init__(self):
        self.newly_created: List[Path] = []
        self.backups: Dict[Path, bytes] = {}
        self.errors: List[Exception] = []

    def prepare_write(self, target_path: Union[str, Path]) -> None:
        p = Path(target_path).resolve()
        if p.exists():
            if p not in self.backups:
                self.backups[p] = p.read_bytes()
        else:
            if p not in self.newly_created:
                self.newly_created.append(p)

    def rollback(self) -> None:
        self.errors.clear()
        for p in self.newly_created:
            try:
                if p.is_file():
                    p.unlink(missing_ok=True)
            except Exception as exc:
                self.errors.append(exc)
        for p, orig_bytes in self.backups.items():
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(orig_bytes)
            except Exception as exc:
                self.errors.append(exc)
        if self.errors:
            err_msg = "; ".join(f"{type(e).__name__}: {e}" for e in self.errors)
            raise RollbackError(
                f"WorkspaceTransaction rollback encountered {len(self.errors)} error(s): {err_msg}"
            )

    def commit(self) -> None:
        self.backups.clear()
        self.newly_created.clear()
        self.errors.clear()


def _compute_file_sha256(path: Union[str, Path]) -> str:
    """Compute standard SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _plan_include_dependencies(
    includes: Sequence[Dict[str, Any]],
    target_dir: Path,
    source_root_inp: Optional[Path] = None,
) -> Tuple[List[IncludeDependencyPlan], List[Dict[str, Any]]]:
    """Pure planning phase for *INCLUDE dependencies without filesystem mutation.

    Rules:
    1. Rejects path escape (relative targets must strictly reside within target_dir).
    2. Rejects collisions (different source files mapping to identical target path).
    3. Nested include mapping: maps each dependency relative to its referring deck's target directory.
    4. Returns planned dependency records and list of missing includes.
    """
    plans: List[IncludeDependencyPlan] = []
    missing: List[Dict[str, Any]] = []
    seen_targets: Dict[Path, str] = {}
    resolved_target_dir = target_dir.resolve()

    deck_target_map: Dict[str, Path] = {}
    root_parent: Optional[Path] = None
    if source_root_inp is not None:
        resolved_root_src = str(Path(source_root_inp).resolve())
        root_parent = Path(source_root_inp).parent.resolve()
        deck_target_map[resolved_root_src] = (target_dir / Path(source_root_inp).name).resolve()

    for inc in includes:
        raw_input = inc.get("input", "")
        if not raw_input:
            continue
        raw_p = Path(raw_input)
        if raw_p.is_absolute():
            # Absolute paths reside outside project workspace, not copied
            continue

        source_deck = inc.get("source_deck")
        parent_target_dir = resolved_target_dir
        if source_deck and source_deck in deck_target_map:
            parent_target_dir = deck_target_map[source_deck].parent
        elif source_deck and root_parent is not None:
            src_deck_path = Path(source_deck).resolve()
            if src_deck_path.is_relative_to(root_parent):
                rel_deck_parent = src_deck_path.relative_to(root_parent).parent
                parent_target_dir = (resolved_target_dir / rel_deck_parent).resolve()
                deck_target_map[source_deck] = (resolved_target_dir / src_deck_path.relative_to(root_parent)).resolve()

        dest_inc = (parent_target_dir / raw_input).resolve()
        if not dest_inc.is_relative_to(resolved_target_dir):
            raise ValueError(
                f"Path escape violation in *INCLUDE: '{raw_input}' escapes target directory '{resolved_target_dir}'."
            )

        if not inc.get("exists") or not inc.get("resolved_path"):
            missing.append(inc)
            continue

        src_inc = Path(inc["resolved_path"]).resolve()
        if not src_inc.is_file():
            missing.append(inc)
            continue

        src_sha256 = inc.get("sha256") or _compute_file_sha256(src_inc)
        resolved_src_str = str(src_inc)
        deck_target_map[resolved_src_str] = dest_inc

        rel_logical = str(dest_inc.relative_to(resolved_target_dir)).replace("\\", "/")

        if dest_inc in seen_targets:
            existing_sha = seen_targets[dest_inc]
            if existing_sha != src_sha256:
                raise ValueError(
                    f"Include collision conflict: multiple dependencies map to '{dest_inc}' "
                    f"with divergent SHA-256 digests."
                )
        else:
            if dest_inc.exists():
                existing_disk_sha = _compute_file_sha256(dest_inc)
                if existing_disk_sha != src_sha256:
                    raise ValueError(
                        f"Include collision conflict: file at '{dest_inc}' already exists "
                        f"with divergent SHA-256 digest."
                    )
            seen_targets[dest_inc] = src_sha256
            plans.append(IncludeDependencyPlan(
                logical_path=rel_logical,
                source_path=str(src_inc),
                target_path=str(dest_inc),
                source_sha256=src_sha256,
            ))

    return plans, missing


def _execute_include_sync(
    plans: Sequence[IncludeDependencyPlan],
    tx: Optional[WorkspaceTransaction] = None,
) -> List[Dict[str, Any]]:
    """Execute dependency copying and perform disk-level cryptographic verification."""
    synced_records: List[Dict[str, Any]] = []
    for plan in plans:
        dest_inc = Path(plan.target_path)
        src_inc = Path(plan.source_path)

        if tx is not None:
            tx.prepare_write(dest_inc)

        if not dest_inc.exists() or _compute_file_sha256(dest_inc) != plan.source_sha256:
            dest_inc.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_inc, dest_inc)

        actual_disk_sha = _compute_file_sha256(dest_inc)
        if actual_disk_sha != plan.source_sha256:
            raise RuntimeError(
                f"Integrity violation copying *INCLUDE '{plan.logical_path}' to '{dest_inc}': SHA-256 mismatch."
            )

        synced_records.append({
            "logical_path": plan.logical_path,
            "source_path": plan.source_path,
            "target_path": plan.target_path,
            "source_sha256": plan.source_sha256,
            "target_sha256": actual_disk_sha,
            "sha256": actual_disk_sha,
        })
    return synced_records


def _sync_include_dependencies(
    includes: Sequence[Dict[str, Any]],
    target_dir: Path,
    source_root_inp: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Synchronize and cryptographically verify *INCLUDE dependencies into target workspace.

    Backwards-compatible convenience wrapper combining planning and execution.
    """
    plans, missing = _plan_include_dependencies(includes, target_dir, source_root_inp=source_root_inp)
    return _execute_include_sync(plans)


def _verify_solver_dependencies(dependencies: Sequence[Dict[str, Any]]) -> None:
    """Pre-solve guard: verify all planned dependencies remain untampered on disk prior to solver launch."""
    for dep in dependencies:
        target_path = Path(dep["target_path"])
        if not target_path.is_file():
            raise RuntimeError(
                f"Pre-solve integrity violation: dependency file missing: {target_path}"
            )
        current_sha = _compute_file_sha256(target_path)
        expected_sha = dep.get("target_sha256") or dep.get("source_sha256")
        if current_sha != expected_sha:
            raise RuntimeError(
                f"Pre-solve integrity violation: dependency file tampered on disk: {target_path}"
            )


def solve_user_inp(
    executor: Any,
    inp_path: Union[str, Path],
    *,
    job_name: Optional[str] = None,
    project_context: Optional[ExternalProjectContext] = None,
    timeout: Optional[int] = None,
    run_id: Optional[str] = None,
    odb_validator: Optional[Callable[[Path], bool]] = None,
    require_verified_odb: bool = False,
) -> Dict[str, Any]:
    """Execute direct solver computation on a user-provided .inp input deck.

    Contract Rules (Task 35.4):
    1. Zero Python CAE Modeling: Directly calls solver batch interface without generating
       or executing geometry/mesh/boundary Python modeling scripts.
    2. Input Deck Preservation: Verifies the original .inp exists and remains strictly intact.
    3. Isolated Workdir: If project_context is provided, the solver runs in an isolated
       solver/<run_id>/ workspace, avoiding core repository contamination.
    4. Strict Returncode and Output Validation: Rejects invalid or missing returncodes, corrupt ODBs,
       or unverified outputs.
    5. ODB Readability Verification Modes:
       - When require_verified_odb=True, the ODB MUST be verified by a concrete readability validator
         (active_validator); otherwise execution fails closed.
       - When require_verified_odb=False, an unverified non-empty file is flagged honestly as
         odb_verification_mode="unverified_file_only" and odb_verified=False.
    """
    inp_file = Path(inp_path).resolve()
    if not inp_file.is_file():
        raise FileNotFoundError(f"User INP file does not exist: {inp_file}")

    initial_sha256 = _compute_file_sha256(inp_file)
    eff_run_id = run_id or f"run_inp_{uuid.uuid4().hex[:8]}"
    eff_job_name = job_name or inp_file.stem

    effective_workdir: Optional[Path] = None
    if project_context is not None:
        effective_workdir = project_context.create_run_solver_dir(eff_run_id)

    synced_dependencies: List[Dict[str, Any]] = []
    # Preflight inspection of *INCLUDE dependencies and workspace synchronization
    if effective_workdir:
        from ..editing.inp_editor import ControlledInpEditor
        inp_editor = ControlledInpEditor(inp_file)
        includes = inp_editor.inspect_includes(
            base_dir=inp_file.parent,
            search_dirs=[inp_file.parent],
            recursive=True,
        )
        plans, missing = _plan_include_dependencies(
            includes,
            target_dir=effective_workdir,
            source_root_inp=inp_file,
        )
        if missing:
            err_detail = "; ".join(
                f"Line {inc['line_number']}: '{inc['input']}'" for inc in missing
            )
            raise FileNotFoundError(
                f"Missing required *INCLUDE dependency file(s) for '{inp_file.name}': {err_detail}"
            )
        synced_dependencies = _execute_include_sync(plans)
        _verify_solver_dependencies(synced_dependencies)

    # Track pre-existing candidate ODB to prevent stale artifact masquerading
    candidate_odb = (effective_workdir if effective_workdir else inp_file.parent) / f"{eff_job_name}.odb"
    pre_existing_odb = candidate_odb.is_file()
    pre_mtime = candidate_odb.stat().st_mtime if pre_existing_odb else None
    if pre_existing_odb:
        try:
            candidate_odb.unlink(missing_ok=True)
        except OSError:
            pass

    # Invoke solver directly via executor
    orig_workdir = getattr(executor, "workdir", None)
    res = None
    exec_exc: Optional[Exception] = None
    try:
        if effective_workdir and hasattr(executor, "workdir"):
            executor.workdir = str(effective_workdir)

        if hasattr(executor, "run_input"):
            import inspect
            sig = inspect.signature(executor.run_input)
            kwargs = {}
            if "workdir" in sig.parameters and effective_workdir:
                kwargs["workdir"] = str(effective_workdir)
            res = executor.run_input(
                input_path=str(inp_file),
                job_name=eff_job_name,
                timeout=timeout,
                **kwargs,
            )
        elif hasattr(executor, "execute"):
            cmd = f"abaqus job={eff_job_name} input={inp_file}"
            res = executor.execute(cmd)
        else:
            raise TypeError(f"Executor {type(executor)} does not support run_input or execute interface.")
    except Exception as exc:
        exec_exc = exc
    finally:
        if hasattr(executor, "workdir"):
            executor.workdir = orig_workdir

    # Integrity verification: original .inp MUST NOT be mutated
    after_sha256 = _compute_file_sha256(inp_file)
    if initial_sha256 != after_sha256:
        raise RuntimeError(f"Integrity violation: source INP '{inp_file}' was modified during execution.")

    expected_odb: Optional[Path] = candidate_odb if candidate_odb.is_file() else None

    # Evaluate true execution status (P0 contract: never report COMPLETED unconditionally)
    status = "COMPLETED"
    error_msg: Optional[str] = None
    returncode = 0
    odb_verified: bool = False
    odb_verification_mode: str = "none"

    if exec_exc is not None:
        status = "FAILED"
        error_msg = f"Solver invocation raised exception: {exec_exc}"
        returncode = -1
    else:
        rc_raw = None
        stderr = ""
        if isinstance(res, dict):
            rc_raw = res.get("returncode")
            stderr = str(res.get("stderr", ""))
        elif hasattr(res, "returncode"):
            rc_raw = getattr(res, "returncode")
            stderr = str(getattr(res, "stderr", ""))

        if rc_raw is None:
            status = "FAILED"
            error_msg = "Execution result is incomplete: missing required 'returncode' field."
            returncode = -1
        else:
            try:
                returncode = _parse_returncode(rc_raw)
            except ValueError as val_err:
                status = "FAILED"
                error_msg = f"Execution result contains invalid non-integer returncode: {val_err}"
                returncode = -1
            else:
                if returncode != 0:
                    status = "FAILED"
                    error_msg = f"Solver exited with non-zero exit code {returncode}. Stderr: {stderr}"
                    expected_odb = None
                elif not candidate_odb.is_file():
                    status = "FAILED"
                    error_msg = f"Solver completed with code 0 but expected ODB output was not found: {eff_job_name}.odb"
                    expected_odb = None
                elif candidate_odb.stat().st_size == 0:
                    status = "FAILED"
                    error_msg = f"Solver completed with code 0 but generated empty/corrupt ODB: {eff_job_name}.odb (0 bytes)"
                    expected_odb = None
                elif pre_existing_odb and pre_mtime is not None and candidate_odb.stat().st_mtime <= pre_mtime:
                    status = "FAILED"
                    error_msg = (
                        f"Solver completed but candidate ODB is stale (pre-existed prior to run and was not updated by solver): "
                        f"{eff_job_name}.odb"
                    )
                    expected_odb = None
                else:
                    expected_odb = candidate_odb
                    active_validator = odb_validator
                    if active_validator is None and hasattr(executor, "validate_odb"):
                        active_validator = getattr(executor, "validate_odb")
                    if active_validator is not None:
                        try:
                            is_valid = bool(active_validator(expected_odb))
                        except Exception as val_exc:
                            status = "FAILED"
                            error_msg = f"Solver output ODB validity verification raised exception: {val_exc}"
                            expected_odb = None
                        else:
                            if not is_valid:
                                status = "FAILED"
                                error_msg = f"Solver output ODB failed validity verification: {eff_job_name}.odb"
                                expected_odb = None
                            else:
                                odb_verified = True
                                odb_verification_mode = "readability_verified"
                    else:
                        if require_verified_odb:
                            status = "FAILED"
                            error_msg = (
                                f"Strict ODB verification required, but no readability validator "
                                f"was configured for {eff_job_name}.odb"
                            )
                            expected_odb = None
                        else:
                            odb_verified = False
                            odb_verification_mode = "unverified_file_only"

    odb_present = bool(
        expected_odb is not None
        and expected_odb.is_file()
        and expected_odb.stat().st_size > 0
    )
    odb_valid = (
        status == "COMPLETED"
        and odb_present
        and (odb_verified or not require_verified_odb)
    )

    return {
        "status": status,
        "error": error_msg,
        "returncode": returncode,
        "odb_present": odb_present,
        "odb_verified": odb_verified,
        "odb_verification_mode": odb_verification_mode,
        "require_verified_odb": require_verified_odb,
        "odb_valid": odb_valid,
        "input_kind": UserInputKind.INP_SOLVER_DIRECT.value,
        "run_id": eff_run_id,
        "job_name": eff_job_name,
        "inp_path": str(inp_file),
        "inp_sha256": initial_sha256,
        "workdir": str(effective_workdir) if effective_workdir else None,
        "odb_path": str(expected_odb) if expected_odb else None,
        "execution_result": res,
        "include_dependencies": synced_dependencies,
        "execution_dependencies": synced_dependencies,
    }


def postprocess_user_odb(
    odb_path: Union[str, Path],
    *,
    project_context: Optional[ExternalProjectContext] = None,
    requirements: Sequence[Any] = (),
    run_id: Optional[str] = None,
    custom_runner: Optional[Callable[[str], Any]] = None,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    """Execute strictly read-only postprocessing and metric extraction on a user-supplied .odb.

    Contract Rules (Task 35.4):
    1. Read-Only Mode: Strictly forbids launching solver or submitting re-computations.
    2. Zero In-Place Mutation: The source ODB remains unmodified.
    3. Structured Extraction: Extracts fields, hotspots, and curves into isolated evidence workspace.
    """
    odb_file = Path(odb_path).resolve()
    if not odb_file.is_file():
        raise FileNotFoundError(f"User ODB file does not exist: {odb_file}")

    odb_sha256 = _compute_file_sha256(odb_file)
    eff_run_id = run_id or f"run_post_{uuid.uuid4().hex[:8]}"

    evidence_dir: Optional[Path] = None
    if project_context is not None:
        evidence_dir = project_context.create_run_evidence_dir(eff_run_id)

    extraction_report = None
    if requirements:
        from .odb_extractor import extract_odb_results
        extraction_report = extract_odb_results(
            odb_path=odb_file,
            requirements_or_criteria=requirements,
            run_id=eff_run_id,
            input_hash=odb_sha256,
            workdir=evidence_dir,
            custom_runner=custom_runner,
            timeout_seconds=timeout_seconds,
        )

    # Verify ODB was not modified
    after_sha256 = _compute_file_sha256(odb_file)
    if odb_sha256 != after_sha256:
        raise RuntimeError(f"Read-only contract violation: source ODB '{odb_file}' was mutated during postprocessing.")

    return {
        "status": "COMPLETED",
        "input_kind": UserInputKind.ODB_READONLY.value,
        "run_id": eff_run_id,
        "odb_path": str(odb_file),
        "odb_sha256": odb_sha256,
        "evidence_dir": str(evidence_dir) if evidence_dir else None,
        "extraction_report": extraction_report,
    }


def open_user_cae_working_copy(
    cae_path: Union[str, Path],
    *,
    project_context: Optional[ExternalProjectContext] = None,
    executor: Optional[Any] = None,
    target_filename: Optional[str] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Prepare and open an authentic Abaqus CAE database using an isolated working copy.

    Contract Rules (Task 35.4):
    1. Original CAE Protection: Original user file is strictly read-only and never modified.
    2. Working Copy Isolation: Duplicates into project_context.working_dir before opening.
    3. openMdb Script Generation: Emits or executes `openMdb(pathName=...)` pointing to working copy.
    """
    src_file = Path(cae_path).resolve()
    if not src_file.is_file():
        raise FileNotFoundError(f"User CAE file does not exist: {src_file}")

    orig_sha256 = _compute_file_sha256(src_file)

    working_cae: Path
    if project_context is not None:
        try:
            src_file.relative_to(project_context.input_dir.resolve())
            is_inside_input = True
        except ValueError:
            is_inside_input = False

        if not is_inside_input:
            safe_input_copy = project_context.input_dir / src_file.name
            if safe_input_copy.exists():
                existing_sha = _compute_file_sha256(safe_input_copy)
                if existing_sha != orig_sha256:
                    if not overwrite:
                        # Collision protection: Never silently overwrite an existing reference benchmark
                        safe_input_copy = project_context.input_dir / f"{src_file.stem}_{orig_sha256[:8]}{src_file.suffix}"
                    if not safe_input_copy.exists() or _compute_file_sha256(safe_input_copy) != orig_sha256:
                        shutil.copy2(src_file, safe_input_copy)
            else:
                shutil.copy2(src_file, safe_input_copy)
            source_fname = safe_input_copy.name
        else:
            source_fname = src_file.name

        working_cae = project_context.prepare_working_copy(
            source_filename=source_fname,
            target_filename=target_filename,
            overwrite=overwrite,
        )
    else:
        # If no project context, work directly on an explicit working copy adjacent to source
        dest_name = target_filename or f"working_{src_file.name}"
        working_cae = src_file.parent / dest_name
        if working_cae.exists() and not overwrite:
            raise FileExistsError(f"Working copy '{working_cae}' already exists.")
        shutil.copy2(src_file, working_cae)

    # Verify original file integrity
    post_sha256 = _compute_file_sha256(src_file)
    if orig_sha256 != post_sha256:
        raise RuntimeError(f"Integrity violation: original CAE '{src_file}' was modified.")

    # Generate headless script to open working database
    working_posix = working_cae.as_posix()
    open_script = (
        "from abaqus import *\n"
        "from abaqusConstants import *\n"
        f"openMdb(pathName=r'{working_posix}')\n"
        "print('[UserCae] Successfully opened working database: ' + r'" + working_posix + "')\n"
    )

    model_info = None
    if executor is not None and hasattr(executor, "execute"):
        executor.execute(open_script)
        from .inspection import get_model_info
        model_info = get_model_info(executor)

    return {
        "status": "PREPARED",
        "input_kind": UserInputKind.CAE_WORKING_COPY.value,
        "original_cae_path": str(src_file),
        "original_cae_sha256": orig_sha256,
        "working_cae_path": str(working_cae),
        "open_script": open_script,
        "model_info": model_info,
    }


def edit_and_solve_user_inp(
    executor: Any,
    inp_path: Union[str, Path],
    operations: Sequence[Any],
    *,
    target_filename: Optional[str] = None,
    job_name: Optional[str] = None,
    project_context: Optional[ExternalProjectContext] = None,
    timeout: Optional[int] = None,
    run_id: Optional[str] = None,
    overwrite: bool = False,
    odb_validator: Optional[Callable[[Path], bool]] = None,
    rollback_on_solver_failure: bool = False,
    require_verified_odb: bool = False,
) -> Dict[str, Any]:
    """Surgically edit a user-provided .inp file in an isolated working copy and execute it.

    Transactional Contract:
    1. Preflight Planning: Verifies syntax, targets, include dependencies and containment without mutating targets.
    2. Atomic Staging with Full Rollback: Tracks new files and backs up overwritten files.
       Any failure before successful execution rolls back all state, restoring original files.
    3. Cryptographic Provenance: Records pre/post SHA-256 for main INP and all dependencies.
    4. Isolated Execution: Runs directly in solver/<run_id>/ workspace.
    5. Rollback Scope vs Diagnostic Sandbox:
       - Working Copy Rollback: When rollback_on_solver_failure=True, only staged working-copy mutations
         (working/ modified INP and staged dependencies) are rolled back to keep the user's working copy clean.
       - Solver Workspace Diagnostics: The solver execution sandbox (solver/<run_id>/) containing raw solver logs
         (.sta, .msg, .log, core dumps) is intentionally retained for post-mortem diagnostics.
    """
    from ..editing.inp_editor import ControlledInpEditor, InpEditOperation, edit_inp_file, InpEditAuditRecord

    src_file = Path(inp_path).resolve()
    if not src_file.is_file():
        raise FileNotFoundError(f"User INP file does not exist: {src_file}")

    allowed_dir: Path
    if project_context is not None:
        target_name = target_filename or f"{src_file.stem}_edited.inp"
        dest_inp = (project_context.working_dir / target_name).resolve()
        allowed_dir = project_context.working_dir.resolve()
        if not dest_inp.is_relative_to(allowed_dir):
            raise ValueError(
                f"Path escape violation: target path '{dest_inp}' escapes working_dir '{allowed_dir}'."
            )
    else:
        target_name = target_filename or f"{src_file.stem}_edited_{uuid.uuid4().hex[:6]}.inp"
        dest_inp = (src_file.parent / target_name).resolve()
        allowed_dir = src_file.parent.resolve()
        if not dest_inp.is_relative_to(allowed_dir):
            raise ValueError(
                f"Path escape violation: target path '{dest_inp}' escapes parent directory '{allowed_dir}'."
            )
        if dest_inp == src_file:
            raise PermissionError("Zero In-Place Mutation violation: target_path cannot be identical to source_path.")

    if dest_inp.exists() and not overwrite:
        raise FileExistsError(
            f"Target INP '{dest_inp}' already exists. Pass overwrite=True to permit overwrite."
        )

    inp_ops = []
    for op in operations:
        if isinstance(op, InpEditOperation):
            inp_ops.append(op)
        elif isinstance(op, dict):
            inp_ops.append(
                InpEditOperation(
                    category=op.get("category", ""),
                    target_identifier=op.get("target_identifier", op.get("target", "")),
                    property_keyword=op.get("property_keyword", op.get("keyword", "")),
                    new_values=op.get("new_values", op.get("values")),
                    metadata=op.get("metadata", {}),
                )
            )
        else:
            raise TypeError(f"Unsupported edit operation type: {type(op)}")

    tx = WorkspaceTransaction()
    synced_dependencies: List[Dict[str, Any]] = []
    audit_record: InpEditAuditRecord

    try:
        tx.prepare_write(dest_inp)
        audit_record = edit_inp_file(
            source_path=src_file,
            target_path=dest_inp,
            operations=inp_ops,
            overwrite=overwrite,
            allowed_directory=allowed_dir,
        )

        search_dirs = [dest_inp.parent]
        if src_file.parent.resolve() != dest_inp.parent.resolve():
            search_dirs.append(src_file.parent.resolve())

        editor_checker = ControlledInpEditor(dest_inp)
        all_includes = editor_checker.inspect_includes(
            base_dir=dest_inp.parent,
            search_dirs=search_dirs,
            recursive=True,
        )

        plans, missing_includes = _plan_include_dependencies(
            all_includes,
            target_dir=dest_inp.parent,
            source_root_inp=dest_inp,
        )
        if missing_includes:
            err_detail = "; ".join(
                f"Line {inc['line_number']}: '{inc['input']}'"
                for inc in missing_includes
            )
            raise FileNotFoundError(
                f"Missing required *INCLUDE dependency file(s) for '{dest_inp.name}': {err_detail}"
            )

        synced_dependencies = _execute_include_sync(plans, tx=tx)
        _verify_solver_dependencies(synced_dependencies)

        # Execute solver under transaction scope
        solve_res = solve_user_inp(
            executor=executor,
            inp_path=dest_inp,
            job_name=job_name or dest_inp.stem,
            project_context=project_context,
            timeout=timeout,
            run_id=run_id,
            odb_validator=odb_validator,
            require_verified_odb=require_verified_odb,
        )

        # Reconcile actual solver workspace dependencies vs editing copy
        execution_deps = solve_res.get("execution_dependencies") or synced_dependencies

        audit_record = InpEditAuditRecord(
            source_path=audit_record.source_path,
            target_path=audit_record.target_path,
            source_sha256=audit_record.source_sha256,
            target_sha256=audit_record.target_sha256,
            operations_applied=audit_record.operations_applied,
            diff_summary=audit_record.diff_summary,
            lines_changed=audit_record.lines_changed,
            include_dependencies=tuple(execution_deps),
        )

        if solve_res["status"] != "COMPLETED" and rollback_on_solver_failure:
            tx.rollback()
            solve_res["rolled_back"] = True
            solve_res["retained_for_diagnosis"] = False
        else:
            tx.commit()
            solve_res["rolled_back"] = False
            solve_res["retained_for_diagnosis"] = (solve_res["status"] != "COMPLETED")

    except Exception:
        tx.rollback()
        raise

    solve_res["working_copy_rolled_back"] = solve_res["rolled_back"]
    solve_res["solver_workspace_retained"] = bool(solve_res.get("workdir") is not None)
    solve_res["audit_record"] = audit_record
    solve_res["source_inp_path"] = str(src_file)
    solve_res["source_inp_sha256"] = audit_record.source_sha256
    solve_res["edited_inp_path"] = str(dest_inp)
    solve_res["edited_inp_sha256"] = audit_record.target_sha256
    solve_res["diff_summary"] = audit_record.diff_summary
    solve_res["lines_changed"] = audit_record.lines_changed
    solve_res["include_dependencies"] = list(execution_deps)
    solve_res["execution_dependencies"] = list(execution_deps)
    solve_res["edited_include_dependencies"] = list(synced_dependencies)
    solve_res["is_edited"] = True
    return solve_res
