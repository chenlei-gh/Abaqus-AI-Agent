# -*- coding: utf-8 -*-
"""Abaqus 2025 Live Real-Machine Verification Suite.

Validates controlled INP editing, authentic solver execution, deep ODB extraction,
and transactional rollback inside an isolated external project directory (e.g. D:\AbaqusProjects\Cantilever_Live_Verification).
Guarantees ZERO contamination of the core Abaqus-AI-Agent codebase.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.execution.batch import BatchExecutor
from abaqus_ai_agent.execution.input_modes import edit_and_solve_user_inp, solve_user_inp
from abaqus_ai_agent.execution.solver import verify_authentic_odb_structure
from abaqus_ai_agent.paths import ExternalProjectContext

DEFAULT_PROJECT_ROOT = Path(r"D:\AbaqusProjects\Cantilever_Live_Verification")
DEFAULT_LAUNCHER = r"C:\SIMULIA\Commands\abaqus.bat"


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def generate_3d_cantilever_inp(dest_path: Path, length=100.0, width=10.0, height=10.0, nx=20, ny=2, nz=2):
    """Generate an authentic, self-contained 3D C3D8R Cantilever Beam INP deck."""
    dx = length / nx
    dy = width / ny
    dz = height / nz

    def nid(i, j, k):
        return 1 + i * (ny + 1) * (nz + 1) + j * (nz + 1) + k

    lines = [
        "*HEADING",
        "Cantilever 3D C3D8R Live Abaqus 2025 Verification",
        "*NODE",
    ]

    for i in range(nx + 1):
        x = i * dx
        for j in range(ny + 1):
            y = j * dy
            for k in range(nz + 1):
                z = k * dz
                lines.append(f"{nid(i, j, k)}, {x:.4f}, {y:.4f}, {z:.4f}")

    lines.append("*ELEMENT, TYPE=C3D8R, ELSET=BEAM_ELEMENTS")
    eid = 1
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                n1 = nid(i, j, k)
                n2 = nid(i + 1, j, k)
                n3 = nid(i + 1, j + 1, k)
                n4 = nid(i, j + 1, k)
                n5 = nid(i, j, k + 1)
                n6 = nid(i + 1, j, k + 1)
                n7 = nid(i + 1, j + 1, k + 1)
                n8 = nid(i, j + 1, k + 1)
                lines.append(f"{eid}, {n1}, {n2}, {n3}, {n4}, {n5}, {n6}, {n7}, {n8}")
                eid += 1

    lines.append("*NSET, NSET=FIXED_NODES")
    fixed_nodes = [nid(0, j, k) for j in range(ny + 1) for k in range(nz + 1)]
    lines.append(", ".join(str(n) for n in fixed_nodes))

    lines.append("*NSET, NSET=TIP_NODES")
    tip_nodes = [nid(nx, j, k) for j in range(ny + 1) for k in range(nz + 1)]
    lines.append(", ".join(str(n) for n in tip_nodes))

    lines.extend([
        "*MATERIAL, NAME=STEEL",
        "*ELASTIC",
        " 210000.0, 0.3",
        "*DENSITY",
        " 7.85e-9",
        "*SOLID SECTION, ELSET=BEAM_ELEMENTS, MATERIAL=STEEL",
        "*BOUNDARY",
        "FIXED_NODES, 1, 3, 0.0",
        "*STEP, NAME=STEP-1, NLGEOM=NO",
        "*STATIC",
        "1.0, 1.0, 1e-05, 1.0",
        "*CLOAD",
    ])

    total_force_y = -1000.0
    f_per_node = total_force_y / len(tip_nodes)
    for n in tip_nodes:
        lines.append(f"{n}, 2, {f_per_node:.4f}")

    lines.extend([
        "*OUTPUT, FIELD",
        "*NODE OUTPUT",
        " U, RF",
        "*ELEMENT OUTPUT",
        " S",
        "*END STEP",
    ])

    dest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_beam_metrics(odb_path: Path, launcher: str) -> Dict[str, float]:
    """Extract physical metrics from authentic ODB via native Abaqus Python."""
    odb_str = str(odb_path).replace("\\", "/")
    code = f"""
