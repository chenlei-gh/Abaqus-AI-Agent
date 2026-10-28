#!/usr/bin/env python3
"""Abaqus 2025 Live Gate Execution & Authoritative Engineering Report Delivery Verification.

Two-phase workflow (pre-solve approval gate):

- Phase A (no approval): the CAE-side ``solve_requirement`` is blocked by the
  pre-solve approval gate. The script emits a facts payload with
  ``summary_card_status == "AWAITING_APPROVAL"``; the host verdict is the
  distinct, honest ``AWAITING_APPROVAL`` -- never PASS, and no solve happens.
- Approve: ``python -m abaqus_ai_agent approve --workdir <workdir> --by <who>``.
- Phase B: re-run with ``--reuse-workdir`` on the same workdir. The gate
  verifies the approved candidate and the solve proceeds.

Verdict contract (computed host-side by :func:`compute_live_gate_verdict`):

- ``PASS`` requires: host process rc == 0, artifacts settled, run identity
  match, task COMPLETED, solver completed, run state accepted, engineering
  status valid, acceptance passed, report filed through the delivery gate,
  and all required artifacts present with hashes.
- ``AWAITING_APPROVAL`` is the explicit blocked state (exit code 2).
- ``DELIVERY_BLOCKED`` means the run succeeded but the formal delivery gate
  refused the report filing (exit code 1, precisely classified).
- ``FAIL`` for everything else (exit code 1).

Anti-stale-run measures: the workdir must be empty unless ``--reuse-workdir``
is passed; every run carries a unique run_id embedded in the facts payload and
the summary filename; artifacts must have mtimes newer than the launch; the
``abaqus.rpy`` fallback only accepts facts whose run_id matches this run.
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
import time
import uuid
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.execution.batch import BatchExecutor, resolve_default_launcher
from abaqus_ai_agent.execution.odb_rendering import verify_image_integrity

FACTS_BEGIN = "AIAgent_LIVE_GATE_FACTS_BEGIN"
FACTS_END = "AIAgent_LIVE_GATE_FACTS_END"

VERDICT_PASS = "PASS"
VERDICT_AWAITING = "AWAITING_APPROVAL"
VERDICT_DELIVERY_BLOCKED = "DELIVERY_BLOCKED"
VERDICT_FAIL = "FAIL"

EXIT_BY_VERDICT = {
    VERDICT_PASS: 0,
    VERDICT_AWAITING: 2,
    VERDICT_DELIVERY_BLOCKED: 1,
    VERDICT_FAIL: 1,
}

# Optional visual assets are verified when present, but the required gate only
# covers the ODB and the filed engineering report.
OPTIONAL_VISUALS = (
    "mesh_discretization.png",
    "mises_stress_hotspot.png",
    "total_displacement.png",
    "deformation_animation.gif",
)

DEFAULT_PROMPT = (
    "Cantilever beam 100mm x 10mm x 10mm, structural steel Q235 "
    "(E=210000MPa, nu=0.3, yield=235MPa). "
    "Boundary condition: the root end face fully fixed (encastre). "
    "Load: 200N downward concentrated force at the free end tip. "
    "Verify that the max von Mises stress does not exceed 1500 MPa. "
    "Compute von Mises stress and displacement, and deliver the "
    "engineering report."
)


def _sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def build_live_gate_cae_script(
    *,
    workdir: Path,
    launcher: str,
    prompt: str,
    job_name: str,
    model_name: str,
    run_id: str,
    completion_sentinel: Optional[Path] = None,
) -> str:
    """Render the CAE-side driver script. Pure function: offline-testable."""
    return """# -*- coding: utf-8 -*-
# Auto-generated CAE Driver Script for Abaqus 2025 Live Report Gate
import sys
_src = %r
if _src not in sys.path:
    sys.path.insert(0, _src)

import json
import os

