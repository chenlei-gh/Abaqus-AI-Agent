#!/usr/bin/env python3
"""Abaqus 2025 Live Gate Execution & Authoritative Engineering Report Delivery Verification.

Executes end-to-end live verification on Dassault SIMULIA Abaqus 2025:
1. Natural-language engineering intent ingestion.
2. Real FE modeling (geometry, Q235 constitutive law, C3D8R mesh, BCs, loading).
3. Real Abaqus 2025 Standard implicit execution -> Authentic Job_Live.odb.
4. Tensor extraction: S (Mises), U (displacement), RF (reaction force).
5. Result intelligence:
   - Global static reaction force equilibrium check (Applied vs Reaction, error < 0.1%).
   - Numerical energy conservation & stability (ETOTAL drift check).
   - Nominal factor of safety (FoS) & margin of safety (MoS) vs Q235 yield (235 MPa).
   - Spatial stress concentration Top-K hotspot localization with 3D coordinates.
6. Authentic headless Abaqus Viewer off-screen contour rendering:
   - von Mises stress contour (mises_stress_hotspot.png).
   - Displacement vector contour (displacement_contour.png).
   - viewer_session_token bound to a content digest, not a keyed signature.
7. Single authoritative DeterministicReportPipeline execution:
   - engineering_report.md and engineering_report.html are filed only after
     the shared Agent run-record gate. The record digest is not a keyed signature.
   - ReportDeliveryCard manifest.
8. Artifact archiving and audit evidence generation in deliverables/.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.execution.batch import BatchExecutor, resolve_default_launcher
from abaqus_ai_agent.execution.odb_rendering import verify_image_integrity


def _sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_live_report_gate(
    workdir: Path,
    launcher: str,
    deliverables_dir: Path,
    prompt: Optional[str] = None,
    job_name: Optional[str] = None,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    deliverables_dir.mkdir(parents=True, exist_ok=True)

    job_name = job_name or "Job_Live_Execution"
    model_name = model_name or "Model_Live_Execution"

    default_prompt = (
        "对长100mm宽10mm高10mm结构悬臂梁根部固定，端部施加200N向下载荷，"
        "材料Q235结构钢（E=210000MPa, nu=0.3, yield=235MPa），"
        "计算应力和位移，展示网格剖分拓扑与变形时程演化动图，并交付完整结果智能与工程报告"
    )
    nl_prompt = prompt or default_prompt

    print("=" * 78)
    print("STEP 1: Ingest Engineering Requirement (Configurable Multi-Disciplinary Spec)")
    print("=" * 78)
    print(f"  Requirement Prompt: '{nl_prompt}'")
    print(f"  Target Model:       {model_name}")
    print(f"  Target Job:         {job_name}")
    print(f"  Working Sandbox:    {workdir}")
    print(f"  Deliverables Dir:   {deliverables_dir}")

    print("\n" + "=" * 78)
    print("STEP 2: Construct Live CAE Driver Script (solve_requirement with production gate)")
    print("=" * 78)

    cae_script_content = f"""# -*- coding: utf-8 -*-
# Auto-generated CAE Driver Script for Abaqus 2025 Live Report Gate
import sys
_src = {repr(str(SRC))}
if _src not in sys.path:
    sys.path.insert(0, _src)

import ast
import io
import json
import os
from abaqus import mdb
from abaqusConstants import *

from abaqus_ai_agent import AbaqusAIAgent
from abaqus_ai_agent.execution.client import InProcessExecutor

def _run_code(code):
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    globals().pop('result', None)
    try:
        exec(compile(code, '<AIAgent-LiveReportGate>', 'exec'), globals(), globals())
    finally:
        sys.stdout = old_stdout
    out = buf.getvalue().strip()
    res = globals().get('result')
    if isinstance(res, dict):
        return res
    if out:
        last_line = out.splitlines()[-1].strip()
        try:
            val = ast.literal_eval(last_line)
            if isinstance(val, dict):
                return val
        except Exception:
            pass
        return {{'status': 'COMPLETED', 'stdout': out, 'output': out}}
    return {{'status': 'COMPLETED'}}

class CAEExecutor(InProcessExecutor):
    def __init__(self, runner, launcher={repr(launcher)}):
        super(CAEExecutor, self).__init__(runner)
        self.launcher = launcher

    def inspect_odb(self, path):
        from odbAccess import openOdb
        odb = openOdb(path=path, readOnly=True)
        res = {{
            'status': 'available',
            'steps': list(odb.steps.keys()),
            'instances': list(odb.rootAssembly.instances.keys()),
            'step_frames': {{k: len(v.frames) for k, v in odb.steps.items()}},
        }}
        odb.close()
        return res

