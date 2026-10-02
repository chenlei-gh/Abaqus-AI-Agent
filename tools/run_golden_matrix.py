#!/usr/bin/env python
"""Abaqus Golden Validation Matrix Manager and Runner.

Provides CLI workflows for:
1. Listing all 9 registered Golden Cases and their evidence status (--list).
2. Validating existing machine evidence files against the unified schema (--validate-evidence).
3. Executing one or all Golden Cases on a live Abaqus launcher (--run).
4. Generating a consolidated Golden Validation Manifest JSON (--manifest-out).
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.golden_registry import (
    GoldenCaseDefinition,
    GoldenMatrixCatalog,
    standard_golden_catalog,
)
from abaqus_ai_agent.golden_evidence import (
    GoldenEvidenceEnvelope,
    load_and_normalize_evidence_file,
    normalize_golden_evidence,
    validate_golden_evidence_dict,
)


def get_evidence_path(case: GoldenCaseDefinition, workdir: Path) -> Path:
    """Resolve evidence path for a case within given workdir or repo root."""
    rel = Path(case.default_evidence_json)
    # Check workdir first
    candidate = workdir / rel.name
    if candidate.is_file():
        return candidate
    candidate = workdir / rel
    if candidate.is_file():
        return candidate
    # Fallback to repo root / machine_validation
    root_candidate = ROOT / rel
    if root_candidate.is_file():
        return root_candidate
    return candidate


def inspect_case_evidence_status(case: GoldenCaseDefinition, workdir: Path) -> Tuple[str, Optional[Path], Optional[str]]:
    """Determine the on-disk status of a Golden Case evidence file.

    Returns:
        (status, path_if_exists, error_message_if_any)
        status: "PASS", "FAIL", "INVALID_SCHEMA", "NO_EVIDENCE"
    """
    path = get_evidence_path(case, workdir)
    if not path.is_file():
        return "NO_EVIDENCE", None, "File does not exist"

    try:
        envelope = load_and_normalize_evidence_file(path)
        errs = validate_golden_evidence_dict(envelope.to_dict())
        if errs:
            return "INVALID_SCHEMA", path, "; ".join(errs)
        if envelope.passed:
            return "PASS", path, None
        return "FAIL", path, "Acceptance passed is False"
    except Exception as exc:
        return "INVALID_SCHEMA", path, str(exc)


def cmd_list(catalog: GoldenMatrixCatalog, workdir: Path) -> int:
    """Print a structured overview of all Golden Cases in the registry."""
    print("=" * 96)
    print(f"{'Abaqus 2025 Real-Machine Golden Validation Matrix Catalog':^96}")
    print("=" * 96)
    header = f"{'Case ID':<22} {'Cat':<5} {'Solver':<9} {'Status':<14} {'Title'}"
    print(header)
    print("-" * 96)

    cases = catalog.all_cases()
    counts = {"PASS": 0, "FAIL": 0, "NO_EVIDENCE": 0, "INVALID_SCHEMA": 0}

    for case in cases:
        status, _, _ = inspect_case_evidence_status(case, workdir)
        counts[status] = counts.get(status, 0) + 1
        status_disp = f"[{status}]"
        print(f"{case.case_id:<22} {case.category:<5} {case.solver:<9} {status_disp:<14} {case.title}")

    print("-" * 96)
    print(
        f"Total: {len(cases)} | "
        f"Passed: {counts['PASS']} | "
        f"Failed: {counts['FAIL']} | "
        f"No Evidence: {counts['NO_EVIDENCE']} | "
        f"Invalid Schema: {counts['INVALID_SCHEMA']}"
    )
    print("=" * 96)
    return 0


def cmd_validate_evidence(
    catalog: GoldenMatrixCatalog,
    target: str,
    workdir: Path,
) -> int:
    """Validate on-disk evidence files against the unified envelope schema."""
    cases = catalog.all_cases() if target in ("all", "*") else [catalog.require_case(target)]

    print(f"\n--- Validating Golden Case Evidence against Unified Schema (Target: {target}) ---")
    all_ok = True

    for case in cases:
        status, path, err = inspect_case_evidence_status(case, workdir)
        print(f"\n[Case: {case.case_id}]")
        print(f"  Title:     {case.title}")
        print(f"  Category:  {case.category} ({case.physics_type})")
        print(f"  File:      {path or 'N/A'}")
        print(f"  Status:    {status}")

        if status == "NO_EVIDENCE":
            print(f"  Result:    MISSING ({err})")
            all_ok = False
        elif status == "INVALID_SCHEMA":
            print(f"  Result:    SCHEMA ERROR ({err})")
            all_ok = False
        elif status == "FAIL":
            print(f"  Result:    ACCEPTANCE FAILED ({err})")
            all_ok = False
        else:
            envelope = load_and_normalize_evidence_file(path)
            print(f"  Result:    VALID (Job: {envelope.job}, ODB: {envelope.odb.get('exists')}, Criteria Passed: {envelope.passed})")

    print("\n" + "=" * 60)
    if all_ok:
        print("Validation Result: ALL TARGET EVIDENCE FILES ARE VALID & PASSED")
        return 0
    else:
        print("Validation Result: ONE OR MORE EVIDENCE CHECKS FAILED OR MISSING")
        return 1


def cmd_run(
    catalog: GoldenMatrixCatalog,
    target: str,
    launcher: str,
    workdir: Path,
    timeout: int = 3600,
) -> int:
    """Execute target Golden Case(s) using the live Abaqus launcher."""
    cases = catalog.all_cases() if target in ("all", "*") else [catalog.require_case(target)]
    workdir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== Executing Live Golden Matrix Run (Target: {target}, Launcher: {launcher}) ===")
    overall_success = True

    for case in cases:
        script_path = ROOT / case.tool_script
        if not script_path.is_file():
            print(f"\nERROR: Runner script not found: {script_path}")
            overall_success = False
            continue

        print(f"\n>> Launching Case: {case.case_id} ({case.title})")
        print(f"   Script: {case.tool_script}")
        cmd = [
            sys.executable,
            str(script_path),
            "--launcher", launcher,
            "--workdir", str(workdir),
            "--timeout", str(timeout),
        ]

        start_time = datetime.datetime.now(datetime.timezone.utc)
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        end_time = datetime.datetime.now(datetime.timezone.utc)
        elapsed = (end_time - start_time).total_seconds()

        if proc.returncode != 0:
            print(f"   FAILED: Return code {proc.returncode} in {elapsed:.1f}s")
            if proc.stderr:
                print("   STDERR:", proc.stderr[-500:])
            overall_success = False
        else:
            print(f"   PASSED: Completed in {elapsed:.1f}s")
            # Verify and print evidence
            status, path, err = inspect_case_evidence_status(case, workdir)
            print(f"   Evidence Status: {status} ({path})")
            if status != "PASS":
                overall_success = False

    return 0 if overall_success else 1


def cmd_emit_manifest(
    catalog: GoldenMatrixCatalog,
    workdir: Path,
    output_path: Path,
) -> int:
    """Generate a comprehensive JSON manifest for all Golden Cases."""
    cases = catalog.all_cases()
    manifest_cases = []
    counts = {"PASS": 0, "FAIL": 0, "NO_EVIDENCE": 0, "INVALID_SCHEMA": 0}

    for case in cases:
        status, path, err = inspect_case_evidence_status(case, workdir)
        counts[status] = counts.get(status, 0) + 1

        case_entry: Dict[str, Any] = {
            "case_id": case.case_id,
            "title": case.title,
            "category": case.category,
            "solver": case.solver,
            "physics_type": case.physics_type,
            "analytical_reference": case.analytical_reference,
            "tool_script": case.tool_script,
            "evidence_status": status,
            "evidence_file": str(path) if path else None,
            "error": err,
        }

        if status == "PASS" and path:
            try:
                env = load_and_normalize_evidence_file(path)
                case_entry["evidence_envelope"] = env.to_dict()
            except Exception as e:
                case_entry["evidence_error"] = str(e)

        manifest_cases.append(case_entry)

    manifest = {
        "manifest_version": "1.0",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "catalog_case_count": len(cases),
        "summary": counts,
        "cases": manifest_cases,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nGolden Validation Manifest written to: {output_path}")
    print(f"Summary: {counts['PASS']}/{len(cases)} Passed, {counts['FAIL']} Failed, {counts['NO_EVIDENCE']} Missing")
    return 0 if counts["FAIL"] == 0 and counts["INVALID_SCHEMA"] == 0 else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Abaqus Real-Machine Golden Validation Matrix Runner & Validator")
    parser.add_argument("--list", action="store_true", help="List all 9 Golden Cases and current status")
    parser.add_argument("--validate-evidence", nargs="?", const="all", help="Validate evidence JSON [case_id|all]")
    parser.add_argument("--run", nargs="?", const="all", help="Execute Golden Case(s) [case_id|all]")
    parser.add_argument("--launcher", default=os.environ.get("ABAQUS_BAT", os.environ.get("ABAQUS_COMMAND", "abaqus")),
                        help="Abaqus launcher command or batch file")
    parser.add_argument("--workdir", default=None, help="Working directory containing machine_validation")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-case timeout in seconds")
    parser.add_argument("--manifest-out", default=None, help="Output path for consolidated manifest JSON")

    args = parser.parse_args(argv)

    catalog = standard_golden_catalog
    workdir = Path(args.workdir or (ROOT / "machine_validation")).resolve()

    if args.list:
        return cmd_list(catalog, workdir)

    if args.validate_evidence:
        return cmd_validate_evidence(catalog, args.validate_evidence, workdir)

    if args.run:
        rc = cmd_run(catalog, args.run, launcher=args.launcher, workdir=workdir, timeout=args.timeout)
        if args.manifest_out:
            cmd_emit_manifest(catalog, workdir, Path(args.manifest_out).resolve())
        return rc

    if args.manifest_out:
        return cmd_emit_manifest(catalog, workdir, Path(args.manifest_out).resolve())

    # Default action if no flags provided: show list
    return cmd_list(catalog, workdir)


if __name__ == "__main__":
    sys.exit(main())
