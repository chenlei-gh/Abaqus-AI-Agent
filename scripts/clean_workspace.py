#!/usr/bin/env python3
"""Safely inspect and clean Abaqus/Python workspace artifacts.

Default behavior is DRY-RUN. No filesystem mutation occurs unless --apply (or --clean) is
explicitly supplied.

Modes:
  safe       Remove only L0 transient artifacts.
  root-jobs  Archive root-level historical Job_* artifacts to
             legacy_job_artifacts/ (never deletes them).
  deep       Remove solver intermediates from machine_validation while
             preserving declared evidence/delivery files.

The tool never deletes Git-tracked files. Use git to explicitly retire tracked
artifacts after confirming that their evidence/report references are no longer
required.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


L0_PATTERNS = (
    "*.rpy",
    "*.rpy.*",
    "*.rec",
    "*.com",
    "*.prt",
    "*.lck",
)
PY_CACHE_DIRS = {"__pycache__", ".pytest_cache"}
PY_CACHE_SUFFIXES = {".pyc", ".pyo"}

SOLVER_PATTERNS = (
    "*.odb",
    "*.sim",
    "*.sta",
    "*.msg",
    "*.dat",
    "*.com",
    "*.prt",
    "*.lck",
    "*.log",
    "*.abq",
    "*.pac",
    "*.res",
    "*.sel",
    "*.stt",
    "*.mdl",
    "*.fil",
    "*.rpy",
    "*.rpy.*",
    "*.rec",
)

# Files in machine_validation that are intentionally retained as evidence.
DEEP_PRESERVE_SUFFIXES = {
    ".json",
    ".md",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".gif",
}
DEEP_PRESERVE_NAMES = {"README", "README.md"}


@dataclass(frozen=True)
class Candidate:
    path: Path
    action: str
    reason: str

    @property
    def size(self) -> int:
        if self.path.is_file() or self.path.is_symlink():
            try:
                return self.path.stat().st_size
            except OSError:
                return 0
        return 0


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def tracked_paths(root: Path) -> set[str]:
    """Return Git-tracked paths; failure means an empty protection set."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {
        item.decode("utf-8", errors="surrogateescape")
        for item in proc.stdout.split(b"\0")
        if item
    }


def is_tracked(path: Path, root: Path, tracked: set[str]) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return True
    return rel in tracked


def iter_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() or path.is_symlink():
            yield path


def matches(path: Path, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)


def is_python_cache(path: Path) -> bool:
    if path.name in PY_CACHE_DIRS:
        return True
    return path.suffix in PY_CACHE_SUFFIXES


def safe_candidates(root: Path, tracked: set[str]) -> list[Candidate]:
    result: list[Candidate] = []
    for path in iter_files(root):
        if is_tracked(path, root, tracked):
            continue
        if matches(path, L0_PATTERNS) or is_python_cache(path):
            result.append(Candidate(path, "delete", "L0 transient artifact"))
    return result


def root_job_candidates(root: Path, tracked: set[str]) -> list[Candidate]:
    result: list[Candidate] = []
    for path in root.iterdir():
        if not path.is_file() or is_tracked(path, root, tracked):
            continue
        if path.name.startswith("Job_"):
            result.append(
                Candidate(
                    path,
                    "archive",
                    "root-level historical Abaqus Job_* artifact",
                )
            )
    return result


def deep_candidates(root: Path, tracked: set[str]) -> list[Candidate]:
    base = root / "machine_validation"
    if not base.exists():
        return []

    result: list[Candidate] = []
    for path in iter_files(base):
        if is_tracked(path, root, tracked):
            continue
        if path.suffix.lower() in DEEP_PRESERVE_SUFFIXES:
            continue
        if matches(path, SOLVER_PATTERNS):
            result.append(Candidate(path, "delete", "L1/L2 solver intermediate"))
    return result


def format_bytes(size: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def apply_candidates(root: Path, candidates: Sequence[Candidate]) -> tuple[int, int]:
    changed = 0
    failed = 0
    archive_dir = root / "legacy_job_artifacts"

    for item in candidates:
        try:
            if item.action == "archive":
                archive_dir.mkdir(parents=True, exist_ok=True)
                destination = archive_dir / item.path.name
                if destination.exists():
                    stem = destination.stem
                    suffix = destination.suffix
                    index = 2
                    while (archive_dir / f"{stem}.{index}{suffix}").exists():
                        index += 1
                    destination = archive_dir / f"{stem}.{index}{suffix}"
                shutil.move(str(item.path), str(destination))
            elif item.action == "delete":
                if item.path.is_symlink() or item.path.is_file():
                    item.path.unlink()
                elif item.path.is_dir():
                    shutil.rmtree(item.path)
            changed += 1
        except OSError as exc:
            failed += 1
            print(f"ERROR: {item.path}: {exc}")
    return changed, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("safe", "root-jobs", "deep"),
        default="safe",
        help="cleanup scope (default: safe)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually mutate the filesystem; without this flag the command is dry-run",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="alias for --apply",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=repo_root(),
        help="repository root (defaults to the project root)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    do_apply = args.apply or args.clean

    tracked = tracked_paths(root)
    if args.mode == "safe":
        candidates = safe_candidates(root, tracked)
    elif args.mode == "root-jobs":
        candidates = root_job_candidates(root, tracked)
    else:
        candidates = deep_candidates(root, tracked)

    total = sum(item.size for item in candidates)
    print(f"Workspace: {root}")
    print(f"Mode: {args.mode}")
    print(f"Tracked-file protection: {'enabled' if tracked else 'unavailable'}")
    print(f"Action: {'APPLY' if do_apply else 'DRY-RUN'}")
    print(f"Candidates: {len(candidates)} ({format_bytes(total)})")

    for item in candidates:
        print(f"[{item.action.upper():7}] {item.path.relative_to(root)}  # {item.reason}")

    if not candidates:
        print("Nothing to clean.")
        return 0

    if not do_apply:
        print("\nDry-run only. Re-run with --apply (or --clean) to mutate the filesystem.")
        return 0

    changed, failed = apply_candidates(root, candidates)
    print(f"Applied: {changed}; failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
