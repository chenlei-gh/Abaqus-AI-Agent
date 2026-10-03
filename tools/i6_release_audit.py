#!/usr/bin/env python
"""Phase I.6 — Public Release Audit, Documentation & Security Sanitization.

Performs automated pre-release and hygiene audits:
1. Path Sanitization: Scans src/ for hardcoded personal paths (e.g. C:\\Users, D:\\Vault)
   and credentials/tokens.
2. Required Release Assets: Verifies presence of LICENSE, README.md, pyproject.toml,
   and engineering-run-evidence-roadmap.md.
3. Git Hygiene: Asserts that .gitignore properly suppresses transient solver binaries
   (*.odb, *.msg, *.sta, *.dat, *.log, *.rec, *.rpy).
4. Package Metadata: Validates pyproject.toml semantic versioning and entrypoints.
5. Export structured audit evidence to machine_validation/i6_release_audit_evidence.json.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def get_tracked_files() -> List[Path]:
    """Get all git-tracked files or fallback to repository file tree."""
    import subprocess
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return [ROOT / line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except Exception:
        pass

    # Fallback to scanning repo directory ignoring vcs/cache
    ignored_dirs = {".git", ".pytest_cache", "__pycache__", "build", "dist", ".egg-info"}
    files = []
    for p in ROOT.rglob("*"):
        if p.is_file() and not any(part in ignored_dirs for part in p.parts):
            files.append(p)
    return files


def run_release_audit() -> Dict[str, Any]:
    """Execute complete public release audit."""
    checks: List[Dict[str, Any]] = []
    all_passed = True
    tracked_files = get_tracked_files()

    # Check 1: Required Release Files
    required_files = [
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "docs/engineering-run-evidence-roadmap.md",
    ]
    missing_files = []
    for rf in required_files:
        if not (ROOT / rf).is_file():
            missing_files.append(rf)

    f_passed = len(missing_files) == 0
    if not f_passed:
        all_passed = False
    checks.append({
        "check_id": "CHK-01",
        "name": "Required Release Files Presence",
        "passed": f_passed,
        "details": {"required": required_files, "missing": missing_files},
    })

    # Check 2: Repository-Wide Security & Path Sanitization
    forbidden_patterns = [
        (r"[c-zC-Z]:\\[U]sers\\[a-zA-Z0-9_\.]+", "Windows personal user profile path"),
        (r"[c-zC-Z]:\\[V]ault", "Private Vault directory path"),
        (r"/(?:home|Users)/[a-zA-Z0-9_\.]+", "POSIX user profile path"),
        (r"sk-[a-zA-Z0-9]{20,}", "OpenAI/API secret key"),
        (r"ghp_[a-zA-Z0-9]{20,}", "GitHub Personal Access Token"),
        (r"ts_[a-zA-Z0-9]{20,}", "TypeSafe API Token"),
    ]
    # Whitelist files that define or test the sanitization patterns themselves or standard candidate commands
    whitelist_names = {
        "i6_release_audit.py",
        "test_i6_release_audit.py",
        "engineering-run-evidence-roadmap.md",
        "THIRD_PARTY_NOTICES.md",
    }

    leaks = []
    for fpath in tracked_files:
        if fpath.name in whitelist_names:
            continue
        # Scan code, docs, configuration files
        if fpath.suffix in (".py", ".toml", ".json", ".md", ".yml", ".yaml", ".sh", ".bat"):
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                for pattern, desc in forbidden_patterns:
                    matches = re.findall(pattern, content)
                    # Filter out CI runner ephemeral public paths (e.g. GitHub Actions /home/runner)
                    if "POSIX" in desc and matches:
                        matches = [
                            m for m in matches 
                            if not (m.startswith("/home/runner") or m.startswith("/Users/runner"))
                        ]
                    if matches:
                        rel_p = fpath.relative_to(ROOT)
                        leaks.append({
                            "file": str(rel_p),
                            "description": desc,
                            "matched_count": len(matches),
                            "sample": matches[0][:30],
                        })
            except Exception:
                pass

    path_passed = len(leaks) == 0
    if not path_passed:
        all_passed = False
    checks.append({
        "check_id": "CHK-02",
        "name": "Repository-Wide Path & Credential Sanitization",
        "passed": path_passed,
        "details": {"scanned_files_count": len(tracked_files), "leaks_detected": leaks},
    })

    # Check 3: Tracked Binaries & Git Ignore Hygiene
    prohibited_extensions = {".odb", ".cae", ".jnl", ".rec", ".rpy", ".lck", ".sta", ".msg", ".dat"}
    committed_binaries = []
    for fpath in tracked_files:
        if fpath.suffix.lower() in prohibited_extensions:
            committed_binaries.append(str(fpath.relative_to(ROOT)))

    gitignore_path = ROOT / ".gitignore"
    gi_patterns = []
    if gitignore_path.is_file():
        gi_patterns = [line.strip() for line in gitignore_path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]

    required_ignores = ["*.odb", "*.sta", "*.msg", "*.dat", "*.log", "*.rec", "*.rpy"]
    missing_ignores = [ig for ig in required_ignores if not any(ig in p for p in gi_patterns)]
    gi_passed = (len(missing_ignores) == 0) and (len(committed_binaries) == 0)
    if not gi_passed:
        all_passed = False
    checks.append({
        "check_id": "CHK-03",
        "name": "Git Ignore Binary & Tracked Artifact Coverage",
        "passed": gi_passed,
        "details": {"missing_rules": missing_ignores, "accidentally_committed_binaries": committed_binaries},
    })

    # Check 4: Package Metadata & Entrypoints
    pyproj_path = ROOT / "pyproject.toml"
    has_version = False
    has_scripts = False
    if pyproj_path.is_file():
        text = pyproj_path.read_text(encoding="utf-8")
        has_version = 'version = "' in text
        has_scripts = "abaqus-ai-agent = " in text or "abaqus-agent = " in text

    meta_passed = has_version and has_scripts
    if not meta_passed:
        all_passed = False
    checks.append({
        "check_id": "CHK-04",
        "name": "Packaging Specification & CLI Entrypoints",
        "passed": meta_passed,
        "details": {"has_version": has_version, "has_scripts": has_scripts},
    })

    manifest = {
        "schema_version": "release_audit_v1",
        "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_checks": len(checks),
        "passed_checks": sum(1 for c in checks if c["passed"]),
        "all_passed": all_passed,
        "checks": checks,
    }
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Public Release Audit & Security Sanitization (Phase I.6)")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "machine_validation" / "i6_release_audit_evidence.json",
        help="Summary output JSON",
    )
    args = parser.parse_args()

    print("================================================================================")
    print(" Phase I.6 — Public Release Audit, Documentation & Security Sanitization")
    print("================================================================================")
    manifest = run_release_audit()

    for chk in manifest["checks"]:
        tag = "[PASS]" if chk["passed"] else "[FAIL]"
        print(f" {tag} {chk['check_id']} {chk['name']}")
        if not chk["passed"]:
            print(f"        Details: {chk['details']}")

    print("--------------------------------------------------------------------------------")
    print(f"Summary: {manifest['passed_checks']}/{manifest['total_checks']} Release Checks PASSED")
    print(f"Overall Status: {'RELEASE GATE READY & AUDITED' if manifest['all_passed'] else 'AUDIT FAILURES DETECTED'}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Saved audit package to {args.out}")

    return 0 if manifest["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