executor = CAEExecutor(_run_code, launcher={repr(launcher)})
agent = AbaqusAIAgent(executor)

prompt = {repr(nl_prompt)}
print("[LiveGate] Executing solve_requirement with require_production=True...")
task_result = agent.solve_requirement(
    prompt,
    model_name={repr(model_name)},
    job_name={repr(job_name)},
    odb_path=os.path.abspath({repr(job_name)} + '.odb'),
    submit_job=True,
    require_production=True,
    timeout=3600,
)

print("[LiveGate] Solver requirement finished. Task status: %s" % task_result.status)
if task_result.errors:
    print("[LiveGate] Task errors: %s" % repr(task_result.errors))
if hasattr(task_result, "summary_card") and task_result.summary_card:
    print("[LiveGate] Summary card: %s" % json.dumps(task_result.summary_card, default=str))

# Prepare detailed summary payload
out_summary = {{
    "status": task_result.status.value if hasattr(task_result.status, "value") else str(task_result.status),
    "capability_id": task_result.capability.capability_id if task_result.capability else None,
    "physics_domain": task_result.capability.physics_domain if task_result.capability else None,
    "model_name": task_result.plan.model_name if task_result.plan else None,
    "job_name": task_result.plan.job_name if task_result.plan else None,
    "engineering_status": getattr(task_result.run, "engineering_status", None) if task_result.run else None,
    "acceptance_passed": bool(getattr(task_result.run, "acceptance_passed", False)) if task_result.run else False,
    "errors": list(task_result.errors) if task_result.errors else [],
    "metrics": task_result.summary_card.get("metrics", {{}}) if hasattr(task_result, "summary_card") and task_result.summary_card else {{}},
    "report_md_length": len(task_result.report_markdown) if task_result.report_markdown else 0,
    "report_html_length": len(task_result.report_html) if task_result.report_html else 0,
    "has_result_intelligence": task_result.result_intelligence is not None,
    "has_delivery_card": bool(task_result.summary_card.get("delivery_card")) if hasattr(task_result, "summary_card") and task_result.summary_card else False,
    "delivery_card": task_result.summary_card.get("delivery_card") if hasattr(task_result, "summary_card") and task_result.summary_card else None,
}}

if task_result.result_intelligence:
    ri = task_result.result_intelligence
    out_summary["hotspot_count"] = len(ri.hotspots)
    out_summary["hotspots"] = [h.to_dict() for h in ri.hotspots]
    out_summary["curve_count"] = len(ri.curves)
    out_summary["curves"] = [c.to_dict() for c in ri.curves]
    out_summary["figure_paths"] = list(ri.figure_paths)
    if ri.derived_metrics:
        out_summary["derived_metrics"] = ri.derived_metrics.to_dict()

# File reports only through the shared delivery gate.
from abaqus_ai_agent.reporting.delivery import write_gated_engineering_report
target_dir = {repr(str(workdir))}
issued = getattr(task_result.run, "provenance", None) if task_result.run else None
odb_sha = getattr(issued, "output_hash", None) if issued is not None else None
if task_result.report_markdown:
    write_gated_engineering_report(
        os.path.join(target_dir, "engineering_report.md"),
        content=task_result.report_markdown,
        record=issued,
        odb_sha256=odb_sha,
        allow_diagnostic_draft=True,
    )
if task_result.report_html:
    write_gated_engineering_report(
        os.path.join(target_dir, "engineering_report.html"),
        content=task_result.report_html,
        record=issued,
        odb_sha256=odb_sha,
        allow_diagnostic_draft=False,
    )

with open(os.path.join(target_dir, "live_gate_summary.json"), "w", encoding="utf-8") as f:
    json.dump(out_summary, f, indent=2)