from abaqus_ai_agent import AbaqusAIAgent
from abaqus_ai_agent.execution.client import InProcessExecutor
from abaqus_ai_agent.execution.kernel_namespace import KernelNamespace, build_cae_seed
from abaqus_ai_agent.paths import ExternalProjectContext

_NS = KernelNamespace(seed_code=build_cae_seed())

def _run_code(code):
    return _NS.execute(code, '<AIAgent-LiveReportGate>')

class CAEExecutor(InProcessExecutor):
    def __init__(self, runner, launcher=%r):
        super(CAEExecutor, self).__init__(runner)
        self.launcher = launcher

    def inspect_odb(self, path):
        from odbAccess import openOdb
        odb = openOdb(path=path, readOnly=True)
        res = {
            'status': 'available',
            'steps': list(odb.steps.keys()),
            'instances': list(odb.rootAssembly.instances.keys()),
            'step_frames': {k: len(v.frames) for k, v in odb.steps.items()},
        }
        odb.close()
        return res

executor = CAEExecutor(_run_code, launcher=%r)
agent = AbaqusAIAgent(executor)

RUN_ID = %r
prompt = %r

# REQ-ISO-002: production artifacts stay inside a customer project structure
# rooted at the tool workdir (outside the repository).
project_ctx = ExternalProjectContext.create(
    project_root=%r,
    project_name='LiveGateProject',
    enforce_outside_repo=True,
)

print('[LiveGate] Executing solve_requirement with require_production=True...')
task_result = None
crash_error = None
try:
    task_result = agent.solve_requirement(
        prompt,
        model_name=%r,
        job_name=%r,
        submit_job=True,
        require_production=True,
        project_context=project_ctx,
        timeout=3600,
    )
except Exception as solve_exc:
    crash_error = f'{solve_exc.__class__.__name__}: {solve_exc}'

if task_result is not None:
    card = task_result.summary_card if getattr(task_result, 'summary_card', None) else {}
    run_obj = task_result.run
    run_state = getattr(run_obj, 'state', None)
else:
    card = {}
    run_obj = None
    run_state = None

# File the report only through the shared delivery gate; the outcome is
# recorded honestly and the verdict is computed host-side, never asserted here.
from abaqus_ai_agent.reporting.delivery import write_gated_engineering_report
from abaqus_ai_agent.contracts.provenance import build_delivery_record
target_dir = %r
issued = getattr(run_obj, 'provenance', None) if run_obj else None
odb_sha = getattr(issued, 'output_hash', None) if issued is not None else None
# The bare provenance object is not a delivery record: the file gate requires
# the same acceptance verdict and condition-fidelity audit the deterministic
# pipeline verified. Rebuild the identical record from the run itself; nothing
# is fabricated here, and missing inputs must fail the gate rather than be
# defaulted.
_acceptance_obj = getattr(run_obj, 'acceptance', None) if run_obj else None
if _acceptance_obj is None and run_obj is not None:
    for _ev in getattr(getattr(run_obj, 'evidence', None), 'entries', ()) or ():
        if getattr(_ev, 'kind', None) == 'acceptance':
            _acceptance_obj = getattr(_ev, 'value', None)
            break
_fidelity_obj = (getattr(run_obj, 'metadata', None) or {}).get('condition_fidelity') if run_obj else None
record_payload = build_delivery_record(
    provenance=issued,
    odb_path=getattr(run_obj, 'odb_path', None) if run_obj else None,
    odb_sha256=odb_sha,
    acceptance=_acceptance_obj,
    condition_fidelity=_fidelity_obj,
)
delivery = {'attempted': False, 'filed': False, 'error': None}
if task_result is not None and task_result.report_html:
    delivery['attempted'] = True
    try:
        write_gated_engineering_report(
            os.path.join(target_dir, 'engineering_report.html'),
            content=task_result.report_html,
            record=record_payload,
            odb_sha256=odb_sha,
            allow_diagnostic_draft=False,
        )
        delivery['filed'] = os.path.isfile(os.path.join(target_dir, 'engineering_report.html'))
    except Exception as d_exc:
        delivery['error'] = f'{d_exc.__class__.__name__}: {d_exc}'

