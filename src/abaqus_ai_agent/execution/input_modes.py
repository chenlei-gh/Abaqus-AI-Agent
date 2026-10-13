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


def _compute_file_sha256(path: Union[str, Path]) -> str:
    """Compute standard SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def solve_user_inp(
    executor: Any,
    inp_path: Union[str, Path],
    *,
    job_name: Optional[str] = None,
    project_context: Optional[ExternalProjectContext] = None,
    timeout: Optional[int] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute direct solver computation on a user-provided .inp input deck.

    Contract Rules (Task 35.4):
    1. Zero Python CAE Modeling: Directly calls solver batch interface without generating
       or executing geometry/mesh/boundary Python modeling scripts.
    2. Input Deck Preservation: Verifies the original .inp exists and remains strictly intact.
    3. Isolated Workdir: If project_context is provided, the solver runs in an isolated
       solver/<run_id>/ workspace, avoiding core repository contamination.
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
            # Generic executor fallback
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

    expected_odb: Optional[Path] = None
    if effective_workdir:
        # P0 Contract: When running in an isolated workdir, the output ODB MUST be
        # produced directly within effective_workdir. Never latch onto stale sibling ODBs!
        candidate_odb = effective_workdir / f"{eff_job_name}.odb"
        if candidate_odb.is_file() and candidate_odb.stat().st_size > 0:
            expected_odb = candidate_odb
    else:
        # Fallback only when executing without an external project context
        candidate_odb = inp_file.parent / f"{eff_job_name}.odb"
        if candidate_odb.is_file() and candidate_odb.stat().st_size > 0:
            expected_odb = candidate_odb

    # Evaluate true execution status (P0 contract: never report COMPLETED unconditionally)
    status = "COMPLETED"
    error_msg: Optional[str] = None
    returncode = 0

    if exec_exc is not None:
        status = "FAILED"
        error_msg = f"Solver invocation raised exception: {exec_exc}"
        returncode = -1
    else:
        if isinstance(res, dict):
            returncode = int(res.get("returncode", 0))
            stderr = str(res.get("stderr", ""))
        elif hasattr(res, "returncode"):
            returncode = int(getattr(res, "returncode", 0))
            stderr = str(getattr(res, "stderr", ""))
        else:
            returncode = 0
            stderr = ""

        if returncode != 0:
            status = "FAILED"
            error_msg = f"Solver exited with non-zero exit code {returncode}. Stderr: {stderr}"
        elif expected_odb is None or not expected_odb.is_file():
            status = "FAILED"
            error_msg = f"Solver completed with code 0 but expected ODB output was not found: {eff_job_name}.odb"

    return {
        "status": status,
        "error": error_msg,
        "returncode": returncode,
        "input_kind": UserInputKind.INP_SOLVER_DIRECT.value,
        "run_id": eff_run_id,
        "job_name": eff_job_name,
        "inp_path": str(inp_file),
        "inp_sha256": initial_sha256,
        "workdir": str(effective_workdir) if effective_workdir else None,
        "odb_path": str(expected_odb) if expected_odb else None,
        "execution_result": res,
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
) -> Dict[str, Any]:
    """Surgically edit a user-provided .inp file in an isolated working copy and execute it.

    Contract Rules (Phase P1.4 / P1.5):
    1. Zero In-Place Mutation: The original input deck is strictly read-only and never modified.
    2. Working Copy Isolation: Surgical edits are applied solely to a new working file.
    3. Verifiable Audit: Preserves pre/post SHA-256 and reproducible unified diff.
    4. Isolated Execution: Direct solver run in isolated solver/<run_id>/ workspace.
    5. Containment Defense: Target path must not escape the designated working directory.
    6. Include Validation: Pre-verifies external *INCLUDE references before launching the solver.
    """
    from ..editing.inp_editor import ControlledInpEditor, InpEditOperation, edit_inp_file

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

    audit_record = edit_inp_file(
        source_path=src_file,
        target_path=dest_inp,
        operations=inp_ops,
        overwrite=overwrite,
        allowed_directory=allowed_dir,
    )

    # Preflight dependency inspection: verify all *INCLUDE references exist
    editor_checker = ControlledInpEditor(dest_inp)
    missing_includes = [
        inc for inc in editor_checker.inspect_includes(base_dir=dest_inp.parent)
        if not inc["exists"]
    ]
    if missing_includes:
        err_detail = "; ".join(
            f"Line {inc['line_number']}: '{inc['input']}'"
            for inc in missing_includes
        )
        raise FileNotFoundError(
            f"Missing required *INCLUDE dependency file(s) for '{dest_inp.name}': {err_detail}"
        )

    solve_res = solve_user_inp(
        executor=executor,
        inp_path=dest_inp,
        job_name=job_name or dest_inp.stem,
        project_context=project_context,
        timeout=timeout,
        run_id=run_id,
    )

    solve_res["audit_record"] = audit_record
    solve_res["source_inp_path"] = str(src_file)
    solve_res["source_inp_sha256"] = audit_record.source_sha256
    solve_res["edited_inp_path"] = str(dest_inp)
    solve_res["edited_inp_sha256"] = audit_record.target_sha256
    solve_res["diff_summary"] = audit_record.diff_summary
    solve_res["lines_changed"] = audit_record.lines_changed
    solve_res["is_edited"] = True
    return solve_res
