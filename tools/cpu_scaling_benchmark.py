#!/usr/bin/env python3
"""Reproducible CPU-scaling benchmark for Abaqus Standard and Explicit.

The benchmark generates a structured hex beam, runs it through the real Abaqus
launcher with a fixed ``cpus=N``, and records independent timings:

* ``solver_phase_seconds`` -- the solver phase parsed from ``.log`` by the
  production ``solver_timing`` reader (primary scaling metric). It includes
  solver process startup, which is why jobs are sized well above one second;
* ``dat_wallclock_seconds`` -- the JOB TIME SUMMARY wallclock in ``.dat``;
* ``wall_seconds`` -- host submission-to-completion duration.

Completion is judged by the T-P3 terminal-state contract, not by exit code or
ODB existence. Results are written as JSON; no git-tracked files are touched.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.execution.solver import classify_solver_terminal_state  # noqa: E402
from abaqus_ai_agent.execution.solver_timing import read_solver_timing  # noqa: E402

_WALL_RE = re.compile(r"WALLCLOCK TIME \(SEC\)\s*=\s*([0-9.]+)", re.IGNORECASE)


def _beam_divisions(elements: int) -> Tuple[int, int, int]:
    """Choose nx:ny:nz = 10:1:1 with near-cubic elements."""
    k = max(2, int(round((max(int(elements), 10) / 10.0) ** (1.0 / 3.0))))
    return 10 * k, k, k


def _mesh(nx: int, ny: int, nz: int) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, ...]]]:
    lx, ly, lz = 200.0, 20.0, 20.0
    dx, dy, dz = lx / nx, ly / ny, lz / nz

    def nid(i: int, j: int, k: int) -> int:
        return 1 + i + j * (nx + 1) + k * (nx + 1) * (ny + 1)

    nodes = []
    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx + 1):
                nodes.append((round(i * dx, 9), round(j * dy, 9), round(k * dz, 9)))

    elements = []
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                elements.append((
                    nid(i, j, k), nid(i + 1, j, k), nid(i + 1, j + 1, k), nid(i, j + 1, k),
                    nid(i, j, k + 1), nid(i + 1, j, k + 1), nid(i + 1, j + 1, k + 1), nid(i, j + 1, k + 1),
                ))
    return nodes, elements


def _write_inp(path: Path, solver: str, nx: int, ny: int, nz: int,
               increments: int, step_time: float) -> Dict[str, int]:
    nodes, elements = _mesh(nx, ny, nz)
    fixed = [nid for nid, (x, _, _) in enumerate(nodes, start=1) if abs(x) < 1e-12]
    loaded = [nid for nid, (x, _, _) in enumerate(nodes, start=1) if abs(x - 200.0) < 1e-9]

    is_explicit = solver == "explicit"
    lines: List[str] = [
        "*HEADING",
        "CPU scaling benchmark - %s" % solver,
        "*PREPRINT, ECHO=NO, MODEL=NO, HISTORY=NO, CONTACT=NO",
        "*NODE",
    ]
    lines += ["%d, %.9g, %.9g, %.9g" % (nid, x, y, z) for nid, (x, y, z) in enumerate(nodes, start=1)]
    lines += ["*ELEMENT, TYPE=%s, ELSET=EALL" % ("C3D8R" if is_explicit else "C3D8")]
    lines += ["%d, %s" % (eid, ", ".join(str(n) for n in conn)) for eid, conn in enumerate(elements, start=1)]
    lines += ["*NSET, NSET=FIXED"] + [str(n) for n in fixed]
    lines += ["*NSET, NSET=LOADED"] + [str(n) for n in loaded]
    lines += [
        "*SOLID SECTION, ELSET=EALL, MATERIAL=STEEL",
        ",",
        "*MATERIAL, NAME=STEEL",
        "*ELASTIC",
        "210000., 0.3",
    ]
    if is_explicit:
        lines += ["*DENSITY", "7.85e-09"]
    if is_explicit:
        lines += ["*STEP, NAME=LOAD", "*DYNAMIC, EXPLICIT", ", %.9g" % step_time]
    else:
        lines += ["*STEP, NAME=LOAD, INC=%d" % max(20, increments * 2), "*STATIC",
                  "%.9g, 1.0, 1e-08, %.9g" % (1.0 / increments, 1.0 / increments)]
    lines += ["*BOUNDARY", "FIXED, 1, 3", "*CLOAD", "LOADED, 1, -1.0"]
    if is_explicit:
        lines += ["*OUTPUT, FIELD, VARIABLE=PRESELECT, NUMBER INTERVAL=10000"]
    else:
        lines += ["*OUTPUT, FIELD, VARIABLE=PRESELECT, FREQUENCY=0"]
    lines += ["*END STEP"]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return {"nodes": len(nodes), "elements": len(elements), "nx": nx, "ny": ny, "nz": nz}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="latin-1", errors="replace")
    except OSError:
        return ""


def _terminal_state(workdir: Path, job: str, returncode: int) -> Tuple[str, List[str]]:
    sta = _read_text(workdir / (job + ".sta")).upper()
    msg = _read_text(workdir / (job + ".msg")).upper()
    log = _read_text(workdir / (job + ".log")).upper()
    verdict = classify_solver_terminal_state(
        returncode=returncode,
        sta_completed="THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in sta,
        sta_not_completed="THE ANALYSIS HAS NOT BEEN COMPLETED" in sta,
        msg_not_completed="THE ANALYSIS HAS NOT BEEN COMPLETED" in msg,
        msg_error="***ERROR" in msg or "***FATAL" in msg,
        kernel_completed="ABAQUS/STANDARD ANALYSIS" in log or "ABAQUS/EXPLICIT ANALYSIS" in log,
        odb_present=(workdir / (job + ".odb")).is_file(),
    )
    return verdict.state.value, list(verdict.evidence)


def _wait_for_completion(workdir: Path, job: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    lock = workdir / (job + ".lck")
    log_path = workdir / (job + ".log")
    sta_path = workdir / (job + ".sta")
    msg_path = workdir / (job + ".msg")
    dat_path = workdir / (job + ".dat")
    start_deadline = min(deadline, time.time() + 30.0)
    while time.time() < start_deadline:
        if lock.exists() or log_path.exists() or sta_path.exists():
            break
        time.sleep(0.5)
    while time.time() < deadline:
        log = _read_text(log_path).upper()
        sta = _read_text(sta_path).upper()
        msg = _read_text(msg_path).upper()
        dat = _read_text(dat_path).upper()
        terminated = (
            "THE ANALYSIS HAS BEEN TERMINATED" in log
            or "EXITED WITH ERROR" in log
            or "ABAQUS ERROR" in log
            or "***ERROR" in msg
            or "***FATAL" in msg
            or "THE ANALYSIS HAS NOT BEEN COMPLETED" in sta
            or "FATAL ERRORS" in dat
        )
        completed = (
            "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in sta
            or ("ABAQUS JOB" in log and "COMPLETED" in log)
        )
        if not lock.exists() and (completed or terminated):
            time.sleep(0.5)
            return True
        time.sleep(1.0)
    return False


def _run_once(launcher: str, solver: str, elements: int, cpus: int, workdir: Path,
              increments: int, step_time: float, timeout: int) -> Dict[str, object]:
    nx, ny, nz = _beam_divisions(elements)
    run_dir = workdir / ("%s_c%d_%s" % (solver, cpus, datetime.now(timezone.utc).strftime("%H%M%S%f")))
    run_dir.mkdir(parents=True, exist_ok=False)
    job = "bench"
    mesh = _write_inp(run_dir / (job + ".inp"), solver, nx, ny, nz, increments, step_time)
    cmd = [launcher, "job=%s" % job, "input=%s" % (job + ".inp"), "cpus=%d" % cpus]
    started = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=str(run_dir), capture_output=True, text=True, timeout=120)
        submit_stdout = "\n".join((proc.stdout or "").splitlines()[-10:])
        submit_stderr = "\n".join((proc.stderr or "").splitlines()[-10:])
        if proc.returncode != 0:
            return_code = proc.returncode
            completed = False
        else:
            completed = _wait_for_completion(run_dir, job, timeout)
            return_code = 0 if completed else -1
    except subprocess.TimeoutExpired:
        submit_stdout = ""
        submit_stderr = "submission timeout"
        return_code = -1
        completed = False
    wall_seconds = time.perf_counter() - started

    dat_text = _read_text(run_dir / (job + ".dat"))
    state, evidence = _terminal_state(run_dir, job, return_code)
    timing = read_solver_timing(run_dir / (job + ".log"))
    wall_match = _WALL_RE.search(dat_text)
    return {
        "solver": solver,
        "requested_elements": elements,
        "mesh": mesh,
        "cpus": cpus,
        "returncode": return_code,
        "completed": completed,
        "wall_seconds": round(wall_seconds, 3),
        "solver_phase_seconds": timing.solver_seconds if timing.measured else None,
        "dat_wallclock_seconds": float(wall_match.group(1)) if wall_match else None,
        "timing_status": timing.status.value,
        "terminal_state": state,
        "terminal_evidence": evidence,
        "submit_stdout": submit_stdout,
        "submit_stderr": submit_stderr,
        "run_dir": str(run_dir),
    }


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", choices=("standard", "explicit"), required=True)
    parser.add_argument("--elements", type=int, default=7290)
    parser.add_argument("--cpus", default="1,2,4,8")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--increments", type=int, default=10, help="Standard fixed increments")
    parser.add_argument("--step-time", type=float, default=1e-3, help="Explicit step period (s)")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--launcher", default=os.environ.get("ABAQUS_LAUNCHER", r"C:\SIMULIA\Commands\abaqus.BAT"))
    parser.add_argument("--outdir", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--skip-warmup", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.outdir) if args.outdir else Path(os.environ.get("TEMP", ".")) / "abaqus_cpu_bench"
    root.mkdir(parents=True, exist_ok=True)
    cpus = [int(x) for x in args.cpus.split(",") if x.strip()]
    label = args.label or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results: List[Dict[str, object]] = []

    host = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
    }

    if not args.skip_warmup:
        warm = _run_once(args.launcher, args.solver, args.elements, cpus[0], root,
                         args.increments, args.step_time, args.timeout)
        warm["warmup"] = True
        results.append(warm)

    for cpus_n in cpus:
        for rep in range(1, args.repeats + 1):
            record = _run_once(args.launcher, args.solver, args.elements, cpus_n, root,
                               args.increments, args.step_time, args.timeout)
            record["repeat"] = rep
            results.append(record)
            print(json.dumps({k: record[k] for k in (
                "solver", "cpus", "repeat", "solver_phase_seconds",
                "dat_wallclock_seconds", "wall_seconds", "terminal_state",
                "timing_status")}), flush=True)

    summary = []
    for cpus_n in cpus:
        measured = [r for r in results if r.get("cpus") == cpus_n and not r.get("warmup")
                    and r.get("solver_phase_seconds") is not None]
        values = [float(r["solver_phase_seconds"]) for r in measured]
        summary.append({
            "cpus": cpus_n,
            "samples": len(values),
            "median_solver_phase_seconds": round(_median(values), 3) if values else None,
            "min_solver_phase_seconds": min(values) if values else None,
            "max_solver_phase_seconds": max(values) if values else None,
        })

    baseline = next((s["median_solver_phase_seconds"] for s in summary if s["cpus"] == 1), None)
    for item in summary:
        value = item["median_solver_phase_seconds"]
        if baseline and value:
            item["speedup_vs_1cpu"] = round(baseline / value, 3)
            item["parallel_efficiency"] = round((baseline / value) / item["cpus"], 3)
        else:
            item["speedup_vs_1cpu"] = None
            item["parallel_efficiency"] = None

    payload = {
        "label": label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "launcher": args.launcher,
        "solver": args.solver,
        "requested_elements": args.elements,
        "actual_elements": results[0]["mesh"]["elements"] if results else None,
        "increments": args.increments,
        "step_time": args.step_time,
        "summary": summary,
        "runs": results,
    }
    out = root / ("cpu_scaling_%s_%s.json" % (args.solver, label))
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("RESULT_JSON=%s" % out)
    print(json.dumps({"summary": summary}, ensure_ascii=False))
    return 0 if all(s["median_solver_phase_seconds"] for s in summary) else 2


if __name__ == "__main__":
    raise SystemExit(main())