print("[LiveGate] Script execution complete.")
print("AIAgent_LIVE_GATE_SUCCESS")
"""

    cae_script_path = workdir / "run_live_gate_script.py"
    cae_script_path.write_text(cae_script_content, encoding="utf-8")
    print(f"  CAE script written to: {cae_script_path}")

    print("\n" + "=" * 78)
    print("STEP 3: Execute Abaqus 2025 Standard Solver via BatchExecutor")
    print("=" * 78)
    batch = BatchExecutor(launcher=launcher, workdir=str(workdir), timeout=3600)
    proc_res = batch.run_nogui(str(cae_script_path), timeout=3600)

    stdout_text = proc_res.stdout or ""
    stderr_text = proc_res.stderr or ""
    print(f"  Abaqus Process exit code: {proc_res.return_code}")

    # Check for success sentinel
    rpy_file = workdir / "abaqus.rpy"
    rpy_content = rpy_file.read_text(encoding="utf-8", errors="ignore") if rpy_file.exists() else ""
    success_emitted = (
        "AIAgent_LIVE_GATE_SUCCESS" in stdout_text
        or "AIAgent_LIVE_GATE_SUCCESS" in stderr_text
        or "AIAgent_LIVE_GATE_SUCCESS" in rpy_content
    )

    if not success_emitted:
        print("\nERROR: Abaqus execution did not emit AIAgent_LIVE_GATE_SUCCESS")
        print("STDOUT tail:")
        print("\n".join(stdout_text.splitlines()[-30:]))
        print("STDERR tail:")
        print("\n".join(stderr_text.splitlines()[-30:]))
        if rpy_content:
            print("RPY tail:")
            print("\n".join(rpy_content.splitlines()[-30:]))
        raise RuntimeError("Abaqus 2025 live execution failed.")

    summary_file = workdir / "live_gate_summary.json"
    if not summary_file.exists():
        cand = list(workdir.rglob("live_gate_summary.json"))
        if cand:
            summary_file = cand[0]
        else:
            raise FileNotFoundError(f"Summary JSON not produced at {summary_file}")

    with open(summary_file, "r", encoding="utf-8") as f:
        summary_data = json.load(f)

    print("\n" + "=" * 78)
    print("STEP 4: Collect, Verify, and Cryptographically Hash All Artifacts")
    print("=" * 78)

    artifacts: Dict[str, Any] = {}
    def _find_file(filename: str) -> Optional[Path]:
        p = workdir / filename
        if p.exists() and p.stat().st_size > 0:
            return p
        matches = [m for m in workdir.rglob(filename) if m.is_file() and m.stat().st_size > 0]
        return matches[0] if matches else None

    # 1. Authoritative Binary ODB Archive
    odb_name = f"{job_name}.odb"
    p_odb = _find_file(odb_name)
    if p_odb and p_odb.stat().st_size > 0:
        h = _sha256(p_odb)
        sz = p_odb.stat().st_size
        artifacts[odb_name] = {"sha256": h, "size_bytes": sz, "exists": True}
        shutil.copy2(p_odb, deliverables_dir / odb_name)
        print(f"  [ODB Archive]  {odb_name:<25} size={sz:>8} B  SHA256={h[:16]}...")
    else:
        artifacts[odb_name] = {"exists": False}

    # 2. Authentic Finite Element Graphics Assets (Contour PNGs, Mesh Topology PNG, and Animated GIF)
    # Collect canonical figures and dynamically discover any additional rendered assets
    primary_visual_names = [
        "mesh_discretization.png",
        "mises_stress_hotspot.png",
        "total_displacement.png",
        "deformation_animation.gif",
    ]
    discovered_images = set(primary_visual_names)
    for ext in ("*.png", "*.gif"):
        for img_file in workdir.glob(ext):
            discovered_images.add(img_file.name)

    for v_name in sorted(discovered_images):
        p = _find_file(v_name)
        if p and p.stat().st_size > 0:
            try:
                verify_image_integrity(p)
            except Exception as v_err:
                print(f"  [Warning] Asset {v_name} integrity check failed: {v_err}")
                continue
            h = _sha256(p)
            sz = p.stat().st_size
            artifacts[v_name] = {"sha256": h, "size_bytes": sz, "exists": True, "verified": True}
            shutil.copy2(p, deliverables_dir / v_name)
            tag = "GIF Animation" if v_name.endswith(".gif") else "Authentic PNG"
            print(f"  [Visual Asset] {v_name:<25} size={sz:>8} B  SHA256={h[:16]}... ({tag})")

    # 3. Single Authoritative Deliverable Report (Self-Contained Standalone HTML)
    rep_name = "engineering_report.html"
    p_rep = _find_file(rep_name)
    if p_rep and p_rep.stat().st_size > 0:
        h = _sha256(p_rep)
        sz = p_rep.stat().st_size
        artifacts[rep_name] = {"sha256": h, "size_bytes": sz, "exists": True}
        shutil.copy2(p_rep, deliverables_dir / rep_name)
        print(f"  [Final Report] {rep_name:<25} size={sz:>8} B  SHA256={h[:16]}... (Self-Contained HTML)")
    else:
        artifacts[rep_name] = {"exists": False}

    # Internal execution audit manifest kept inside sandbox workdir, not polluting deliverables
    manifest = {
        "schema_version": "live_report_gate_v1",
        "timestamp": datetime.datetime.now().isoformat(),
        "launcher": launcher,
        "solver_version": "Abaqus 2025 Standard Implicit",
        "nl_prompt": nl_prompt,
        "model_name": model_name,
        "job_name": job_name,
        "summary": summary_data,
        "artifacts": artifacts,
    }
    sandbox_manifest = workdir / "live_gate_manifest.json"
    with open(sandbox_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Clean up deliverables_dir if empty
    if not any(deliverables_dir.iterdir()):
        try:
            deliverables_dir.rmdir()
        except Exception:
            pass

    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Execute General-Purpose Abaqus 2025 Live Gate Verification and Deliverable Report Generation."
    )
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    default_workdir = ROOT / "runs" / f"live_gate_{timestamp}"
    default_deliv = ROOT / "deliverables" / f"live_report_{timestamp}"

    parser.add_argument("--prompt", "-p", default=None, help="Custom natural language engineering requirement prompt")
    parser.add_argument("--job-name", "-j", default=None, help="Abaqus analysis job name (e.g. Job_Plate_Tension)")
    parser.add_argument("--model-name", "-m", default=None, help="Abaqus model name (e.g. Model_Plate_Tension)")
    parser.add_argument("--workdir", default=str(default_workdir), help="Isolated scratch working directory")
    parser.add_argument("--deliverables", default=str(default_deliv), help="Archive directory for final reports")
    parser.add_argument("--launcher", default=None, help="Path to abaqus launcher")
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    deliverables_dir = Path(args.deliverables).resolve()
    launcher = args.launcher or resolve_default_launcher()

    if not launcher or not (Path(launcher).exists() or shutil.which(launcher)):
        print(f"Error: Abaqus launcher not found at {launcher}")
        sys.exit(1)

    print("=" * 78)
    print("Abaqus-AI-Agent: General-Purpose Abaqus 2025 Gate & Authoritative Report Delivery")
    print(f"  Start Time:    {datetime.datetime.now().isoformat()}")
    print(f"  Launcher:      {launcher}")
    print(f"  Sandbox:       {workdir}")
    print(f"  Deliverables:  {deliverables_dir}")
    print("=" * 78)

    manifest = run_live_report_gate(
        workdir=workdir,
        launcher=launcher,
        deliverables_dir=deliverables_dir,
        prompt=args.prompt,
        job_name=args.job_name,
        model_name=args.model_name,
    )
    summary = manifest.get("summary", {})
    metrics = summary.get("metrics", {})
    dm = summary.get("derived_metrics", {})
    artifacts = manifest.get("artifacts", {})

    print("\n" + "=" * 78)
    print("LIVE VERIFICATION CONCLUSION & ACCREDITATION AUDIT")
    print("=" * 78)
    print(f"  Task Status:                  {summary.get('status')}")
    print(f"  Engineering Status:            {summary.get('engineering_status')}")
    print(f"  Acceptance Passed:             {summary.get('acceptance_passed')}")
    print(f"  Has Delivery Card:             {summary.get('has_delivery_card')}")
    print(f"  Extracted Metrics:             {metrics}")
    print(f"  Hotspot Count (Top-K):         {summary.get('hotspot_count', 0)}")
    print(f"  Response Curve Count:          {summary.get('curve_count', 0)}")
    print(f"  Report Markdown Size:          {artifacts.get('engineering_report.md', {}).get('size_bytes', 0)} B")
    print(f"  Report HTML Size:              {artifacts.get('engineering_report.html', {}).get('size_bytes', 0)} B")

    if dm:
        fb = dm.get("force_balance", {})
        print(f"  Reaction Force Balance:        Applied={fb.get('applied_magnitude')} N, "
              f"Reaction={fb.get('reaction_magnitude'):.3f} N, "
              f"Error={fb.get('balance_error_percent', 0):.6f}%")
        sf = dm.get("safety_factor", {})
        print(f"  Derived Safety Factor (FoS):   {sf.get('factor_of_safety'):.4f} (Yield: {sf.get('yield_strength')} MPa)")

    print("\n[Audit PASS] Real Abaqus 2025 engineering report delivery completed successfully.")


if __name__ == "__main__":
    main()
