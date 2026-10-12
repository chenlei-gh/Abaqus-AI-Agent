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
from pathlib import Path
from typing import Optional, Union

ENV_RUNS_DIR = "ABAQUS_AGENT_RUNS_DIR"
ENV_DELIVERABLES_DIR = "ABAQUS_AGENT_DELIVERABLES_DIR"
ENV_VALIDATION_ASSETS_DIR = "ABAQUS_AGENT_VALIDATION_ASSETS_DIR"


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
