"""Canonical Workspace Paths and Artifact Location Contracts.

This module provides deterministic, priority-ordered path resolution for:
1. Runtime Sandboxes (transient solver runs, scratch jobs)
2. Authoritative Deliverables (official engineering reports, signed manifests)
3. Validation Assets (benchmarks, golden cases, reference models)

Contract Resolution Order:
1. Explicit argument passed by caller (e.g. pytest tmp_path fixture or caller-specified workdir)
2. Environment variable override (ABAQUS_AGENT_RUNS_DIR, ABAQUS_AGENT_DELIVERABLES_DIR, etc.)
3. User-local fallback outside the git repository
"""

from __future__ import annotations

import os
import re
import uuid
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

    @classmethod
    def create(
        cls,
        project_root: Union[str, Path],
        project_name: Optional[str] = None,
        enforce_outside_repo: bool = True,
        ensure_dirs: bool = True,
    ) -> "ExternalProjectContext":
        """Factory method to construct, validate, and initialize an ExternalProjectContext."""
        return create_external_project_context(
            project_root=project_root,
            project_name=project_name,
            enforce_outside_repo=enforce_outside_repo,
            ensure_dirs=ensure_dirs,
        )

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


def resolve_project_workdir() -> Path:
    """Return the checkout-owned directory for Abaqus session scratch.

    Abaqus writes ``abaqus.rpy``, ``abaqusN.rec``, ``acis_tmp.dbg``, and
    ``temp-*.sat`` into the process cwd. The agent directory is the parent of
    this checkout. Launching CAE there drops those files beside the repository.
    Session scratch belongs in ``<repo>/workdir``, not in that parent directory.
    """
    target = (get_repo_root() / "workdir").resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def is_agent_or_repo_launch_dir(path: Union[str, Path]) -> bool:
    """True when a launch cwd is the agent parent directory or the checkout root."""
    resolved = Path(path).resolve()
    repo = get_repo_root().resolve()
    return resolved == repo or resolved == get_core_workspace_root(repo)


def get_core_workspace_root(repo_root: Optional[Path] = None) -> Path:
    """Return the core file tree that must not hold customer solver copies.

    The product checkout is ``get_repo_root()``. The core workspace is its parent,
    for example ``D:/Vault/Abaqus`` when the checkout is ``D:/Vault/Abaqus/Abaqus-AI-Agent``.
    A solver copy such as ``<core>/ms13l_project`` is still inside the core files even
    though it is outside the git repository.
    """
    resolved_repo = (repo_root or get_repo_root()).resolve()
    parent = resolved_repo.parent
    if parent == resolved_repo:
        return resolved_repo
    return parent


def assert_path_outside_core_workspace(path: Union[str, Path], repo_root: Optional[Path] = None) -> Path:
    """Reject a production path that lands in the repository or its parent workspace.

    Customer solver copies, reports, and scratch files belong in the customer project
    directory. They must not be written beside the product checkout.
    """
    resolved_path = Path(path).resolve()
    core_root = get_core_workspace_root(repo_root)
    if resolved_path == core_root or resolved_path.is_relative_to(core_root):
        raise PermissionError(
            f"Security violation (REQ-ISO-003): Production path '{resolved_path}' "
            f"cannot reside inside the core workspace '{core_root}'. "
            "Solver copies belong in the customer project directory, not beside the product checkout."
        )
    return resolved_path


def assert_path_outside_repo(path: Union[str, Path], repo_root: Optional[Path] = None) -> Path:
    """Validate that an external project path is outside the core workspace (REQ-ISO-003).

    Raises PermissionError if the path points to the product repository, anything inside
    that repository, or the parent workspace that holds the checkout.
    """
    return assert_path_outside_core_workspace(path, repo_root=repo_root)


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


def infer_customer_project_root(
    source_path: Optional[Union[str, Path]] = None,
    project_root: Optional[Union[str, Path]] = None,
) -> Optional[Path]:
    """Find the customer project that should own production artifacts.

    A customer project is recognized by its ``input/working/solver/evidence/delivery``
    layout, or by an explicit root. Source files that merely sit next to a repository
    are not enough: production must not invent a project inside the agent checkout
    or inside the process launch directory.
    """
    explicit = resolve_project_root(project_root, fail_closed=False)
    if explicit is not None:
        try:
            return assert_path_outside_repo(explicit)
        except PermissionError:
            return None
    if source_path is None:
        return None
    current = Path(source_path).resolve()
    start = current.parent if current.is_file() or current.suffix else current
    markers = {"input", "working", "solver", "evidence", "delivery"}
    for candidate in [start] + list(start.parents):
        try:
            assert_path_outside_repo(candidate)
        except PermissionError:
            return None
        if candidate.is_dir() and markers.issubset({item.name for item in candidate.iterdir()}):
            return candidate
        if candidate.name in markers and candidate.parent.is_dir():
            parent = candidate.parent
            try:
                assert_path_outside_repo(parent)
            except PermissionError:
                return None
            if markers.issubset({item.name for item in parent.iterdir()}):
                return parent
    return None


