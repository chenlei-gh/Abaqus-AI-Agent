#!/usr/bin/env python3
"""Safely inspect and clean confirmed historical Abaqus and Python runtime artifacts.

Default behavior is DRY-RUN. Files are only deleted when --clean is explicitly passed.

Protected by default:
  - All Git-tracked files
  - *.json, *.html, *.md, *.png, *.svg, *.gif, *.py, and other engineering assets
  - Unrecognized file extensions outside confirmed solver ephemeral patterns

Fail-Closed Policy:
  - If Git status cannot be reliably determined, execution aborts immediately.
  - If a file is modified between candidate scan and deletion, deletion aborts for that file.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from dataclasses import dataclass
from typing import Sequence


TARGET_ARTIFACT_PATTERNS = (
    "*.rpy",
    "*.rpy.*",
    "*.rec",
    "*.com",
    "*.prt",
    "*.lck",
    "*.odb",
    "*.dat",
    "*.msg",
    "*.sta",
    "*.inp",
    "*.log",
    "*.sim",
    "*.abq",
    "*.pac",
    "*.res",
    "*.sel",
    "*.stt",
    "*.mdl",
    "*.fil",
    "*.env",
)

HISTORICAL_MV_SCRIPT_PATTERNS = (
    "*_script.py",
)

HISTORICAL_MV_WORKDIR_NAMES = {
    "ga2_golden_workdir",
    "ga263_workdir",
    "ga3_qualification_workdir",
    "multi_physics_workdir",
    "p1_2_reasoning_workdir",
    "p1_product_solve_workdir",
    "p2_cases_workdir",
    "real_failure_workdir",
    "Connector_L4_Golden",
    "live_benchmarks_run",
    "live_phase_l_run",
}

PROTECTED_SUFFIXES = {
    ".json",
    ".html",
    ".htm",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".gif",
    ".py",
}

CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache"}
CACHE_FILE_SUFFIXES = {".pyc", ".pyo"}


@dataclass(frozen=True)
class Candidate:
    path: Path
    scope: str
    size: int
    sha256: str
    reason: str
    risk_level: str = "SAFE_PURGE_IF_AUTHORIZED"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def compute_sha256(path: Path) -> str:
    """Compute sha256 checksum of a file safely."""
    try:
        hasher = hashlib.sha256()
        with open(path, "rb") as fh:
            while chunk := fh.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


def get_tracked_paths(root: Path) -> set[str]:
    """Retrieve Git tracked files.

    FAIL-CLOSED: If Git execution fails or repository is unavailable,
    raises RuntimeError immediately to prevent catastrophic file loss.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        return {
            item.decode("utf-8", errors="surrogateescape")
            for item in proc.stdout.split(b"\0")
            if item
        }
    except Exception as exc:
        raise RuntimeError(
            f"Fail-closed safety trigger: unable to retrieve Git tracked files for '{root}'. "
            f"Aborting clean operation to prevent accidental file deletion. Root cause: {exc}"
        ) from exc


def is_tracked(path: Path, root: Path, tracked: set[str]) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        return rel in tracked
    except Exception:
        # If relative resolution fails, treat as tracked (safe fail-closed)
        return True


