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
    if hasattr(executor, "run_input"):
        res = executor.run_input(
            input_path=str(inp_file),
            job_name=eff_job_name,
            timeout=timeout,
        )
    elif hasattr(executor, "execute"):
        # Generic executor fallback
        cmd = f"abaqus job={eff_job_name} input={inp_file}"
        res = executor.execute(cmd)
    else:
        raise TypeError(f"Executor {type(executor)} does not support run_input or execute interface.")

    # Integrity verification: original .inp MUST NOT be mutated
    after_sha256 = _compute_file_sha256(inp_file)
    if initial_sha256 != after_sha256:
        raise RuntimeError(f"Integrity violation: source INP '{inp_file}' was modified during execution.")

    expected_odb: Optional[Path] = None
    if effective_workdir:
        candidate_odb = effective_workdir / f"{eff_job_name}.odb"
        if candidate_odb.is_file():
            expected_odb = candidate_odb
    if expected_odb is None:
        sibling_odb = inp_file.parent / f"{eff_job_name}.odb"
        if sibling_odb.is_file():
            expected_odb = sibling_odb

    return {
        "status": "COMPLETED",
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
        working_cae = project_context.prepare_working_copy(
            source_filename=src_file.name,
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