if task_result is None:
    facts = {
        'run_id': RUN_ID,
        'task_status': 'CRASHED',
        'summary_card_status': None,
        'candidate_id': None,
        'execution_manifest_hash': None,
        'approval_workdir': None,
        'engineering_status': None,
        'run_state': None,
        'acceptance_passed': False,
        'solver_completed': False,
        'odb_path': None,
        'errors': [crash_error],
        'delivery': {'attempted': False, 'filed': False, 'error': None},
        'report_html_length': 0,
        'metrics': {},
        'has_delivery_card': False,
        'delivery_card': None,
    }
else:
    facts = {
    'run_id': RUN_ID,
    'task_status': task_result.status.value if hasattr(task_result.status, 'value') else str(task_result.status),
    'summary_card_status': card.get('status'),
    'approval_workdir': card.get('workdir'),
    'candidate_id': card.get('candidate_id'),
    'execution_manifest_hash': card.get('execution_manifest_hash'),
    'engineering_status': getattr(run_obj, 'engineering_status', None),
    'run_state': run_state.value if hasattr(run_state, 'value') else (str(run_state) if run_state is not None else None),
    'acceptance_passed': bool(getattr(run_obj, 'acceptance_passed', False)) if run_obj else False,
    'solver_completed': bool(getattr(run_obj, 'solver_completed', False)) if run_obj else False,
    'odb_path': getattr(run_obj, 'odb_path', None) if run_obj else None,
    'errors': [str(e) for e in task_result.errors] if task_result.errors else [],
    'delivery': delivery,
    'report_html_length': len(task_result.report_html) if task_result.report_html else 0,
    'metrics': card.get('metrics', {}),
    'has_delivery_card': bool(card.get('delivery_card')),
    'delivery_card': card.get('delivery_card'),
}

ri = task_result.result_intelligence if task_result is not None else None
if ri is not None:
    facts['hotspot_count'] = len(ri.hotspots)
    facts['hotspots'] = [h.to_dict() for h in ri.hotspots]
    facts['curve_count'] = len(ri.curves)
    facts['curves'] = [c.to_dict() for c in ri.curves]
    facts['figure_paths'] = list(ri.figure_paths)
    if ri.derived_metrics:
        facts['derived_metrics'] = ri.derived_metrics.to_dict()

summary_path = os.path.join(target_dir, f'live_gate_summary_{RUN_ID}.json')
with open(summary_path, 'w', encoding='utf-8') as fh:
    json.dump(facts, fh, indent=2, default=str)

print('[LiveGate] Facts written: ' + summary_path)
print('AIAgent_LIVE_GATE_FACTS_BEGIN')
print(json.dumps(facts, default=str, sort_keys=True))
print('AIAgent_LIVE_GATE_FACTS_END')

# Kernel-side completion evidence. Solve exceptions are caught above, so this
# statement is reached on every path that produced a verdict; the host waits
# for it instead of trusting the launcher's exit code.
if %r:
    _ai_done = open(%r, 'w')
    _ai_done.write('completed')
    _ai_done.close()
""" % (
        str(SRC),
        launcher,
        launcher,
        run_id,
        prompt,
        str(workdir),
        model_name,
        job_name,
        str(workdir),
        str(completion_sentinel) if completion_sentinel else "",
        str(completion_sentinel) if completion_sentinel else "",
    )


def extract_facts(text: str, *, expected_run_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parse the facts payload between markers; reject foreign run identities."""
    if FACTS_BEGIN not in text or FACTS_END not in text:
        return None
    payload = text.split(FACTS_BEGIN, 1)[1].split(FACTS_END, 1)[0].strip()
    try:
        facts = json.loads(payload)
    except Exception:
        return None
    if expected_run_id is not None and facts.get("run_id") != expected_run_id:
        return None
    return facts