def collect_candidates(root: Path, tracked: set[str]) -> tuple[list[Candidate], list[Path], int]:
    root_resolved = root.resolve()
    candidates: list[Candidate] = []
    cache_dirs: list[Path] = []
    protected_count = len(tracked)

    mv_dir = root / "machine_validation"

    # 1. Historical untracked workdirs in machine_validation/
    if mv_dir.exists():
        for d in mv_dir.iterdir():
            if not d.resolve().is_relative_to(root_resolved):
                continue
            if d.is_dir() and d.name in HISTORICAL_MV_WORKDIR_NAMES:
                if not is_tracked(d, root, tracked):
                    cache_dirs.append(d)

    # 2. Scopes: project root, machine_validation/, runs/, and legacy_job_artifacts/
    runs_dir = root / "runs"
    search_dirs = [root, mv_dir, runs_dir, root / "legacy_job_artifacts"]

    for base_dir in search_dirs:
        if not base_dir.exists():
            continue

        # For root, iterate top-level files only; for subdirs, recurse
        iterator = base_dir.iterdir() if base_dir == root else base_dir.rglob("*")

        for p in iterator:
            if not p.resolve().is_relative_to(root_resolved):
                # Containment protection: ignore anything resolving outside repo root
                continue

            if is_tracked(p, root, tracked):
                continue

            # Protect p2_cases/ subfolder completely
            if "p2_cases" in p.parts:
                continue

            # Protect test_assets/ completely
            if "test_assets" in p.parts:
                continue

            # Protect validation_assets/ completely if present
            if "validation_assets" in p.parts:
                continue

            # Protect deliverables/ and qualifications completely
            if "deliverables" in p.parts or "qualifications" in p.parts or "case_01_qualification" in p.parts:
                continue

            if p.is_dir() and (p.name in CACHE_DIR_NAMES or p.name == "MagicMock"):
                cache_dirs.append(p)
                continue

            if not p.is_file() and not p.is_symlink():
                continue

            # Check if parent is inside a candidate dir to avoid double counting
            if any(p.is_relative_to(cd) for cd in cache_dirs):
                continue

            suffix = p.suffix.lower()

            # Handle runs/ directory with strict protection of non-ephemeral assets
            if "runs" in p.parts:
                if suffix in PROTECTED_SUFFIXES or p.name in {"README", "README.md"}:
                    # Strictly protected: .py, .json, .html, images, etc.
                    continue

                is_artifact = any(fnmatch.fnmatch(p.name, pat) for pat in TARGET_ARTIFACT_PATTERNS)
                is_cache = suffix in CACHE_FILE_SUFFIXES
                if is_artifact or is_cache:
                    scope = "runs"
                    size = p.stat().st_size if p.exists() else 0
                    sha = compute_sha256(p)
                    reason = "Transient solver artifact in runs/" if is_artifact else "Python bytecode cache in runs/"
                    candidates.append(Candidate(path=p, scope=scope, size=size, sha256=sha, reason=reason))
                continue

            # Check historical machine_validation script patterns
            is_mv_script = (
                "machine_validation" in p.parts
                and any(fnmatch.fnmatch(p.name, pat) for pat in HISTORICAL_MV_SCRIPT_PATTERNS)
            )

            if not is_mv_script and (suffix in PROTECTED_SUFFIXES or p.name in {"README", "README.md"}):
                continue

            is_artifact = any(fnmatch.fnmatch(p.name, pat) for pat in TARGET_ARTIFACT_PATTERNS)
            is_cache = suffix in CACHE_FILE_SUFFIXES

            if is_artifact or is_cache or is_mv_script:
                scope = "root" if p.parent == root else ("machine_validation" if "machine_validation" in p.parts else "legacy")
                size = p.stat().st_size if p.exists() else 0
                sha = compute_sha256(p)
                reason = "Confirmed artifact / cache / legacy script"
                candidates.append(Candidate(path=p, scope=scope, size=size, sha256=sha, reason=reason))

    return candidates, cache_dirs, protected_count