def require_customer_project_context(
    *,
    source_path: Optional[Union[str, Path]] = None,
    project_root: Optional[Union[str, Path]] = None,
    project_name: Optional[str] = None,
    project_context: Optional[ExternalProjectContext] = None,
) -> ExternalProjectContext:
    """Return the customer project that must own every production artifact.

    Production scripts, solver files, and reports are not allowed to fall back to
    the agent repository, the process cwd, or a machine-local scratch directory.
    """
    if project_context is not None:
        assert_path_outside_repo(project_context.project_root)
        return project_context
    root = infer_customer_project_root(source_path=source_path, project_root=project_root)
    if root is None:
        hint = f" source={source_path!s}" if source_path else ""
        raise ValueError(
            "Production artifacts require the customer project directory. "
            "Pass project_root/project_context, or place the source inside a project "
            "that has input/, working/, solver/, evidence/, and delivery/. "
            "Nothing is written to the agent repository or the launch directory."
            + hint
        )
    return create_external_project_context(
        root,
        project_name=project_name or root.name,
        enforce_outside_repo=True,
    )


def resolve_production_scratch(
    *,
    source_path: Optional[Union[str, Path]] = None,
    project_root: Optional[Union[str, Path]] = None,
    project_context: Optional[ExternalProjectContext] = None,
    prefix: str = "scratch",
) -> Path:
    """Return a scratch directory owned by the customer project ``solver/`` tree.

    Production scratch is not allowed to fall back to the process temporary directory,
    the launch directory, the product repository, or the core workspace beside it.
    A missing customer project is a hard failure, not a silent relocation.
    """
    context = require_customer_project_context(
        source_path=source_path,
        project_root=project_root,
        project_context=project_context,
        project_name=prefix,
    )
    target = context.create_run_solver_dir(f"{prefix}_{uuid.uuid4().hex[:8]}")
    assert_path_outside_core_workspace(target)
    return target


def default_local_workspace_root() -> Path:
    """Return the user-local workspace root used when no override is configured.

    This is intentionally outside the git repository. Windows uses LOCALAPPDATA;
    other platforms use the XDG state home. A missing environment variable falls
    back to the user home directory, never to the repository.

    Production customer jobs must not use this directory. It remains only for
    explicit non-production scratch when no customer project exists.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        return (Path(base) / "AbaqusAIAgent").resolve()
    base = os.environ.get("XDG_STATE_HOME", "").strip()
    if not base:
        base = str(Path.home() / ".local" / "state")
    return (Path(base) / "abaqus-ai-agent").resolve()


def resolve_runs_root(override: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the root directory for ephemeral execution runs.

    Priority:
    1. Explicit override
    2. ABAQUS_AGENT_RUNS_DIR environment variable
    3. A user-local directory outside the git repository
    """
    if override is not None:
        return Path(override).resolve()
    env_val = os.environ.get(ENV_RUNS_DIR, "").strip()
    if env_val:
        return Path(env_val).resolve()
    return (default_local_workspace_root() / "runs").resolve()


def resolve_customer_project_root(
    project_context: Optional[Any] = None,
    project_root: Optional[Union[str, Path]] = None,
) -> Optional[Path]:
    """Return the customer data/requirements directory when one was supplied.

    A customer project is not the agent repository and not a machine-local
    scratch directory. Delivery belongs with the data the customer provided.
    """
    if project_context is not None:
        rooted = getattr(project_context, "project_root", None)
        if rooted:
            return Path(rooted).resolve()
    if project_root is not None:
        return Path(project_root).resolve()
    configured = resolve_project_root(fail_closed=False)
    return configured.resolve() if configured is not None else None


def resolve_customer_delivery_dir(
    project_context: Optional[Any] = None,
    project_root: Optional[Union[str, Path]] = None,
    deliverables_dir: Optional[Union[str, Path]] = None,
    source_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Resolve the delivery directory inside the customer-provided project.

    Priority:
    1. Explicit deliverables_dir
    2. ExternalProjectContext.delivery_dir
    3. <customer project root>/delivery
    4. <directory containing the customer source file>/delivery

    There is no machine-local or agent-repository fallback. A job without a
    customer directory cannot invent a delivery location.
    """
    if deliverables_dir is not None:
        return Path(deliverables_dir).resolve()
    if project_context is not None:
        delivery = getattr(project_context, "delivery_dir", None)
        if delivery:
            return Path(delivery).resolve()
    customer_root = resolve_customer_project_root(project_context, project_root)
    if customer_root is not None:
        return (customer_root / "delivery").resolve()
    if source_path is not None:
        return (Path(source_path).resolve().parent / "delivery").resolve()
    raise ValueError(
        "Customer delivery directory is unresolved. Pass the customer data/requirements "
        "directory as project_root, project_context, deliverables_dir, or source_path. "
        "Delivery is not written to the agent repository or a machine-local AppData directory."
    )


def resolve_deliverables_root(
    override: Optional[Union[str, Path]] = None,
    *,
    project_context: Optional[Any] = None,
    project_root: Optional[Union[str, Path]] = None,
    source_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Resolve the customer delivery directory.

    ``ABAQUS_AGENT_DELIVERABLES_DIR`` remains an explicit override for a caller
    that already chose a delivery directory. It is not a substitute for the
    customer project directory.
    """
    if override is not None:
        return Path(override).resolve()
    env_val = os.environ.get(ENV_DELIVERABLES_DIR, "").strip()
    if env_val:
        return Path(env_val).resolve()
    return resolve_customer_delivery_dir(
        project_context=project_context,
        project_root=project_root,
        source_path=source_path,
    )


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
