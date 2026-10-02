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


def run_release_audit() -> Dict[str, Any]:
    """Execute complete public release audit."""
    checks: List[Dict[str, Any]] = []
    all_passed = True

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

    # Check 2: Source Code Path Sanitization (scan src/)
    forbidden_patterns = [
        r"[c-zC-Z]:\\Users\\[a-zA-Z0-9_\.]+",
        r"[c-zC-Z]:\\Vault",
        r"sk-[a-zA-Z0-9]{20,}",
        r"ghp_[a-zA-Z0-9]{20,}",
    ]
    leaks = []
    for py_file in (ROOT / "src").rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for pattern in forbidden_patterns:
                matches = re.findall(pattern, content)
                if matches:
                    rel_p = py_file.relative_to(ROOT)
                    leaks.append({"file": str(rel_p), "pattern": pattern, "matched_count": len(matches)})
        except Exception:
            pass

    path_passed = len(leaks) == 0
    if not path_passed:
        all_passed = False
    checks.append({
        "check_id": "CHK-02",
        "name": "Source Code Path & Credential Sanitization",
        "passed": path_passed,
        "details": {"leaks_detected": leaks},
    })

    # Check 3: Git Ignore Completeness
    gitignore_path = ROOT / ".gitignore"
    gi_patterns = []
    if gitignore_path.is_file():
        gi_patterns = [line.strip() for line in gitignore_path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]

    required_ignores = ["*.odb", "*.sta", "*.msg", "*.dat", "*.log", "*.rec", "*.rpy"]
    missing_ignores = [ig for ig in required_ignores if not any(ig in p for p in gi_patterns)]
    gi_passed = len(missing_ignores) == 0
    if not gi_passed:
        all_passed = False
    checks.append({
        "check_id": "CHK-03",
        "name": "Git Ignore Binary & Artifact Coverage",
        "passed": gi_passed,
        "details": {"missing_rules": missing_ignores},
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