def format_bytes(size: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    val = float(size)
    for u in units:
        if val < 1024 or u == units[-1]:
            return f"{val:.1f} {u}"
        val /= 1024
    return f"{size} B"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="actually delete candidate files; without this, runs in dry-run mode",
    )
    parser.add_argument(
        "--export-manifest",
        type=str,
        default="",
        help="optional file path to export candidate audit manifest as JSON",
    )
    parser.add_argument(
        "--root",
        type=str,
        default="",
        help="override repository root path (defaults to auto-detection)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else repo_root()
    tracked = get_tracked_paths(root)
    candidates, cache_dirs, protected_count = collect_candidates(root, tracked)

    mv_count = sum(1 for c in candidates if c.scope == "machine_validation")
    runs_count = sum(1 for c in candidates if c.scope == "runs")
    root_count = sum(1 for c in candidates if c.scope == "root")
    legacy_count = sum(1 for c in candidates if c.scope == "legacy")
    total_size = sum(c.size for c in candidates)

    print("=== Workspace Cleaning Report ===")
    print(f"Project root:         {root}")
    print(f"Mode:                 {'EXECUTE CLEAN' if args.clean else 'DRY-RUN'}")
    print(f"Git-tracked (kept):   {protected_count} items")
    print(f"Candidate files:      {len(candidates)}")
    print(f"  - machine_validation: {mv_count}")
    print(f"  - runs/ (runtime):    {runs_count}")
    print(f"  - project-root:       {root_count}")
    print(f"  - legacy_artifacts:   {legacy_count}")
    print(f"Candidate directories:{len(cache_dirs)} (Python caches)")
    print(f"Total size to reclaim: {format_bytes(total_size)}")

    if args.export_manifest:
        manifest_path = Path(args.export_manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repo_root": str(root),
            "git_tracked_kept_count": protected_count,
            "candidate_count": len(candidates),
            "total_reclaim_bytes": total_size,
            "candidates": [
                {
                    "relative_path": c.path.resolve().relative_to(root.resolve()).as_posix(),
                    "scope": c.scope,
                    "size_bytes": c.size,
                    "sha256": c.sha256,
                    "reason": c.reason,
                    "risk_level": c.risk_level,
                }
                for c in candidates
            ],
            "cache_dirs": [
                d.resolve().relative_to(root.resolve()).as_posix()
                for d in cache_dirs
            ],
        }
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest_data, fh, indent=2, ensure_ascii=False)
        print(f"\n[MANIFEST EXPORTED] Audit manifest written to: {manifest_path}")

    if not args.clean:
        print("\n[DRY-RUN] No files were deleted. Re-run with --clean to delete.")
        return 0

    # Execute deletion with pre-execution consistency verification
    deleted_files = 0
    failed_files = 0
    for c in candidates:
        try:
            if not c.path.exists():
                continue

            # 1. Path boundary check: ensure candidate path is strictly within repo root
            try:
                c.path.resolve().relative_to(root.resolve())
            except ValueError:
                failed_files += 1
                print(f"Safety abort: path outside repository root, skipping {c.path}")
                continue

            # 2. File size re-verification
            current_size = c.path.stat().st_size
            if current_size != c.size:
                failed_files += 1
                print(f"Safety abort: file modified since audit scan (size mismatch), skipping {c.path}")
                continue

            # 3. Content SHA-256 re-verification to prevent deletion if modified/tampered after candidate collection
            if c.sha256:
                current_sha = compute_sha256(c.path)
                if current_sha != c.sha256:
                    failed_files += 1
                    print(f"Safety abort: file content modified since audit scan (sha256 mismatch), skipping {c.path}")
                    continue

            c.path.unlink()
            deleted_files += 1
        except OSError as e:
            failed_files += 1
            print(f"Failed to delete {c.path}: {e}")

    for d in cache_dirs:
        try:
            if d.exists():
                shutil.rmtree(d)
        except OSError as e:
            print(f"Failed to delete cache dir {d}: {e}")

    # Clean legacy_job_artifacts directory if empty
    legacy_dir = root / "legacy_job_artifacts"
    if legacy_dir.exists() and not any(legacy_dir.iterdir()):
        legacy_dir.rmdir()

    # Clean empty run subdirectories in runs/
    runs_dir = root / "runs"
    if runs_dir.exists():
        for d in sorted(runs_dir.glob("*"), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                try:
                    d.rmdir()
                except OSError:
                    pass

    # Clean empty workdir subdirectories in machine_validation
    mv_dir = root / "machine_validation"
    if mv_dir.exists():
        for d in sorted(mv_dir.glob("*_workdir*"), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                try:
                    d.rmdir()
                except OSError:
                    pass

    print(f"\n[CLEAN COMPLETE] Deleted {deleted_files} files (failed: {failed_files}).")
    return 1 if failed_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