import sys, json
from odbAccess import openOdb

odb = openOdb({odb_str!r}, readOnly=True)
last_step = list(odb.steps.values())[-1]
last_frame = last_step.frames[-1]

u_fld = last_frame.fieldOutputs['U']
max_u_mag = max(float(v.magnitude) for v in u_fld.values)
min_u2 = min(float(v.data[1]) for v in u_fld.values)

s_fld = last_frame.fieldOutputs['S']
max_mises = max(float(v.mises) for v in s_fld.values)

odb.close()
res = {{
    'max_u_mag': max_u_mag,
    'min_u2': min_u2,
    'max_mises': max_mises
}}
print('__RESULTS__' + json.dumps(res))
"""
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "extract.py"
        script.write_text(code, encoding="utf-8")
        proc = subprocess.run(
            [launcher, "python", str(script)],
            cwd=td,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ODB extraction failed: {proc.stderr}")
        for line in proc.stdout.splitlines():
            if line.startswith("__RESULTS__"):
                return json.loads(line[len("__RESULTS__"):])
        raise RuntimeError(f"No structured metrics extracted: {proc.stdout}")


def odb_authenticity_validator(odb_file: Path, launcher: str) -> bool:
    """Deep structural validator requiring authentic frames, mesh, and fields."""
    chk = verify_authentic_odb_structure(
        odb_file,
        required_fields=["U", "S"],
        required_step="STEP-1",
        launcher_cmd=launcher,
    )
    return bool(chk.get("verified", False))


def run_verification(project_root: Path = DEFAULT_PROJECT_ROOT, launcher: str = DEFAULT_LAUNCHER) -> Dict[str, Any]:
    print("=======================================================================")
    print("  Abaqus 2025 Live Real-Machine Verification Suite (External Isolated) ")
    print("=======================================================================")
    ctx = ExternalProjectContext.create(project_root)
    print(f"[Setup] Project root initialized at: {ctx.project_root}")
    print(f"  input/:    {ctx.input_dir}")
    print(f"  working/:  {ctx.working_dir}")
    print(f"  solver/:   {ctx.solver_dir}")
    print(f"  evidence/: {ctx.evidence_dir}")
    print(f"  delivery/: {ctx.delivery_dir}")

    base_inp_path = ctx.input_dir / "cantilever_base.inp"
    generate_3d_cantilever_inp(base_inp_path)
    base_sha256 = compute_sha256(base_inp_path)
    print(f"[Model] Base INP generated: {base_inp_path.name} (SHA-256: {base_sha256[:12]}...)")

    executor = BatchExecutor(launcher=launcher)
    summary_report = {}

    validator = lambda p: odb_authenticity_validator(p, executor.resolved_launcher)

    # -------------------------------------------------------------------------
    # STEP 1: Baseline Solve & Deep ODB Verification
    # -------------------------------------------------------------------------
    print("\n>>> [STEP 1] Baseline Solve on cantilever_base.inp...")
    run_01_id = "run_01_baseline"
    res_01 = solve_user_inp(
        executor=executor,
        inp_path=base_inp_path,
        job_name="CantileverBaseJob",
        project_context=ctx,
        run_id=run_01_id,
        require_verified_odb=True,
        odb_validator=validator,
    )
    print(f"  Status: {res_01['status']}, RC: {res_01['returncode']}, ODB Valid: {res_01['odb_valid']}")
    assert res_01["status"] == "COMPLETED", f"Step 1 failed: {res_01.get('error')}"
    assert res_01["returncode"] == 0
    assert res_01["odb_valid"] is True
    assert res_01["odb_verified"] is True
    assert compute_sha256(base_inp_path) == base_sha256, "Baseline INP mutated during Step 1!"

    metrics_01 = extract_beam_metrics(Path(res_01["odb_path"]), executor.resolved_launcher)
    print("  Extracted Baseline Metrics:")
    print(f"    Max Deflection: {metrics_01['max_u_mag']:.5f} mm")
    print(f"    Min Tip U2:     {metrics_01['min_u2']:.5f} mm")
    print(f"    Max Stress:     {metrics_01['max_mises']:.2f} MPa")

    ev1 = ctx.create_run_evidence_dir(run_01_id)
    (ev1 / "evidence.json").write_text(json.dumps({
        "run_id": run_01_id,
        "status": res_01["status"],
        "metrics": metrics_01,
        "source_sha256": base_sha256,
        "odb_path": res_01["odb_path"],
    }, indent=2), encoding="utf-8")
    summary_report["step_1_baseline"] = {"status": "PASS", "run_id": run_01_id, "metrics": metrics_01}

    # -------------------------------------------------------------------------
    # STEP 2: Controlled INP Edit (E: 210000 -> 200000 MPa) & Authentic Solve
    # -------------------------------------------------------------------------
    print("\n>>> [STEP 2] Controlled INP Edit (E: 210000 -> 200000 MPa) & Authentic Solve...")
    run_02_id = "run_02_edited"
    ops = [{"category": "material", "target": "STEEL", "keyword": "*ELASTIC", "values": [[200000.0, 0.3]]}]
    res_02 = edit_and_solve_user_inp(
        executor=executor,
        inp_path=base_inp_path,
        operations=ops,
        target_filename="cantilever_edited.inp",
        job_name="CantileverEditedJob",
        project_context=ctx,
        run_id=run_02_id,
        overwrite=True,
        require_verified_odb=True,
        odb_validator=validator,
    )
    print(f"  Status: {res_02['status']}, RC: {res_02['returncode']}, ODB Valid: {res_02['odb_valid']}")
    assert res_02["status"] == "COMPLETED", f"Step 2 failed: {res_02.get('error')}"
    assert res_02["returncode"] == 0
    assert res_02["odb_valid"] is True
    assert res_02["working_copy_rolled_back"] is False
    assert compute_sha256(base_inp_path) == base_sha256, "Baseline INP mutated during Step 2!"

    edited_inp = Path(res_02["edited_inp_path"])
    assert edited_inp.is_file() and "200000.0" in edited_inp.read_text(encoding="utf-8")

    metrics_02 = extract_beam_metrics(Path(res_02["odb_path"]), executor.resolved_launcher)
    print("  Extracted Edited Metrics:")
    print(f"    Max Deflection: {metrics_02['max_u_mag']:.5f} mm")
    print(f"    Min Tip U2:     {metrics_02['min_u2']:.5f} mm")
    print(f"    Max Stress:     {metrics_02['max_mises']:.2f} MPa")

    u_ratio = metrics_02["max_u_mag"] / metrics_01["max_u_mag"]
    expected_ratio = 210000.0 / 200000.0
    ratio_error_pct = abs(u_ratio - expected_ratio) / expected_ratio * 100.0
    stress_diff_pct = abs(metrics_02["max_mises"] - metrics_01["max_mises"]) / metrics_01["max_mises"] * 100.0
    print("  Physical Verification:")
    print(f"    Theoretical Ratio: {expected_ratio:.6f}, Simulation Ratio: {u_ratio:.6f}, Discrepancy: {ratio_error_pct:.4f}%")
    print(f"    Stress Discrepancy: {stress_diff_pct:.4f}%")
    assert ratio_error_pct < 0.1, f"Deflection ratio discrepancy {ratio_error_pct}% exceeds 0.1%!"
    assert stress_diff_pct < 0.1, f"Stress discrepancy {stress_diff_pct}% exceeds 0.1%!"

    ev2 = ctx.create_run_evidence_dir(run_02_id)
    (ev2 / "evidence.json").write_text(json.dumps({
        "run_id": run_02_id,
        "status": res_02["status"],
        "metrics": metrics_02,
        "u_ratio": u_ratio,
        "expected_ratio": expected_ratio,
        "ratio_error_pct": ratio_error_pct,
        "source_sha256": base_sha256,
        "edited_sha256": compute_sha256(edited_inp),
    }, indent=2), encoding="utf-8")
    summary_report["step_2_controlled_edit"] = {
        "status": "PASS",
        "run_id": run_02_id,
        "metrics": metrics_02,
        "u_ratio": u_ratio,
        "ratio_error_pct": ratio_error_pct,
    }

    # -------------------------------------------------------------------------
    # STEP 3: Failure Injection & Working Copy Rollback
    # -------------------------------------------------------------------------
    print("\n>>> [STEP 3] Injecting Fatal Solver Failure & Verifying Transactional Rollback...")
    run_03_id = "run_03_rollback"
    ops_fail = [{"category": "material", "target": "STEEL", "keyword": "*ELASTIC", "values": [[-210000.0, 0.3]]}]
    target_fail = "cantilever_failed_attempt.inp"
    res_03 = edit_and_solve_user_inp(
        executor=executor,
        inp_path=base_inp_path,
        operations=ops_fail,
        target_filename=target_fail,
        job_name="CantileverFailJob",
        project_context=ctx,
        run_id=run_03_id,
        overwrite=True,
        rollback_on_solver_failure=True,
        require_verified_odb=True,
        odb_validator=validator,
    )
    print(f"  Status: {res_03['status']}, Rolled Back: {res_03['working_copy_rolled_back']}")
    print(f"  Diagnostics: {res_03['error']}")
    assert res_03["status"] == "FAILED", f"Expected FAILED but got {res_03['status']}"
    assert res_03["odb_valid"] is False
    assert res_03["working_copy_rolled_back"] is True
    assert not (ctx.working_dir / target_fail).exists(), "Failed target file was NOT rolled back!"

    solver_scratch = ctx.solver_dir / run_03_id
    assert solver_scratch.is_dir(), "Solver scratch directory was missing!"
    dat_files = list(solver_scratch.glob("*.dat"))
    assert len(dat_files) > 0, "No solver diagnostic .dat files found in scratch!"
    print(f"  Verified: working copy '{target_fail}' rolled back, solver scratch retained ({len(dat_files)} .dat files)")

    ev3 = ctx.create_run_evidence_dir(run_03_id)
    (ev3 / "evidence.json").write_text(json.dumps({
        "run_id": run_03_id,
        "status": res_03["status"],
        "error": res_03["error"],
        "working_copy_rolled_back": True,
    }, indent=2), encoding="utf-8")
    summary_report["step_3_rollback"] = {"status": "PASS", "run_id": run_03_id, "working_copy_rolled_back": True}

    # -------------------------------------------------------------------------
    # FINAL DELIVERY: Manifest and HTML Report
    # -------------------------------------------------------------------------
    print("\n>>> Generating Final Delivery Manifest & HTML Report...")
    manifest = {
        "project": "Cantilever_Live_Verification",
        "project_root": str(project_root),
        "abaqus_version": "Abaqus 2025",
        "all_steps_passed": True,
        "summary": summary_report,
    }
    manifest_path = ctx.delivery_dir / "live_verification_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  Manifest written to: {manifest_path}")

    html_text = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Abaqus 2025 Live Verification Report</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; color: #24292e; max-width: 900px; margin: 40px auto; padding: 0 20px; }}
    h1 {{ color: #0366d6; border-bottom: 1px solid #e1e4e8; padding-bottom: 10px; }}
    .card {{ background: #f6f8fa; border: 1px solid #e1e4e8; border-radius: 6px; padding: 16px; margin-bottom: 20px; }}
    .badge-pass {{ background: #28a745; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    th, td {{ border: 1px solid #e1e4e8; padding: 8px 12px; text-align: left; }}
    th {{ background: #fafbfc; }}
  </style>
</head>
<body>
  <h1>Abaqus 2025 Live Real-Machine Verification Report</h1>
  <div class="card">
    <p><strong>Environment:</strong> Windows (x86_64) | Abaqus 2025 (<code>{launcher}</code>)</p>
    <p><strong>Isolated Project Root:</strong> <code>{project_root}</code> (Strict REQ-ISO-002 Compliance)</p>
    <p><strong>Overall Verification Status:</strong> <span class="badge-pass">ALL CHECKS QUALIFIED (3/3)</span></p>
  </div>
  <h2>1. Baseline Solve (run_01_baseline) <span class="badge-pass">PASS</span></h2>
  <table>
    <tr><th>Parameter</th><th>Value</th></tr>
    <tr><td>Model</td><td>3D Cantilever Beam (100x10x10 mm, 80 C3D8R Elements, 189 Nodes)</td></tr>
    <tr><td>Material (Baseline)</td><td>E = 210000.0 MPa, &nu; = 0.3</td></tr>
    <tr><td>Applied Load</td><td>F_y = -1000.0 N (Tip Shear)</td></tr>
    <tr><td>Max Deflection (U_mag)</td><td><strong>{metrics_01['max_u_mag']:.5f} mm</strong></td></tr>
    <tr><td>Max von Mises Stress</td><td><strong>{metrics_01['max_mises']:.2f} MPa</strong></td></tr>
    <tr><td>ODB Authenticity</td><td>Verified via native odbAccess probe (Frames &gt; 0, Steps: STEP-1)</td></tr>
  </table>
  <h2>2. Controlled INP Edit &amp; Linear Elastic Physics Validation (run_02_edited) <span class="badge-pass">PASS</span></h2>
  <table>
    <tr><th>Parameter</th><th>Baseline</th><th>Edited</th><th>Theoretical Ratio</th><th>Observed Ratio</th><th>Discrepancy</th></tr>
    <tr><td>Young's Modulus (E)</td><td>210000.0 MPa</td><td>200000.0 MPa</td><td>1.050000</td><td>-</td><td>-</td></tr>
    <tr><td>Max Deflection (U_mag)</td><td>{metrics_01['max_u_mag']:.5f} mm</td><td>{metrics_02['max_u_mag']:.5f} mm</td><td>1.050000</td><td><strong>{u_ratio:.6f}</strong></td><td><strong>{ratio_error_pct:.4f}%</strong></td></tr>
    <tr><td>Max Stress</td><td>{metrics_01['max_mises']:.2f} MPa</td><td>{metrics_02['max_mises']:.2f} MPa</td><td>1.000000</td><td><strong>{(metrics_02['max_mises']/metrics_01['max_mises']):.6f}</strong></td><td><strong>{stress_diff_pct:.4f}%</strong></td></tr>
  </table>
  <h2>3. Transactional Rollback on Solver Failure (run_03_rollback) <span class="badge-pass">PASS</span></h2>
  <div class="card">
    <p><strong>Injected Fault:</strong> Negative Young's Modulus (E = -210000.0 MPa)</p>
    <p><strong>Solver Exit Code / Status:</strong> <code>FAILED</code> (ODB validity failed closed)</p>
    <p><strong>Working Copy Rollback:</strong> <code>{target_fail}</code> purged from <code>working/</code>.</p>
    <p><strong>Diagnostic Preservation:</strong> Solver sandbox <code>solver/{run_03_id}/</code> retained with complete <code>.dat</code> logs.</p>
  </div>
</body>
</html>
"""
    # Hand-written HTML has no Agent run record. File a labeled diagnostic
    # draft only; do not create the formal live_test_report.html name.
    from abaqus_ai_agent.reporting.delivery import write_gated_engineering_report
    report_path = ctx.delivery_dir / "live_test_report.html"
    written = write_gated_engineering_report(
        report_path,
        content=html_text,
        allow_diagnostic_draft=True,
    )
    report_path = Path(written["path"])
    print(f"  Diagnostic HTML draft written to: {report_path}")
    print("  Formal live_test_report.html was not written: no Agent run record.")
    print("\n=======================================================================")
    print("  Abaqus 2025 Real-Machine Verification: 100% COMPLETE & QUALIFIED!   ")
    print("=======================================================================")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Abaqus 2025 Live Real-Machine Verification Runner")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT), help="External project workspace")
    parser.add_argument("--launcher", default=DEFAULT_LAUNCHER, help="Abaqus launcher executable")
    args = parser.parse_args()
    run_verification(Path(args.project_root), args.launcher)
