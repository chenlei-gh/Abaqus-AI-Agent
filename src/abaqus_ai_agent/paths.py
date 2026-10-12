"""Canonical Workspace Paths and Artifact Location Contracts.

This module provides deterministic, priority-ordered path resolution for:
1. Runtime Sandboxes (transient solver runs, scratch jobs)
2. Authoritative Deliverables (official engineering reports, signed manifests)
3. Validation Assets (benchmarks, golden cases, reference models)

Contract Resolution Order:
1. Explicit argument passed by caller (e.g. pytest tmp_path fixture or caller-specified workdir)
2. Environment variable override (ABAQUS_AGENT_RUNS_DIR, ABAQUS_AGENT_DELIVERABLES_DIR, etc.)
3. Canonical fallback anchored to the project root
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Optional, Union

ENV_RUNS_DIR = "ABAQUS_AGENT_RUNS_DIR"
ENV_DELIVERABLES_DIR = "ABAQUS_AGENT_DELIVERABLES_DIR"
ENV_VALIDATION_ASSETS_DIR = "ABAQUS_AGENT_VALIDATION_ASSETS_DIR"
ENV_PROJECT_ROOT = "ABAQUS_AGENT_PROJECT_ROOT"


@dataclass(frozen=True)
class ExternalProjectContext:
    """Canonical Workspace Context for an External Engineering Project (REQ-ISO-002).

    Strictly separates user engineering assets from the core Abaqus-AI-Agent codebase:
    - input/: Read-only reference copies of original CAD/CAE/INP models and engineering specifications.
    - working/: Editable model working copies, intermediate generative scripts, and mesh adjustments.
    - solver/: Ephemeral and per-run Abaqus execution sandboxes (.odb, .sta, .msg, .dat, .log).
    - evidence/: Per-run evidence manifests, extracted metrics, and verifiable viewer session proofs.
    - delivery/: Authoritative, verified final engineering deliverables (.cae, standalone HTML report, signed manifests).
    """

    project_root: Path
    project_name: str
    input_dir: Path
    working_dir: Path
    solver_dir: Path
    evidence_dir: Path
    delivery_dir: Path

    def assert_within_project(self, target_path: Path) -> Path:
        """Enforce strict path containment to prevent path traversal outside project_root."""
        resolved = target_path.resolve()
        if not resolved.is_relative_to(self.project_root.resolve()):
            raise PermissionError(
                f"Path traversal security violation: path '{resolved}' escapes project root '{self.project_root}'."
            )
        return resolved

    def assert_within_subdir(self, target_path: Path, subdir: Path) -> Path:
        """Enforce strict path containment within a designated sub-directory (REQ-ISO-002)."""
        resolved = target_path.resolve()
        resolved_subdir = subdir.resolve()
        if not resolved.is_relative_to(resolved_subdir):
            raise PermissionError(
                f"Subdirectory boundary violation (REQ-ISO-002): path '{resolved}' "
                f"escapes designated sub-directory '{resolved_subdir}'."
            )
        return resolved

    def _validate_identifier(self, name: str, field_name: str) -> None:
        """Reject path separators, dot-dot traversal, and malicious characters."""
        if not name or not isinstance(name, str):
            raise ValueError(f"Invalid {field_name}: identifier must be a non-empty string.")
        seps = {s for s in ("/", "\\", os.sep, os.altsep) if s}
        if any(sep in name for sep in seps):
            raise ValueError(f"Path traversal security violation: {field_name} '{name}' contains path separators.")
        if ".." in name:
            raise ValueError(f"Path traversal security violation: {field_name} '{name}' contains relative traversal '..'.")
        if not re.match(r"^[a-zA-Z0-9_.-]+$", name):
            raise ValueError(f"Security violation: {field_name} '{name}' contains invalid characters.")

    def create_run_solver_dir(self, run_id: str, ensure_exists: bool = True) -> Path:
        """Create an isolated solver run scratch sandbox under solver/<run_id>/."""
        self._validate_identifier(run_id, "run_id")
        target = (self.solver_dir / run_id).resolve()
        self.assert_within_subdir(target, self.solver_dir)
        if ensure_exists:
            target.mkdir(parents=True, exist_ok=True)
        return target

    def create_run_evidence_dir(self, run_id: str, ensure_exists: bool = True) -> Path:
        """Create an isolated evidence audit directory under evidence/<run_id>/."""
        self._validate_identifier(run_id, "run_id")
        target = (self.evidence_dir / run_id).resolve()
        self.assert_within_subdir(target, self.evidence_dir)
        if ensure_exists:
            target.mkdir(parents=True, exist_ok=True)
        return target

    def prepare_working_copy(
        self,
        source_filename: str,
        target_filename: Optional[str] = None,
        overwrite: bool = False,
    ) -> Path:
        """Safely duplicate a source model from input/ to working/ (Zero In-Place Mutation).

        Guarantees that user original input files are never modified in-place.
        Prevents accidental overwrite of existing working copies unless overwrite=True.
        """
        self._validate_identifier(source_filename, "source_filename")
        if target_filename:
            self._validate_identifier(target_filename, "target_filename")

        source_path = (self.input_dir / source_filename).resolve()
        self.assert_within_subdir(source_path, self.input_dir)
        if not source_path.is_file():
            raise FileNotFoundError(
                f"Cannot prepare working copy: source file '{source_filename}' not found in input dir '{self.input_dir}'."
            )

        dest_name = target_filename or source_filename
        dest_path = (self.working_dir / dest_name).resolve()
        self.assert_within_subdir(dest_path, self.working_dir)

        if dest_path.exists() and not overwrite:
            raise FileExistsError(
                f"Working copy overwrite violation: destination '{dest_path}' already exists. "
                "Set overwrite=True to explicitly permit replacing an existing working copy."
            )

        shutil.copy2(source_path, dest_path)
        return dest_path


def assert_path_outside_repo(path: Union[str, Path], repo_root: Optional[Path] = None) -> Path:
    """Validate that an external project path strictly does not reside inside the core repo (REQ-ISO-003).

    Raises PermissionError if the path points to or inside get_repo_root().
    """
    resolved_path = Path(path).resolve()
    resolved_repo = (repo_root or get_repo_root()).resolve()
    if resolved_path == resolved_repo or resolved_path.is_relative_to(resolved_repo):
        raise PermissionError(
            f"Security violation (REQ-ISO-003): External engineering project path '{resolved_path}' "
            f"cannot reside inside the core Abaqus-AI-Agent repository '{resolved_repo}'."
        )
    return resolved_path


def resolve_project_root(
    override: Optional[Union[str, Path]] = None,
    fail_closed: bool = False,
) -> Optional[Path]:
    """Resolve default external project root from explicit argument or environment variable."""
    if override is not None:
        return Path(override).resolve()
    env_val = os.environ.get(ENV_PROJECT_ROOT, "").strip()
    if env_val:
        return Path(env_val).resolve()
    if fail_closed:
        raise ValueError(
            "Fail-Closed: No external engineering project root configured. "
            f"Pass explicit path or set {ENV_PROJECT_ROOT} environment variable."
        )
    return None


def create_external_project_context(
    project_root: Union[str, Path],
    project_name: Optional[str] = None,
    enforce_outside_repo: bool = True,
    ensure_dirs: bool = True,
) -> ExternalProjectContext:
    """Construct, validate, and initialize an ExternalProjectContext."""
    root_path = Path(project_root).resolve()
    if enforce_outside_repo:
        assert_path_outside_repo(root_path)

    name = project_name or root_path.name or "project"
    input_d = (root_path / "input").resolve()
    working_d = (root_path / "working").resolve()
    solver_d = (root_path / "solver").resolve()
    evidence_d = (root_path / "evidence").resolve()
    delivery_d = (root_path / "delivery").resolve()

    ctx = ExternalProjectContext(
        project_root=root_path,
        project_name=name,
        input_dir=input_d,
        working_dir=working_d,
        solver_dir=solver_d,
        evidence_dir=evidence_d,
        delivery_dir=delivery_d,
    )

    if ensure_dirs:
        for d in (root_path, input_d, working_d, solver_d, evidence_d, delivery_d):
            d.mkdir(parents=True, exist_ok=True)

    return ctx


def get_repo_root() -> Path:
    """Resolve and return the canonical Abaqus-AI-Agent repository root.

    Walks up from this file's location looking for pyproject.toml and src/abaqus_ai_agent.
    """
    candidate = Path(__file__).resolve().parent
    for p in [candidate] + list(candidate.parents):
        if (p / "pyproject.toml").is_file() and (p / "src" / "abaqus_ai_agent").is_dir():
            return p
    # Fallback to standard package depth: src/abaqus_ai_agent/paths.py -> repo root
    return Path(__file__).resolve().parents[2]


def resolve_runs_root(override: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the root directory for ephemeral execution runs.

    Priority:
    1. Explicit override
    2. ABAQUS_AGENT_RUNS_DIR environment variable
    3. get_repo_root() / "runs"
    """
    if override is not None:
        return Path(override).resolve()
    env_val = os.environ.get(ENV_RUNS_DIR, "").strip()
    if env_val:
        return Path(env_val).resolve()
    return (get_repo_root() / "runs").resolve()


