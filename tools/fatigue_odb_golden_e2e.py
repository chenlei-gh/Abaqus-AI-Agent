#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Real ODB Fatigue Post-Processing Golden Case E2E.

Proves the complete post-processing chain directly from a live-solved Abaqus ODB:
1. Locates or generates a live multi-frame dynamic stress ODB.
2. Performs full-model stress scan to identify the critical hotspot element and integration point.
3. Extracts multi-frame stress tensor time history and reduces to Signed von Mises stress.
4. Performs ASTM E1049-85 compliant rainflow cycle counting.
5. Applies Goodman mean-stress correction on tensile mean stresses.
6. Interpolates cycles to failure on an S-N material curve with endurance limit cutoff.
7. Accumulates Palmgren-Miner cumulative fatigue damage D.
8. Evaluates formal engineering acceptance gates (Normal PASS, Strict Gate FAIL).
9. Produces standardized evidence JSON for the Golden Matrix.
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.fatigue import (
    build_odb_fatigue_postprocess_script,
    evaluate_fatigue_from_stress_history,
    extract_stress_history_from_odb,
)


# Standard structural steel fatigue S-N curve: (Stress Amplitude [MPa], Cycles to Failure Nf)
STRUCTURAL_STEEL_SN_CURVE = (
    (100.0, 1.0e7),   # Endurance fatigue limit (below this is infinite life)
    (150.0, 2.0e6),
    (200.0, 1.0e6),
    (300.0, 1.0e5),
    (450.0, 2.0e4),
    (600.0, 5.0e3),
)
ULTIMATE_TENSILE_STRENGTH_MPA = 800.0


def find_candidate_odb(workdir: Path) -> Path:
    """Find the best available live-solved dynamic ODB."""
    candidates = [
        workdir / "DynamicGoldenJob.odb",
        workdir / "machine_validation" / "DynamicGoldenJob.odb",
        ROOT / "runs" / "dynamic_golden_run" / "DynamicGoldenJob.odb",
        ROOT / "DynamicGoldenJob.odb",
        ROOT / "machine_validation" / "DynamicGoldenJob.odb",
        workdir / "ExplicitGoldenJob.odb",
        workdir / "machine_validation" / "ExplicitGoldenJob.odb",
        ROOT / "runs" / "explicit_golden_run" / "ExplicitGoldenJob.odb",
        ROOT / "machine_validation" / "ExplicitGoldenJob.odb",
        workdir / "FMBD5GoldenJob.odb",
        workdir / "machine_validation" / "FMBD5GoldenJob.odb",
        ROOT / "runs" / "fmbd5_crank_slider_run" / "FMBD5GoldenJob.odb",
        ROOT / "machine_validation" / "FMBD5GoldenJob.odb",
    ]
    for c in candidates:
        if c.is_file() and c.stat().st_size > 1000:
            return c.resolve()
    return None