def compute_live_gate_verdict(
    facts: Optional[Dict[str, Any]],
    *,
    process_returncode: Optional[int],
    process_settled: Optional[bool],
    artifacts: Dict[str, Any],
    expected_run_id: str,
    required_artifacts: List[str],
    completion_evidence: Optional[str] = None,
) -> Dict[str, Any]:
    """Pure verdict function. PASS requires every gate; rejection is explicit.

    Host-failure precedence: an approval-pending (AWAITING_APPROVAL)
    classification is only credible when the host process itself terminated
    cleanly; a crashed or unsettled host can never be re-labelled as a
    routine approval wait.

    Physics sanity (fail-closed): a completed solve must produce a positive
    peak von Mises stress, and static equilibrium must close via the
    engineering force-balance evidence (applied load vs reaction resultant
    computed from per-node RF component sums). Zero-stress or unbalanced
    results are symptomatic of a wrongly built model (e.g. the load applied
    on the constrained face) and must never pass, even if every procedural
    gate succeeded.
    """
    reasons: List[str] = []
    host_ok = True
    if process_returncode != 0:
        reasons.append(f"host process return_code={process_returncode}")
        host_ok = False
    if process_settled is not True:
        reasons.append("artifacts not settled after launcher exit")
        host_ok = False
    # ``None`` means the caller did not supervise script completion (legacy
    # callers). When it is supervised, anything other than the kernel's own
    # end-of-script record means the script may still be running, in which case
    # neither the facts nor the artifacts are terminal evidence.
    if completion_evidence is not None and completion_evidence != "script_completed":
        reasons.append(
            "no kernel-side script-completion evidence (completion_evidence=%r)"
            % (completion_evidence,))
        host_ok = False
    if not facts:
        reasons.append("no facts payload emitted by the CAE script")
        return {"verdict": VERDICT_FAIL, "reasons": reasons}
    if facts.get("run_id") != expected_run_id:
        return {
            "verdict": VERDICT_FAIL,
            "reasons": reasons + ["run identity mismatch: facts do not belong to this run"],
        }
    if facts.get("task_status") == "BLOCKED" and facts.get("summary_card_status") == VERDICT_AWAITING:
        if host_ok:
            return {
                "verdict": VERDICT_AWAITING,
                "reasons": [],
                "candidate_id": facts.get("candidate_id"),
                "execution_manifest_hash": facts.get("execution_manifest_hash"),
                "approval_workdir": facts.get("approval_workdir"),
            }
        return {
            "verdict": VERDICT_FAIL,
            "reasons": reasons + [
                "approval-pending classification refused: host process did not terminate cleanly"
            ],
        }

    checks = {
        "task_status==COMPLETED": facts.get("task_status") == "COMPLETED",
        "solver_completed": facts.get("solver_completed") is True,
        "run_state==accepted": str(facts.get("run_state") or "").lower() == "accepted",
        "engineering_status_valid": facts.get("engineering_status") in ("ACCEPTED", "RESULT_VALID"),
        "acceptance_passed": facts.get("acceptance_passed") is True,
        "report_filed": (facts.get("delivery") or {}).get("filed") is True,
    }
    for name, ok in checks.items():
        if not ok:
            reasons.append(f"gate failed: {name}")
    for name in required_artifacts:
        rec = artifacts.get(name) or {}
        if not rec.get("exists") or not rec.get("sha256"):
            reasons.append(f"required artifact missing or unverified: {name}")

    # Physics sanity: only meaningful when every procedural gate passed.
    if not reasons:
        physics_reasons: List[str] = []
        metrics = facts.get("metrics") or {}
        mises = metrics.get("max_mises")
        try:
            mises_val = float(mises)
        except (TypeError, ValueError):
            mises_val = None
        if mises_val is None or mises_val <= 0.0:
            physics_reasons.append(
                f"physics sanity failed: max_mises={mises!r} is missing or non-positive "
                "after a completed solve"
            )
        derived = facts.get("derived_metrics") or {}
        force_balance = derived.get("force_balance") or {}
        if force_balance.get("is_balanced") is not True:
            physics_reasons.append(
                "static force balance not established: applied load and reaction "
                "resultant do not close within tolerance"
            )
        if physics_reasons:
            return {"verdict": VERDICT_FAIL, "reasons": reasons + physics_reasons}

    delivery = facts.get("delivery") or {}
    errors_text = " ".join(str(e) for e in facts.get("errors") or [])
    delivery_blocked = (
        (delivery.get("attempted") and delivery.get("error") and not delivery.get("filed"))
        or "DELIVERY_BLOCKED" in errors_text
    )
    if reasons and delivery_blocked:
        verdict = VERDICT_DELIVERY_BLOCKED
    else:
        verdict = VERDICT_PASS if not reasons else VERDICT_FAIL
    return {"verdict": verdict, "reasons": reasons}