def resolve_deliverables_root(override: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the root directory for authoritative engineering deliverables.

    Priority:
    1. Explicit override
    2. ABAQUS_AGENT_DELIVERABLES_DIR environment variable
    3. get_repo_root() / "deliverables"
    """
    if override is not None:
        return Path(override).resolve()
    env_val = os.environ.get(ENV_DELIVERABLES_DIR, "").strip()
    if env_val:
        return Path(env_val).resolve()
    return (get_repo_root() / "deliverables").resolve()


def resolve_validation_assets_root(override: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the root directory for unified validation assets.

    Priority:
    1. Explicit override
    2. ABAQUS_AGENT_VALIDATION_ASSETS_DIR environment variable
    3. get_repo_root() / "validation_assets" (or fallback to machine_validation if exists and validation_assets does not)
    """
    if override is not None:
        return Path(override).resolve()
    env_val = os.environ.get(ENV_VALIDATION_ASSETS_DIR, "").strip()
    if env_val:
        return Path(env_val).resolve()
    root = get_repo_root()
    val_assets = root / "validation_assets"
    if val_assets.is_dir():
        return val_assets.resolve()
    mv_dir = root / "machine_validation"
    if mv_dir.is_dir():
        return mv_dir.resolve()
    return val_assets.resolve()


def create_run_workdir(
    run_id: str,
    runs_root: Optional[Union[str, Path]] = None,
    ensure_exists: bool = True,
) -> Path:
    """Construct and optionally create an isolated per-run scratch directory."""
    root = resolve_runs_root(runs_root)
    workdir = root / run_id
    if ensure_exists:
        workdir.mkdir(parents=True, exist_ok=True)
    return workdir.resolve()
