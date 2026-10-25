"""Read-only protection for tracked machine-validation evidence.

Pytest and CI may read these bundles. They must not refresh timestamps or
rewrite hashes as a side effect. Intentional evidence generation is a separate
tool invocation and must opt out explicitly.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional, Sequence, Union


class EvidenceRewriteError(RuntimeError):
    """Raised when a caller tries to rewrite protected evidence during tests."""


def evidence_writes_locked() -> bool:
    return os.environ.get("ABAQUS_AGENT_EVIDENCE_READONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def is_protected_evidence_path(path: Union[str, Path], repo_root: Optional[Path] = None) -> bool:
    candidate = Path(path)
    if candidate.suffix.lower() != ".json":
        return False
    resolved = candidate.resolve()
    root = (repo_root or _repo_root()).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] == "machine_validation"


def refuse_evidence_rewrite(path: Union[str, Path], repo_root: Optional[Path] = None) -> None:
    if evidence_writes_locked() and is_protected_evidence_path(path, repo_root):
        raise EvidenceRewriteError(
            "Tracked machine_validation JSON is read-only during tests and CI. "
            f"Refusing to rewrite '{path}'. Generate evidence in an explicit tool run "
            "outside pytest, or unset ABAQUS_AGENT_EVIDENCE_READONLY for that invocation only."
        )


def tracked_evidence_dirty(repo_root: Optional[Path] = None) -> list[str]:
    """Return tracked machine_validation paths that differ from HEAD.

    A missing git repository is not treated as a clean tree. Callers that need a
    hard failure should use the workspace guard script.
    """
    root = repo_root or _repo_root()
    if not (root / ".git").exists():
        raise EvidenceRewriteError(f"Cannot audit evidence rewrites without a git repository at '{root}'.")
    proc = subprocess.run(
        ["git", "--no-pager", "status", "--short", "--", "machine_validation"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise EvidenceRewriteError(proc.stderr.strip() or "git status failed while auditing evidence files.")
    dirty: list[str] = []
    for line in proc.stdout.splitlines():
        path = line[3:].strip().strip('"')
        if path.startswith("machine_validation/") or path.startswith("machine_validation\\"):
            dirty.append(path)
    return dirty


def assert_workspace_unpolluted(
    repo_root: Optional[Path] = None,
    extra_paths: Sequence[str] = (
        "deliverables",
        "runs",
        "invalid",
        "machine_validation",
        "validation_assets",
        "test_assets",
    ),
) -> list[str]:
    """Return violations. Empty means the protected paths are clean."""
    root = repo_root or _repo_root()
    violations = [f"evidence:{path}" for path in tracked_evidence_dirty(root)]
    proc = subprocess.run(
        ["git", "--no-pager", "status", "--short", "--", *extra_paths],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise EvidenceRewriteError(proc.stderr.strip() or "git status failed while auditing workspace paths.")
    for line in proc.stdout.splitlines():
        path = line[3:].strip().strip('"')
        if path:
            violations.append(f"workspace:{path}")
    return violations


def _repo_root() -> Path:
    from .paths import get_repo_root

    return get_repo_root()