def _prepare_workdir(workdir: Path, *, reuse_workdir: bool) -> None:
    if workdir.exists() and any(workdir.iterdir()) and not reuse_workdir:
        raise RuntimeError(
            f"workdir {workdir} is not empty; refusing to mix artifacts from "
            "another run. Use --reuse-workdir only for an approved phase-B resume."
        )
    workdir.mkdir(parents=True, exist_ok=True)


def run_live_report_gate(
    workdir: Path,
    launcher: str,
    deliverables_dir: Path,
    prompt: Optional[str] = None,
    job_name: Optional[str] = None,
    model_name: Optional[str] = None,
    reuse_workdir: bool = False,
) -> Dict[str, Any]:
    _prepare_workdir(workdir, reuse_workdir=reuse_workdir)
    deliverables_dir.mkdir(parents=True, exist_ok=True)

    run_id = uuid.uuid4().hex[:12]
    job_name = job_name or "Job_Live_Execution"
    model_name = model_name or "Model_Live_Execution"
    nl_prompt = prompt or DEFAULT_PROMPT

    print("=" * 78)
    print("STEP 1: Ingest Engineering Requirement (Configurable Multi-Disciplinary Spec)")
    print("=" * 78)
    print(f"  Run ID:           {run_id}")
    print(f"  Requirement Prompt: '{nl_prompt}'")
    print(f"  Target Model:       {model_name}")
    print(f"  Target Job:         {job_name}")
    print(f"  Working Sandbox:    {workdir}")
    print(f"  Deliverables Dir:   {deliverables_dir}")

    print("\n" + "=" * 78)
    print("STEP 2: Construct Live CAE Driver Script (solve_requirement with production gate)")
    print("=" * 78)

    cae_script_path = workdir / "run_live_gate_script.py"
    sentinel_path = workdir / "live_gate_script_end.flag"
    # A sentinel left by a previous run would be read as this run's evidence.
    if sentinel_path.exists():
        sentinel_path.unlink()
    cae_script_content = build_live_gate_cae_script(
        workdir=workdir,
        launcher=launcher,
        prompt=nl_prompt,
        job_name=job_name,
        model_name=model_name,
        run_id=run_id,
        completion_sentinel=sentinel_path,
    )
    cae_script_path.write_text(cae_script_content, encoding="utf-8")
    print(f"  CAE script written to: {cae_script_path}")

    print("\n" + "=" * 78)
    print("STEP 3: Execute Abaqus 2025 Standard Solver via BatchExecutor")
    print("=" * 78)
    launch_time = time.time()
    batch = BatchExecutor(launcher=launcher, workdir=str(workdir), timeout=3600)
    proc_res = batch.run_nogui(str(cae_script_path), timeout=3600,
                               completion_sentinel=sentinel_path)

    stdout_text = proc_res.stdout or ""
    stderr_text = proc_res.stderr or ""
    print(f"  Abaqus Process exit code: {proc_res.return_code}")
    print(f"  Artifacts settled:        {getattr(proc_res, 'settled', None)}")

    facts = extract_facts(stdout_text + "\n" + stderr_text, expected_run_id=run_id)
    facts_source = "stdout" if facts else None
    if facts is None:
        rpy_file = workdir / "abaqus.rpy"
        if rpy_file.exists() and rpy_file.stat().st_mtime >= launch_time - 1.0:
            facts = extract_facts(
                rpy_file.read_text(encoding="utf-8", errors="ignore"),
                expected_run_id=run_id,
            )
            if facts is not None:
                facts_source = "abaqus.rpy (fresh, run-id matched)"
    if facts is None:
        summary_file = workdir / f"live_gate_summary_{run_id}.json"
        if summary_file.exists() and summary_file.stat().st_mtime >= launch_time - 1.0:
            try:
                candidate_facts = json.loads(summary_file.read_text(encoding="utf-8"))
                if candidate_facts.get("run_id") == run_id:
                    facts = candidate_facts
                    facts_source = "summary file (fresh, run-id matched)"
            except Exception:
                facts = None

    print("\n" + "=" * 78)
    print("STEP 4: Collect, Verify, and Hash Fresh Artifacts (mtime >= launch)")
    print("=" * 78)

    artifacts: Dict[str, Any] = {}

    def _collect(filename: str, *, copy_to_deliverables: bool, explicit_path=None) -> None:
        p = Path(explicit_path) if explicit_path else (workdir / filename)
        try:
            p.resolve().relative_to(workdir.resolve())
        except ValueError:
            artifacts[filename] = {"exists": False, "rejected": "outside workdir tree"}
            return
        fresh = (
            p.exists()
            and p.is_file()
            and p.stat().st_size > 0
            and p.stat().st_mtime >= launch_time - 1.0
        )
        if not fresh:
            artifacts[filename] = {"exists": False}
            return
        h = _sha256(p)
        rec = {"sha256": h, "size_bytes": p.stat().st_size, "exists": True}
        artifacts[filename] = rec
        if copy_to_deliverables:
            shutil.copy2(p, deliverables_dir / filename)
        print(f"  [artifact] {filename:<28} size={rec['size_bytes']:>8} B  SHA256={h[:16]}...")

    odb_name = f"{job_name}.odb"
    odb_hint = (facts or {}).get("odb_path")
    _collect(odb_name, copy_to_deliverables=True, explicit_path=odb_hint)
    _collect("engineering_report.html", copy_to_deliverables=True)

    discovered = set(OPTIONAL_VISUALS)
    for ext in ("*.png", "*.gif"):
        for img_file in workdir.glob(ext):
            discovered.add(img_file.name)
    for v_name in sorted(discovered):
        p = workdir / v_name
        if not (p.exists() and p.stat().st_size > 0 and p.stat().st_mtime >= launch_time - 1.0):
            continue
        try:
            verify_image_integrity(p)
        except Exception as v_err:
            artifacts[v_name] = {"exists": True, "verified": False, "integrity_error": str(v_err)}
            print(f"  [Warning] Asset {v_name} integrity check failed: {v_err} (recorded, not fatal)")
            continue
        _collect(v_name, copy_to_deliverables=True)
        artifacts[v_name]["verified"] = True

    required = [odb_name, "engineering_report.html"]
    verdict = compute_live_gate_verdict(
        facts,
        process_returncode=proc_res.return_code,
        process_settled=getattr(proc_res, "settled", None),
        artifacts=artifacts,
        expected_run_id=run_id,
        required_artifacts=required,
        completion_evidence=getattr(proc_res, "completion_evidence", None),
    )

    manifest = {
        "schema_version": "live_report_gate_v2",
        "timestamp": datetime.datetime.now().isoformat(),
        "run_id": run_id,
        "launcher": launcher,
        "solver_version": "Abaqus 2025 Standard Implicit",
        "nl_prompt": nl_prompt,
        "model_name": model_name,
        "job_name": job_name,
        "facts_source": facts_source,
        "process": {
            "return_code": proc_res.return_code,
            "settled": getattr(proc_res, "settled", None),
            "settle_note": getattr(proc_res, "settle_note", None),
            "completion_evidence": getattr(proc_res, "completion_evidence", None),
            "stdout_tail": stdout_text[-4000:],
            "stderr_tail": stderr_text[-4000:],
        },
        "facts": facts,
        "verdict": verdict,
        "artifacts": artifacts,
        "required_artifacts": required,
    }
    sandbox_manifest = workdir / f"live_gate_manifest_{run_id}.json"
    with open(sandbox_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)

    if verdict["verdict"] != VERDICT_PASS and any(deliverables_dir.iterdir()):
        # A non-PASS run must not leave deliverables behind that could be
        # mistaken for an accepted delivery.
        for item in deliverables_dir.iterdir():
            if item.is_file() and item.stat().st_mtime >= launch_time - 1.0:
                item.unlink()
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
    parser.add_argument(
        "--reuse-workdir",
        action="store_true",
        help="Allow a non-empty workdir (only for an approved phase-B resume)",
    )
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

    try:
        manifest = run_live_report_gate(
            workdir=workdir,
            launcher=launcher,
            deliverables_dir=deliverables_dir,
            prompt=args.prompt,
            job_name=args.job_name,
            model_name=args.model_name,
            reuse_workdir=args.reuse_workdir,
        )
    except Exception as exc:
        print(f"\n[Audit FAIL] {exc.__class__.__name__}: {exc}")
        sys.exit(1)

    facts = manifest.get("facts") or {}
    verdict = manifest.get("verdict") or {}
    metrics = facts.get("metrics", {}) or {}
    dm = facts.get("derived_metrics", {}) or {}
    artifacts = manifest.get("artifacts", {})

    print("\n" + "=" * 78)
    print("LIVE VERIFICATION CONCLUSION & ACCREDITATION AUDIT")
    print("=" * 78)
    print(f"  Run ID:                        {manifest.get('run_id')}")
    print(f"  Task Status:                   {facts.get('task_status')}")
    print(f"  Summary Card Status:           {facts.get('summary_card_status')}")
    print(f"  Engineering Status:            {facts.get('engineering_status')}")
    print(f"  Acceptance Passed:             {facts.get('acceptance_passed')}")
    print(f"  Has Delivery Card:             {facts.get('has_delivery_card')}")
    print(f"  Report HTML Size:              {artifacts.get('engineering_report.html', {}).get('size_bytes', 0)} B")
    if metrics:
        print(f"  Extracted Metrics:             {metrics}")
    if dm:
        fb = dm.get("force_balance", {})
        if fb:
            print(f"  Reaction Force Balance:        Applied={fb.get('applied_magnitude')} N, Error={fb.get('balance_error_percent', 0):.6f}%")
        sf = dm.get("safety_factor", {})
        if sf:
            print(f"  Derived Safety Factor (FoS):   {sf.get('factor_of_safety')} (Yield: {sf.get('yield_strength')} MPa)")

    verdict_name = verdict.get("verdict", VERDICT_FAIL)
    reasons = verdict.get("reasons") or []
    if verdict_name == VERDICT_PASS:
        print("\n[Audit PASS] All gates satisfied: process terminal state, acceptance, delivery, artifacts.")
    elif verdict_name == VERDICT_AWAITING:
        print("\n[Audit AWAITING_APPROVAL] Pre-solve approval gate blocked submission (as designed).")
        print(f"  Candidate: {verdict.get('candidate_id')}")
        approve_dir = verdict.get("approval_workdir") or str(workdir)
        print(f"  Approve with: python -m abaqus_ai_agent approve --workdir {approve_dir} --by <name>")
        print("  Then re-run this tool with --reuse-workdir on the same workdir.")
    else:
        print(f"\n[Audit {verdict_name}] Gates not satisfied:")
        for reason in reasons:
            print(f"  - {reason}")
    sys.exit(EXIT_BY_VERDICT.get(verdict_name, 1))


if __name__ == "__main__":
    main()