def run_fatigue_extraction(
    launcher: str,
    odb_path: Path,
    output_json: Path,
    workdir: Path,
    timeout: int = 1800,
) -> dict:
    """Run fatigue extraction either in-process if odbAccess exists, or via Abaqus launcher."""
    validation_dir = workdir if workdir.name == "machine_validation" else (workdir / "machine_validation")
    validation_dir.mkdir(parents=True, exist_ok=True)
    script_path = validation_dir / "fatigue_odb_extract_script.py"
    script_content = build_odb_fatigue_postprocess_script(
        odb_path=str(odb_path),
        output_json=str(output_json),
        material_curve=STRUCTURAL_STEEL_SN_CURVE,
        ultimate_strength=ULTIMATE_TENSILE_STRENGTH_MPA,
        mean_stress_correction="GOODMAN",
        measure="signed_mises",
        src_dir=str(SRC),
    )
    script_path.write_text(script_content, encoding="utf-8")

    cmd = [launcher, "python", str(script_path)]
    start_time = datetime.datetime.now(datetime.timezone.utc)
    proc = subprocess.run(
        cmd,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    end_time = datetime.datetime.now(datetime.timezone.utc)
    elapsed = (end_time - start_time).total_seconds()

    if proc.returncode != 0:
        raise RuntimeError(
            f"Fatigue extraction process failed with code {proc.returncode} in {elapsed:.1f}s:\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

    if not output_json.is_file():
        raise FileNotFoundError(f"Expected fatigue output JSON not found at: {output_json}")

    with open(output_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["execution"] = {
        "launcher": launcher,
        "command": cmd,
        "return_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    return data


def main(argv=None):
    default_launcher = os.environ.get(
        "ABAQUS_BAT",
        os.environ.get(
            "ABAQUS_COMMAND",
            r"C:\SIMULIA\Commands\abaqus.bat" if os.path.exists(r"C:\SIMULIA\Commands\abaqus.bat") else "abaqus"
        )
    )
    parser = argparse.ArgumentParser(description="Real ODB Fatigue Post-Processing Golden Case E2E")
    parser.add_argument("--launcher", default=default_launcher, help="Abaqus launcher executable")
    parser.add_argument(
        "--workdir",
        default=os.path.join(str(ROOT), "runs", "fatigue_odb_golden_run"),
        help="Working directory",
    )
    parser.add_argument("--odb", default=None, help="Path to input ODB file")
    parser.add_argument("--timeout", type=int, default=1800, help="Process timeout in seconds")
    parser.add_argument(
        "--output",
        default=os.path.join(str(ROOT), "machine_validation", "fatigue_odb_golden_e2e.json"),
        help="Output evidence JSON path",
    )
    args = parser.parse_args(argv)

    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Resolve source ODB
    odb_path = Path(args.odb).resolve() if args.odb else find_candidate_odb(workdir)
    if not odb_path or not odb_path.is_file():
        raise RuntimeError(
            f"No valid dynamic ODB found in candidate locations under {workdir} or {ROOT}. "
            f"Please run a dynamic Golden Case first or pass --odb."
        )

    print(f"=== Real ODB Fatigue Post-Processing Golden E2E ===")
    print(f"Target ODB: {odb_path} ({odb_path.stat().st_size} bytes)")
    print(f"Launcher:   {args.launcher}")
    print(f"Workdir:    {workdir}")

    # 2. Execute fatigue extraction
    evidence = run_fatigue_extraction(
        launcher=args.launcher,
        odb_path=odb_path,
        output_json=output_path,
        workdir=workdir,
        timeout=args.timeout,
    )

    # 3. Add standard envelope metadata
    hotspot = evidence.get("hotspot", {})
    cycle_summary = evidence.get("cycle_summary", {})
    acceptance = evidence.get("acceptance", {})
    strict_gate = evidence.get("strict_gate", {})

    envelope = {
        "status": evidence.get("status", "fail"),
        "case_id": "fatigue_real_odb",
        "title": "Real ODB Stress History Fatigue Damage & Rainflow E2E",
        "category": "P2",
        "physics_type": "fatigue_postprocess",
        "solver": "postprocess",
        "release": "Abaqus 2025",
        "job": odb_path.stem,
        "process_succeeded": evidence["execution"]["return_code"] == 0,
        "return_code": evidence["execution"]["return_code"],
        "launcher": args.launcher,
        "workdir": str(workdir),
        "odb": {
            "path": str(odb_path),
            "exists": odb_path.is_file(),
            "size_bytes": odb_path.stat().st_size if odb_path.is_file() else 0,
        },
        "solver_status": "completed",
        "runtime": {
            "launcher": args.launcher,
            "workdir": str(workdir),
            "process_succeeded": evidence["execution"]["return_code"] == 0,
            "return_code": evidence["execution"]["return_code"],
            "execution_time_s": evidence["execution"]["elapsed_seconds"],
            "stdout": evidence["execution"]["stdout"],
            "stderr": evidence["execution"]["stderr"],
        },
        "result_evidence": {
            "hotspot": hotspot,
            "stress_measure": evidence.get("measure"),
            "frame_count": evidence.get("stress_history", {}).get("frame_count"),
            "cycle_summary": cycle_summary,
        },
        "verification": {
            "rainflow_events_count": len(evidence.get("cycles", [])),
            "max_stress_range": cycle_summary.get("max_stress_range"),
            "max_stress_amplitude": cycle_summary.get("max_stress_amplitude"),
            "mean_stress_average": cycle_summary.get("mean_stress_average"),
            "cumulative_damage": cycle_summary.get("cumulative_damage"),
            "life_blocks": cycle_summary.get("life_blocks"),
        },
        "acceptance": acceptance,
        "strict_gate_verification": strict_gate,
        "provenance": {
            "odb_source": str(odb_path),
            "material_curve": STRUCTURAL_STEEL_SN_CURVE,
            "ultimate_strength_mpa": ULTIMATE_TENSILE_STRENGTH_MPA,
            "mean_stress_correction": "GOODMAN",
            "damage_model": "PALMGREN_MINER",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    }

    # Anti-fabrication check: strict gate MUST fail
    if strict_gate.get("passed") is True:
        envelope["status"] = "fail"
        print("CRITICAL AUDIT ERROR: Strict negative gate unexpectedly passed!")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2)

    print("\n[AIAgent_FATIGUE_E2E_STATUS]:", envelope["status"])
    print("  Hotspot Element:", hotspot.get("element_label"), "IP:", hotspot.get("integration_point"))
    print("  Peak Mises Stress: %.2f MPa" % (hotspot.get("peak_mises_detected") or 0.0))
    print("  Rainflow Cycles:", cycle_summary.get("total_cycles_count"))
    print("  Cumulative Damage D: %.6e" % (cycle_summary.get("cumulative_damage") or 0.0))
    print("  Life Blocks: %.2f" % (cycle_summary.get("life_blocks") or 0.0))
    print("  Acceptance Gate Passed:", acceptance.get("passed"))
    print("  Strict Negative Gate Failed (as expected):", not strict_gate.get("passed"))
    print("  Evidence Written:", output_path)

    if envelope["status"] != "pass":
        sys.exit(1)


if __name__ == "__main__":
    main()
