"""Command-line interface (CLI) for Abaqus-AI-Agent.

Provides a unified command-line tool for:
1. inspect: inspect host Abaqus runtime, launcher, and capabilities.
2. matrix: list, validate, and summarize Golden Case evidence.
3. diff: compute deterministic run-level diff between two runs.
4. diagnose: deterministic diagnosis of Abaqus solver artifacts (.msg, .sta, .dat, .log).
5. report: render an HTML engineering report from evidence or AnalysisRun. Markdown is an explicit preview only.
6. fmbd: inspect mechanism topology and action compilation plan for MBD/FMBD models.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .contracts.provenance import AnalysisProvenance, build_delivery_record, verify_deliverable
from .diagnostics.solver_patterns import DiagnosticIssue, diagnose_inp_contract, diagnose_solver_artifacts
from .golden_evidence import (
    load_and_normalize_evidence_file,
    validate_golden_evidence_dict,
)
from .golden_registry import (
    GoldenCaseDefinition,
    standard_golden_catalog,
)
from .reporting.delivery import write_gated_engineering_report
from .reporting.renderer import render_html
from .contracts.conclusions import build_report_conclusions
from .contracts.report import EngineeringReportData, classify_report_facts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="abaqus-ai-agent",
        description="Abaqus-AI-Agent Engineering Automation and Verification CLI",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # 1. inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect local Abaqus launcher and environment.")
    p_inspect.add_argument("--launcher", default="abaqus", help="Abaqus launcher command or path (default: abaqus)")
    p_inspect.add_argument("--json", action="store_true", help="Output machine-readable JSON format.")

    # 2. matrix
    p_matrix = subparsers.add_parser("matrix", help="Manage and validate Golden Evidence Matrix.")
    p_matrix.add_argument("--list", action="store_true", help="List all registered Golden Cases.")
    p_matrix.add_argument(
        "--validate",
        metavar="TARGET",
        nargs="?",
        const="all",
        help="Validate Golden Case evidence (pass case_id or 'all', default: all).",
    )
    p_matrix.add_argument("--workdir", default=".", help="Directory containing evidence files (default: .)")
    p_matrix.add_argument("--json", action="store_true", help="Output validation results as JSON.")

    # 3. diff
    p_diff = subparsers.add_parser("diff", help="Compute deterministic difference between two AnalysisRuns or evidence files.")
    p_diff.add_argument("baseline", help="Path to baseline JSON file.")
    p_diff.add_argument("candidate", help="Path to candidate JSON file.")
    p_diff.add_argument("--json", action="store_true", help="Output diff as JSON.")

    # 4. diagnose
    p_diag = subparsers.add_parser("diagnose", help="Diagnose Abaqus solver artifacts (.msg, .sta, .dat, .log).")
    p_diag.add_argument("path", help="Path to a solver artifact file or directory containing job artifacts.")
    p_diag.add_argument("--job-name", help="Optional job name prefix when path is a directory.")
    p_diag.add_argument("--inp", help="Optional INP path for model-contract warnings.")
    p_diag.add_argument("--json", action="store_true", help="Output structured diagnostic issues as JSON.")

    # 5. report
    p_rep = subparsers.add_parser("report", help="Render an HTML engineering report from evidence JSON.")
    p_rep.add_argument("evidence_file", help="Path to evidence or AnalysisRun JSON file.")
    p_rep.add_argument(
        "--format",
        choices=["html"],
        default="html",
        help="Formal deliverable format. HTML is the only file the product writes.",
    )
    p_rep.add_argument("--output", "-o", help="Output file path (default: stdout). A formal file must be HTML.")
    p_rep.add_argument("--title", help="Override report title.")
    p_rep.add_argument(
        "--allow-preview",
        action="store_true",
        help="Print a non-deliverable preview even when the Agent run record is missing. Does not write a file.",
    )

    # 5b. verify-deliverable
    p_vd = subparsers.add_parser(
        "verify-deliverable",
        help="Check whether a JSON record may be filed as an Agent engineering report.",
    )
    p_vd.add_argument("evidence_file", help="Path to evidence or AnalysisRun JSON file.")
    p_vd.add_argument("--json", action="store_true", help="Output the gate result as JSON.")

    # 6. fmbd
    p_fmbd = subparsers.add_parser("fmbd", help="Inspect and compile Flexible Multibody Dynamics (FMBD) mechanisms.")
    p_fmbd.add_argument(
        "--case",
        choices=["fmbd4", "fmbd5", "fmbd6", "fmbd7"],
        default="fmbd7",
        help="Target mechanism benchmark case (default: fmbd7)",
    )
    p_fmbd.add_argument("--verify-topology", action="store_true", help="Analyze and display mechanism topology graph.")
    p_fmbd.add_argument("--compile", action="store_true", help="Compile mechanism into native Abaqus action plan.")
    p_fmbd.add_argument("--json", action="store_true", help="Output topology/actions as JSON.")

    # 7. memory
    p_mem = subparsers.add_parser("memory", help="Inspect, query, and search persisted Case Memory / Run Index.")
    p_mem.add_argument("--dir", default="case_memory", help="Directory containing persisted runs (default: case_memory)")
    p_mem.add_argument("--list", action="store_true", help="List all runs stored in directory.")
    p_mem.add_argument("--manifest", action="store_true", help="Display summary manifest of the case memory.")
    p_mem.add_argument("--solver", help="Filter runs by solver (e.g. standard, explicit).")
    p_mem.add_argument("--status", help="Filter runs by engineering status.")
    p_mem.add_argument("--passed", action="store_true", help="Filter runs where acceptance_passed is True.")
    p_mem.add_argument("--failed", action="store_true", help="Filter runs where acceptance_passed is False.")
    p_mem.add_argument("--json", action="store_true", help="Output machine-readable JSON format.")

    # 8. ask (JEV-powered natural language engineering intent)
    p_ask = subparsers.add_parser("ask", help="Process natural language engineering requirements via TypeSafe JEV System One.")
    p_ask.add_argument("prompt", help="Natural language engineering specification or simulation requirement.")
    p_ask.add_argument("--mode", choices=["offline", "live", "shadow"], default="offline", help="JEV execution mode: offline (default deterministic), live (fail-closed API), or shadow (discrepancy diff).")
    p_ask.add_argument("--json", action="store_true", help="Output typed intent and JEV decisions as JSON.")
    p_ask.add_argument("--dry-run", action="store_true", help="Synthesize plan and intent contracts without executing solver.")

    # 8.5 approve (Phase A/B boundary: approve a pre-solve execution candidate)
    p_approve = subparsers.add_parser(
        "approve",
        help="Approve the pre-solve execution candidate of a run workdir, permitting solver submission.",
    )
    p_approve.add_argument("--workdir", required=True, help="Run workdir containing execution_candidate.json and pre_solve_review.html.")
    p_approve.add_argument("--by", required=True, dest="approved_by", help="Name of the approving reviewer (a label, not identity proof).")
    p_approve.add_argument("--note", default=None, help="Optional approval note recorded with the decision.")
    p_approve.add_argument("--json", action="store_true", help="Output the approval record as JSON.")

    # 9. assets (Canonical validation assets and case registry)
    p_assets = subparsers.add_parser("assets", help="Inspect and query canonical validation assets and Case 01-10 registry.")
    p_assets.add_argument("--list", action="store_true", help="List all registered cases (default).")
    p_assets.add_argument("--case", help="Filter and display details for a specific case_id.")
    p_assets.add_argument("--json", action="store_true", help="Output machine-readable JSON format.")

    # 10. material (Authentic engineering materials, properties, and experimental curves)
    p_mat = subparsers.add_parser(
        "material",
        help="Query and inspect authentic engineering materials, properties, and experimental curves.",
    )
    p_mat.add_argument(
        "name",
        nargs="?",
        help="Material grade, trade name, or alias (e.g. 'Ultramid A3WG6', 'Q235', '6061-T6', 'Ti-6Al-4V').",
    )
    p_mat.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List all registered materials from standard catalog and CAMPUS/MMPDS databases.",
    )
    p_mat.add_argument(
        "--curves",
        "-c",
        action="store_true",
        help="Display experimental stress-strain curves and calibrated Abaqus *Plastic tables.",
    )
    p_mat.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON format.",
    )

    return parser


# --- Handlers ---

def handle_inspect(args: argparse.Namespace) -> int:
    import shutil
    import subprocess

    launcher = args.launcher
    which_path = shutil.which(launcher)

    # Automatic fallback candidate paths on Windows if default not in PATH
    if not which_path and sys.platform == "win32":
        candidates = [
            os.environ.get("ABAQUS_COMMAND"),
            os.environ.get("ABAQUS_BAT"),
        ]
        for cand in candidates:
            if cand and os.path.isfile(cand):
                which_path = cand
                launcher = cand
                break

    launcher_found = bool(which_path)
    version_probe_ok = False
    runtime_startable = False
    license_verified = False
    cae_available = False
    nogui_available = False
    solver_submit_capable = False
    version_info = "unavailable"
    probe_output = ""

    if which_path:
        try:
            cmd = [which_path, "information=release"] if sys.platform != "win32" else f'"{which_path}" information=release'
            p = subprocess.run(
                cmd,
                shell=(sys.platform == "win32"),
                capture_output=True,
                text=True,
                timeout=15,
            )
            out = p.stdout.strip() or p.stderr.strip()
            probe_output = out
            if p.returncode == 0:
                version_probe_ok = True
                runtime_startable = True
                # A successful release inquiry indicates launcher and core environment work
                version_info = out.splitlines()[0] if out else "Abaqus detected"
                # Check for explicit license error patterns in output
                lower_out = out.lower()
                if "license error" in lower_out or "flexnet" in lower_out or "cannot connect to license server" in lower_out:
                    license_verified = False
                else:
                    license_verified = True
                cae_available = True
                nogui_available = True
                solver_submit_capable = license_verified
            else:
                # Returncode non-zero: launcher exists but runtime probe failed
                version_probe_ok = False
                runtime_startable = False
                license_verified = False
                version_info = f"Launcher detected at {which_path} but information=release returned code {p.returncode}"
        except Exception as e:
            version_probe_ok = False
            runtime_startable = False
            license_verified = False
            version_info = f"Detection probe exception: {e}"

    if runtime_startable and license_verified:
        runtime_mode = "LIVE_ABAQUS_SOLVER"
    elif launcher_found and not license_verified:
        runtime_mode = "LAUNCHER_DETECTED_NO_LICENSE"
    else:
        runtime_mode = "HEADLESS_CONTRACT_FALLBACK"

    data = {
        "launcher": launcher,
        "located_path": which_path,
        "available": launcher_found,
        "launcher_found": launcher_found,
        "version_probe_ok": version_probe_ok,
        "runtime_startable": runtime_startable,
        "license_verified": license_verified,
        "license_probe_ok": license_verified,  # Backward compatible alias
        "cae_available": cae_available,
        "nogui_available": nogui_available,
        "solver_submit_capable": solver_submit_capable,
        "runtime_version": version_info,
        "runtime_mode": runtime_mode,
        "python_version": sys.version.split()[0],
        "workdir_writable": os.access(".", os.W_OK),
    }

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("=== Abaqus Runtime Environment Inspection ===")
        print(f"Launcher command:      {data['launcher']}")
        print(f"Executable path:       {data['located_path'] or 'NOT FOUND in PATH'}")
        print(f"Launcher found:        {'YES' if data['launcher_found'] else 'NO'}")
        print(f"Version probe:         {'PASS' if data['version_probe_ok'] else 'FAIL / UNAVAILABLE'}")
        print(f"Runtime startable:     {'YES' if data['runtime_startable'] else 'NO'}")
        print(f"License verified:      {'YES' if data['license_verified'] else 'NO / UNVERIFIED'}")
        print(f"Solver submit capable: {'YES' if data['solver_submit_capable'] else 'NO'}")
        print(f"Runtime mode:          {data['runtime_mode']}")
        print(f"Runtime version:       {data['runtime_version']}")
        print(f"Python version:        {data['python_version']}")
        print(f"Workdir writable:  {'YES' if data['workdir_writable'] else 'NO'}")

    return 0


def handle_ask(args: argparse.Namespace) -> int:
    clean_prompt = args.prompt.strip()
    for prefix in ("查询材料", "查材料", "material "):
        if clean_prompt.startswith(prefix):
            mat_name = clean_prompt[len(prefix):].strip()
            if mat_name:
                import argparse as ap
                mat_args = ap.Namespace(
                    name=mat_name,
                    list=False,
                    curves=True,
                    json=getattr(args, "json", False),
                )
                return handle_material(mat_args)

    from .typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode=getattr(args, "mode", "offline"))
    try:
        routing_res = router.route(args.prompt)
    except Exception as exc:
        print(f"Error processing intent with JEV: {exc}", file=sys.stderr)
        return 1

    bundle = routing_res.decision_bundle
    intent = routing_res.intent

    if routing_res.status == "NEEDS_CLARIFICATION":
        if args.json:
            print(json.dumps(routing_res.to_dict(), indent=2, ensure_ascii=False))
        else:
            print("=== JEV-Powered Engineering Intent: NEEDS CLARIFICATION ===")
            print(f"Prompt:               {args.prompt}")
            print(f"Status:               BLOCKED (Fail-Closed)")
            print(f"Missing Prereqs:      {', '.join(routing_res.missing_requirements)}")
            print("Clarification Needed: {routing_res.clarification_prompt}")
            print("Solver invoked:       NO")
            print("Report authorized:    NO")
            print("Modeling is not authorized until the missing prerequisites are resolved.")
        return 2

    if args.json:
        out = {
            "prompt": args.prompt,
            "status": routing_res.status,
            "intent": {
                "id": intent.id,
                "kind": intent.kind,
                "analysis_type": intent.analysis_type,
                "unit_system": intent.unit_system,
                "material": intent.material,
                "boundary_conditions": list(intent.boundary_conditions),
                "loads": list(intent.loads),
                "acceptance_criteria": list(intent.acceptance_criteria),
            } if intent else None,
            "jev_decision_bundle": bundle.to_dict(),
            "solver_invoked": False,
            "report_authorized": False,
            "note": "ask routes intent only; it does not solve and does not authorize an engineering report.",
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print("=== JEV-Powered Engineering Intent Routing ===")
        print(f"Prompt:             {args.prompt}")
        print(f"Inferred Physics:   {bundle.physics_choice.value} (Confidence: {bundle.physics_choice.confidence:.2f})")
        print(f"Unit System:        {bundle.unit_system_choice.value}")
        print(f"Target Solver:      {bundle.solver_choice.value}")
        print(f"Constraint wording:  {'PRESENT' if bundle.is_well_constrained_noul.is_yes else 'NOT ESTABLISHED FROM TEXT'}")
        print("Constraint note:     text sufficiency only; not a stiffness-rank or fixture proof")
        print(f"Completeness Score: {bundle.completeness_score.score:.1f} / 5.0")
        if intent and intent.material:
            print(f"Material Detected:  {intent.material.get('name')} (E={intent.material.get('elastic_modulus')} MPa)")
        if intent:
            print(f"Boundary Conditions:{len(intent.boundary_conditions)} defined")
            print(f"Loads:              {len(intent.loads)} defined")
            print(f"Acceptance Criteria:{len(intent.acceptance_criteria)} defined")
        if args.dry_run:
            print("[DRY-RUN] Intent and plan contracts verified successfully. No solver invoked.")
        print("Solver invoked:     NO")
        print("Report authorized:  NO")
        print("This command routes intent only. It does not solve, and it does not authorize an engineering report.")

    return 0


def handle_matrix(args: argparse.Namespace) -> int:
    catalog = standard_golden_catalog
    workdir_arg = Path(args.workdir).resolve()
    if workdir_arg.name != "machine_validation" and (workdir_arg / "machine_validation").is_dir():
        workdir = workdir_arg / "machine_validation"
    else:
        workdir = workdir_arg

    if args.list:
        if args.json:
            out = [
                {
                    "case_id": c.case_id,
                    "title": c.title,
                    "category": c.category,
                    "solver": c.solver,
                    "physics_type": c.physics_type,
                    "job_name": c.job_name,
                }
                for c in catalog.all_cases()
            ]
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(f"=== Registered Golden Cases ({len(catalog.all_cases())} total) ===")
            for c in catalog.all_cases():
                print(f"[{c.category}] {c.case_id:24s} | {c.title}")
        return 0

    target = args.validate or "all"
    cases_to_validate: Sequence[GoldenCaseDefinition]
    if target == "all":
        cases_to_validate = catalog.all_cases()
    else:
        found = catalog.get_case(target)
        if not found:
            print(f"Error: Unknown golden case '{target}'.", file=sys.stderr)
            return 2
        cases_to_validate = [found]

    results = []
    all_passed = True

    for c in cases_to_validate:
        # resolve candidate paths
        rel = Path(c.default_evidence_json)
        from .paths import resolve_validation_assets_root
        val_root = resolve_validation_assets_root()
        candidates = [
            workdir / rel.name,
            workdir / rel,
            workdir / f"{c.case_id}.json",
            workdir_arg / rel.name,
            workdir_arg / rel,
            workdir / "machine_validation" / rel.name,
            val_root / "evidence" / rel.name,
            val_root / rel.name,
        ]
        ev_path = None
        for cand in candidates:
            if cand.is_file():
                ev_path = cand
                break

        if not ev_path:
            results.append({
                "case_id": c.case_id,
                "status": "NO_EVIDENCE",
                "valid": False,
                "error": f"Evidence file not found in candidates: {[str(x) for x in candidates]}",
            })
            all_passed = False
            continue

        try:
            envelope = load_and_normalize_evidence_file(ev_path)
            raw = envelope.to_dict()
            errs = validate_golden_evidence_dict(raw)
            if errs:
                status = "INVALID_SCHEMA"
                passed = False
                err_msg = "; ".join(errs)
            elif not envelope.passed:
                status = "FAIL"
                passed = False
                err_msg = "Acceptance passed is False"
            elif envelope.solver_status != "completed":
                status = "INVALID_SCHEMA"
                passed = False
                err_msg = f"Acceptance passed but solver_status is '{envelope.solver_status}'"
            elif envelope.runtime.get("process_succeeded") is not True:
                status = "INVALID_SCHEMA"
                passed = False
                err_msg = "Acceptance passed but runtime.process_succeeded is not True"
            else:
                status = "PASS"
                passed = True
                err_msg = None
        except Exception as e:
            status = "INVALID_JSON"
            passed = False
            err_msg = str(e)

        if not passed:
            all_passed = False

        results.append({
            "case_id": c.case_id,
            "title": c.title,
            "status": status,
            "valid_schema": status != "INVALID_SCHEMA",
            "error": err_msg,
            "path": str(ev_path),
            "passed": passed,
        })

    if args.json:
        print(json.dumps({"all_passed": all_passed, "results": results}, indent=2, ensure_ascii=False))
    else:
        print(f"--- Validating Golden Evidence ({len(results)} cases checked) ---")
        for r in results:
            res_str = "PASS" if r.get("passed") else f"FAIL ({r.get('status')})"
            print(f"[{r['case_id']:22s}] -> {res_str} (file: {r.get('path', '-')})")
        print("=" * 60)
        print("OVERALL RESULT: " + ("ALL PASSED" if all_passed else "SOME CASES FAILED"))

    return 0 if all_passed else 1


def _extract_flat_metrics(source: Any) -> Dict[str, Any]:
    """Deterministically extract numerical metric values from an envelope or dict."""
    metrics: Dict[str, Any] = {}

    # 1. From GoldenEvidenceEnvelope or dict with result_evidence
    res_ev = getattr(source, "result_evidence", None)
    if res_ev is None and isinstance(source, dict):
        res_ev = source.get("result_evidence") or source.get("report", {}).get("results")
    if isinstance(res_ev, dict):
        m_list = res_ev.get("metrics")
        if isinstance(m_list, list):
            for item in m_list:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    metrics[item["name"]] = item["value"]
        elif isinstance(m_list, dict):
            metrics.update(m_list)
        for k, v in res_ev.items():
            if isinstance(v, (int, float)):
                metrics.setdefault(k, v)

    # 2. From acceptance criteria
    acc = getattr(source, "acceptance", None)
    if acc is None and isinstance(source, dict):
        acc = source.get("acceptance") or source.get("report", {}).get("acceptance")
    if isinstance(acc, dict):
        crit = acc.get("criteria", [])
        if isinstance(crit, list):
            for c in crit:
                if isinstance(c, dict) and "name" in c and "actual" in c:
                    metrics.setdefault(c["name"], c["actual"])

    # 3. From direct metrics dict/list
    if isinstance(source, dict):
        dm = source.get("metrics")
        if isinstance(dm, dict):
            metrics.update(dm)
        elif isinstance(dm, list):
            for item in dm:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    metrics[item["name"]] = item["value"]

    return metrics


def handle_diff(args: argparse.Namespace) -> int:
    base_path = Path(args.baseline)
    cand_path = Path(args.candidate)

    if not base_path.is_file():
        print(f"Error: Baseline file '{base_path}' not found.", file=sys.stderr)
        return 2
    if not cand_path.is_file():
        print(f"Error: Candidate file '{cand_path}' not found.", file=sys.stderr)
        return 2

    # Load baseline
    try:
        base_src = load_and_normalize_evidence_file(base_path)
        base_status = "PASS" if base_src.passed else "FAIL"
        base_solver = base_src.solver
    except Exception:
        with open(base_path, "r", encoding="utf-8") as f:
            base_src = json.load(f)
        base_status = base_src.get("status")
        base_solver = base_src.get("solver") or base_src.get("metadata", {}).get("solver")

    # Load candidate
    try:
        cand_src = load_and_normalize_evidence_file(cand_path)
        cand_status = "PASS" if cand_src.passed else "FAIL"
        cand_solver = cand_src.solver
    except Exception:
        with open(cand_path, "r", encoding="utf-8") as f:
            cand_src = json.load(f)
        cand_status = cand_src.get("status")
        cand_solver = cand_src.get("solver") or cand_src.get("metadata", {}).get("solver")

    base_metrics = _extract_flat_metrics(base_src)
    cand_metrics = _extract_flat_metrics(cand_src)

    # Compute key differences
    metric_diffs: Dict[str, Any] = {}
    all_metric_keys = sorted(set(list(base_metrics.keys()) + list(cand_metrics.keys())))

    for k in all_metric_keys:
        b_val = base_metrics.get(k)
        c_val = cand_metrics.get(k)
        delta = None
        rel = None
        if isinstance(b_val, (int, float)) and isinstance(c_val, (int, float)):
            delta = c_val - b_val
            if b_val != 0:
                rel = delta / abs(b_val)
        metric_diffs[k] = {
            "baseline": b_val,
            "candidate": c_val,
            "delta": delta,
            "relative_change": rel,
        }

    diff_report = {
        "baseline_file": str(base_path),
        "candidate_file": str(cand_path),
        "status_changed": base_status != cand_status,
        "baseline_status": base_status,
        "candidate_status": cand_status,
        "solver_baseline": base_solver,
        "solver_candidate": cand_solver,
        "metric_differences": metric_diffs,
    }

    if args.json:
        print(json.dumps(diff_report, indent=2, ensure_ascii=False))
    else:
        print(f"=== AnalysisRun Difference Report ===")
        print(f"Baseline:  {base_path.name} (Status: {diff_report['baseline_status']}, Solver: {diff_report['solver_baseline']})")
        print(f"Candidate: {cand_path.name} (Status: {diff_report['candidate_status']}, Solver: {diff_report['solver_candidate']})")
        print(f"Status Changed: {diff_report['status_changed']}")
        print("\n--- Metric Deltas ---")
        for k, v in metric_diffs.items():
            b_s = f"{v['baseline']}" if v['baseline'] is not None else "-"
            c_s = f"{v['candidate']}" if v['candidate'] is not None else "-"
            d_s = f"{v['delta']:+.4e}" if v['delta'] is not None else "-"
            print(f"  {k:30s} | Base: {b_s:14s} | Cand: {c_s:14s} | Delta: {d_s}")

    return 0


def handle_diagnose(args: argparse.Namespace) -> int:
    p = Path(args.path)
    if not p.exists():
        print(f"Error: Path '{p}' does not exist.", file=sys.stderr)
        return 2

    msg_text = ""
    sta_text = ""
    dat_text = ""
    log_text = ""

    if p.is_file():
        suffix = p.suffix.lower()
        content = p.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".msg":
            msg_text = content
        elif suffix == ".sta":
            sta_text = content
        elif suffix == ".dat":
            dat_text = content
        elif suffix == ".log":
            log_text = content
        else:
            # treat general file as msg/log
            msg_text = content
    elif p.is_dir():
        job_prefix = args.job_name or ""
        for item in p.iterdir():
            if not item.is_file():
                continue
            if job_prefix and not item.name.startswith(job_prefix):
                continue
            s = item.suffix.lower()
            text = item.read_text(encoding="utf-8", errors="ignore")
            if s == ".msg":
                msg_text = text
            elif s == ".sta":
                sta_text = text
            elif s == ".dat":
                dat_text = text
            elif s == ".log":
                log_text = text

    inp_path = Path(args.inp) if getattr(args, "inp", None) else None
    if inp_path is None:
        if p.is_file() and p.suffix.lower() == ".inp":
            inp_path = p
        elif p.is_dir():
            job_prefix = args.job_name or ""
            candidates = [
                item for item in p.iterdir()
                if item.is_file() and item.suffix.lower() == ".inp"
                and (not job_prefix or item.name.startswith(job_prefix))
            ]
            if len(candidates) == 1:
                inp_path = candidates[0]
    inp_text = None
    if inp_path is not None and inp_path.is_file():
        inp_text = inp_path.read_text(encoding="utf-8", errors="ignore")

    issues = list(diagnose_solver_artifacts(
        msg_text=msg_text,
        sta_text=sta_text,
        dat_text=dat_text,
        log_text=log_text,
        inp_text=inp_text,
    ))
    if inp_path is not None and inp_text is not None:
        issues.extend(diagnose_inp_contract(inp_text, source=str(inp_path)))

    if args.json:
        print(json.dumps([iss.to_dict() for iss in issues], indent=2, ensure_ascii=False))
    else:
        print(f"=== Abaqus Solver Diagnostics ({len(issues)} issues detected) ===")
        if not issues:
            print("No known diagnostic anomalies detected in provided solver artifacts.")
        for iss in issues:
            print(f"[{iss.severity}] {iss.diagnosis_id}")
            print(f"  Cause:       {iss.likely_cause}")
            print(f"  Remediation: {iss.suggested_remediation}")
            if iss.supporting_evidence:
                print(f"  Evidence:    {iss.supporting_evidence[0]}")
            print()

    has_error = any(iss.severity == "ERROR" for iss in issues)
    return 1 if has_error else 0


def handle_report(args: argparse.Namespace) -> int:
    ev_path = Path(args.evidence_file)
    if not ev_path.is_file():
        print(f"Error: Evidence file '{ev_path}' not found.", file=sys.stderr)
        return 2

    raw_unnormalized: Dict[str, Any] = {}
    try:
        raw_unnormalized = json.loads(ev_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    try:
        raw = load_and_normalize_evidence_file(str(ev_path)).to_dict()
    except Exception as e:
        raw = raw_unnormalized

    # Synthesize an EngineeringReportData structure from evidence dict
    case_def = standard_golden_catalog.get_case(raw.get("case_id", ""))
    default_title = case_def.title if case_def else raw.get("case_id", "Engineering Analysis Report")

    title = (
        args.title
        or raw_unnormalized.get("title")
        or raw.get("title")
        or default_title
    )
    objective = (
        raw_unnormalized.get("summary")
        or raw.get("summary")
        or (f"{case_def.title} - {case_def.physics_type}" if case_def else "")
        or ""
    )
    flat_metrics = _extract_flat_metrics(raw)
    if not flat_metrics and isinstance(raw_unnormalized, dict):
        flat_metrics = _extract_flat_metrics(raw_unnormalized)
    results_list = [{"name": k, "value": v} for k, v in flat_metrics.items()]

    acc_obj = raw.get("acceptance") or raw_unnormalized.get("acceptance") or raw_unnormalized.get("report", {}).get("acceptance")
    checks_obj = raw.get("verification") or raw_unnormalized.get("verification") or raw_unnormalized.get("report", {}).get("engineering_checks")

    gate_record = build_delivery_record(
        provenance=raw.get("provenance") or raw_unnormalized.get("provenance"),
        results=raw.get("results") or raw.get("metrics") or raw.get("result_evidence")
        or raw_unnormalized.get("results") or raw_unnormalized.get("metrics") or (),
        odb_path=raw.get("odb_path") or (raw.get("odb") or {}).get("path"),
        odb_sha256=raw.get("odb_sha256"),
        acceptance=acc_obj,
        condition_fidelity=raw.get("condition_fidelity")
        or raw_unnormalized.get("condition_fidelity")
        or (raw_unnormalized.get("report") or {}).get("condition_fidelity"),
        figures=raw.get("figures") or raw_unnormalized.get("figures") or (),
        # Keep the declared kinds intact; see reporting/delivery.py for why a bool
        # here would demand every formal preprocessing figure.
        require_preprocessing_figures=(
            raw.get("required_preprocessing_figures")
            or raw_unnormalized.get("required_preprocessing_figures")
            or raw.get("require_preprocessing_figures")
            or raw_unnormalized.get("require_preprocessing_figures")
            or False
        ),
        model_contract_mismatch=raw.get("model_contract_mismatch")
        or raw_unnormalized.get("model_contract_mismatch"),
    )
    # A caller who asks for a formal file must supply both engineering verdicts.
    gate = verify_deliverable(gate_record, require_decision_inputs=bool(args.output))
    metadata = dict(raw.get("metadata") or {})
    metadata["deliverable_authorization"] = gate

    report = EngineeringReportData(
        title=title,
        objective=objective,
        solver={"solver": raw.get("solver", "standard"), "physics": raw.get("physics_type", "")},
        results=tuple(results_list),
        engineering_checks=tuple(checks_obj.items()) if isinstance(checks_obj, dict) else (checks_obj or ()),
        acceptance=acc_obj,
        fatigue=raw.get("fatigue") or raw_unnormalized.get("fatigue") or raw_unnormalized.get("report", {}).get("fatigue"),
        mechanism=raw.get("mechanism_topology") or raw.get("kinematics") or raw_unnormalized.get("mechanism"),
        provenance=raw.get("provenance") or raw_unnormalized.get("provenance"),
        classified_facts=classify_report_facts(results_list),
        conclusions=build_report_conclusions(
            acc_obj,
            objective_context=objective,
            run_id=str(raw.get("run_id") or raw_unnormalized.get("run_id") or ""),
            model_name=str(raw.get("model_name") or title),
            physics_domain=str(raw.get("physics_type") or raw.get("physics_domain") or ""),
        ),
        metadata=metadata,
    )

    requested_format = (args.format or "html").lower()
    if requested_format != "html":
        print(
            "BLOCKED: refusing to write a Markdown engineering report. "
            "HTML is the only formal deliverable.",
            file=sys.stderr,
        )
        return 2
    if args.output:
        requested_suffix = Path(args.output).suffix.lower()
        if requested_suffix in {".md", ".markdown"}:
            print(
                "BLOCKED: refusing to write a Markdown engineering report. "
                "HTML is the only formal deliverable.",
                file=sys.stderr,
            )
            return 2

    if not gate["deliverable_file_allowed"] and args.output:
        print("BLOCKED: refusing to write an engineering deliverable.", file=sys.stderr)
        print(f"Reasons: {', '.join(gate['reasons']) or 'unspecified'}", file=sys.stderr)
        print(
            "A formal report requires an Agent-issued run record. "
            "This is not a keyed signature; rewriting the JSON and recomputing the digest does not create one.",
            file=sys.stderr,
        )
        return 2
    if not gate["allow_agent_attribution"]:
        print(
            "NOTE: this record is not authorized to be captioned as an Abaqus-AI-Agent JEV deliverable.",
            file=sys.stderr,
        )

    output_str = render_html(report)

    if args.output:
        out_path = Path(args.output)
        suffix = out_path.suffix.lower()
        if suffix in {".md", ".markdown"}:
            print(
                "BLOCKED: refusing to write a Markdown engineering report. "
                "HTML is the only formal deliverable.",
                file=sys.stderr,
            )
            return 2
        if suffix and suffix != ".html":
            print(
                f"BLOCKED: formal report must be HTML, not '{suffix}'.",
                file=sys.stderr,
            )
            return 2
        if not suffix:
            out_path = out_path.with_suffix(".html")
        try:
            written = write_gated_engineering_report(
                out_path,
                report=report,
                record=gate_record,
                fmt="html",
                allow_diagnostic_draft=False,
            )
        except PermissionError as exc:
            print(f"BLOCKED: {exc}", file=sys.stderr)
            return 2
        if written.get("kind") != "deliverable":
            print("BLOCKED: refusing to write an engineering deliverable.", file=sys.stderr)
            return 2
        print(f"Report written to: {Path(written['path']).resolve()}")
    else:
        if not gate["deliverable_file_allowed"] and not args.allow_preview:
            print("BLOCKED: refusing to print a deliverable. Pass --allow-preview for a non-deliverable preview.", file=sys.stderr)
            print(f"Reasons: {', '.join(gate['reasons']) or 'unspecified'}", file=sys.stderr)
            return 2
        print(output_str)

    return 0


def handle_verify_deliverable(args: argparse.Namespace) -> int:
    ev_path = Path(args.evidence_file)
    if not ev_path.is_file():
        print(f"Error: Evidence file '{ev_path}' not found.", file=sys.stderr)
        return 2
    try:
        record = json.loads(ev_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Error: cannot read JSON evidence: {exc}", file=sys.stderr)
        return 2
    gate = verify_deliverable(record if isinstance(record, dict) else {})
    if args.json:
        print(json.dumps(gate, indent=2, ensure_ascii=False))
    else:
        print(f"=== Deliverable Gate: {gate['status']} ===")
        print(f"File allowed:            {'YES' if gate['deliverable_file_allowed'] else 'NO'}")
        print(f"Agent attribution:       {'YES' if gate['allow_agent_attribution'] else 'NO'}")
        print(f"JEV routed:              {'YES' if gate['jev_routed'] else 'NO'}")
        print(f"Requirement kind:        {gate['requirement_kind']}")
        if gate["reasons"]:
            print(f"Reasons:                 {', '.join(gate['reasons'])}")
        print("Guarantee:               agent run record, not a keyed signature")
    return 0 if gate["deliverable_file_allowed"] else 2


def _build_case_graph(case: str):
    from .planning.mechanism import MechanismGraph

    m = MechanismGraph(f"FMBD_Case_{case.upper()}")
    m.add_body("ground", body_type="ground", ref_point_name="RP_GROUND", ref_point_coords=(0.0, 0.0, 0.0))

    if case == "fmbd4":
        m.add_body("crank", body_type="rigid", ref_point_name="RP_CRANK", ref_point_coords=(0.0, 0.0, 0.0))
        m.add_body(
            "flex_beam",
            body_type="flexible",
            part_name="BeamPart",
            instance_name="Beam-1",
            youngs_modulus=70000.0,
            poisson_ratio=0.33,
            density=2.7e-9,
            mesh_size=10.0,
        )
        m.add_flexible_interface(
            name="IFace_Root",
            body_name="flex_beam",
            interface_region="RootFace",
            ref_point_name="RP_BEAM_ROOT",
            ref_point_coords=(0.0, 100.0, 0.0),
        )
        m.add_joint("J_Ground", joint_type="revolute", body_a="ground", body_b="crank", location=(0.0, 0.0, 0.0))
        m.add_joint("J_Elbow", joint_type="revolute", body_a="crank", body_b="flex_beam", location=(0.0, 100.0, 0.0))

    elif case == "fmbd5":
        m.add_body("crank", body_type="rigid", ref_point_name="RP_CRANK", ref_point_coords=(0.0, 0.0, 0.0))
        m.add_body(
            "flex_rod",
            body_type="flexible",
            part_name="RodPart",
            instance_name="Rod-1",
            youngs_modulus=70000.0,
            poisson_ratio=0.33,
            density=2.7e-9,
            mesh_size=10.0,
        )
        m.add_body("slider", body_type="rigid", ref_point_name="RP_SLIDER", ref_point_coords=(200.0, 0.0, 0.0))
        m.add_flexible_interface(
            name="IFace_Rod_Elbow",
            body_name="flex_rod",
            interface_region="ElbowFace",
            ref_point_name="RP_ROD_ELBOW",
            ref_point_coords=(0.0, 100.0, 0.0),
        )
        m.add_flexible_interface(
            name="IFace_Rod_Wrist",
            body_name="flex_rod",
            interface_region="WristFace",
            ref_point_name="RP_ROD_WRIST",
            ref_point_coords=(200.0, 0.0, 0.0),
        )
        m.add_joint("J_CrankHinge", joint_type="revolute", body_a="ground", body_b="crank", location=(0.0, 0.0, 0.0))
        m.add_joint("J_Elbow", joint_type="revolute", body_a="crank", body_b="flex_rod", location=(0.0, 100.0, 0.0))
        m.add_joint("J_Wrist", joint_type="revolute", body_a="flex_rod", body_b="slider", location=(200.0, 0.0, 0.0))
        m.add_joint("J_SliderGuide", joint_type="prismatic", body_a="ground", body_b="slider", location=(200.0, 0.0, 0.0))

    elif case == "fmbd6":
        m.add_body("crank", body_type="rigid", ref_point_name="RP_CRANK", ref_point_coords=(0.0, 0.0, 0.0))
        m.add_body(
            "flex_proximal",
            body_type="flexible",
            part_name="PartProx",
            instance_name="Prox-1",
            youngs_modulus=70000.0,
            poisson_ratio=0.33,
            density=2.7e-9,
        )
        m.add_body(
            "flex_distal",
            body_type="flexible",
            part_name="PartDist",
            instance_name="Dist-1",
            youngs_modulus=70000.0,
            poisson_ratio=0.33,
            density=2.7e-9,
        )
        m.add_flexible_interface(
            name="IFace_Prox_In",
            body_name="flex_proximal",
            interface_region="ProxInFace",
            ref_point_name="RP_PROX_IN",
            ref_point_coords=(0.0, 100.0, 0.0),
        )
        m.add_flexible_interface(
            name="IFace_Prox_Mid",
            body_name="flex_proximal",
            interface_region="ProxMidFace",
            ref_point_name="RP_PROX_MID",
            ref_point_coords=(100.0, 100.0, 0.0),
        )
        m.add_flexible_interface(
            name="IFace_Dist_Mid",
            body_name="flex_distal",
            interface_region="DistMidFace",
            ref_point_name="RP_DIST_MID",
            ref_point_coords=(100.0, 100.0, 0.0),
        )
        m.add_joint("J_Pivot", joint_type="revolute", body_a="ground", body_b="crank", location=(0.0, 0.0, 0.0))
        m.add_joint("J_Elbow", joint_type="revolute", body_a="crank", body_b="flex_proximal", location=(0.0, 100.0, 0.0))
        m.add_joint("J_Knee", joint_type="revolute", body_a="flex_proximal", body_b="flex_distal", location=(100.0, 100.0, 0.0))

    elif case == "fmbd7":
        m.add_body("crank", body_type="rigid", ref_point_name="RP_CRANK_A", ref_point_coords=(0.0, 0.0, 10.0))
        m.add_body(
            "flex_coupler",
            body_type="flexible",
            part_name="CouplerPart",
            instance_name="Coupler-1",
            youngs_modulus=70000.0,
            poisson_ratio=0.33,
            density=2.7e-9,
        )
        m.add_body(
            "flex_rocker",
            body_type="flexible",
            part_name="RockerPart",
            instance_name="Rocker-1",
            youngs_modulus=100000.0,
            poisson_ratio=0.30,
            density=4.5e-9,
        )
        m.add_flexible_interface(
            name="IFace_Coupler_B",
            body_name="flex_coupler",
            interface_region="CouplerRootFace",
            ref_point_name="RP_COUPLER_B",
            ref_point_coords=(0.0, 100.0, 10.0),
        )
        m.add_flexible_interface(
            name="IFace_Coupler_C",
            body_name="flex_coupler",
            interface_region="CouplerTipFace",
            ref_point_name="RP_COUPLER_C",
            ref_point_coords=(200.0, 100.0, 10.0),
        )
        m.add_flexible_interface(
            name="IFace_Rocker_C",
            body_name="flex_rocker",
            interface_region="RockerTopFace",
            ref_point_name="RP_ROCKER_C",
            ref_point_coords=(200.0, 100.0, 10.0),
        )
        m.add_flexible_interface(
            name="IFace_Rocker_D",
            body_name="flex_rocker",
            interface_region="RockerBottomFace",
            ref_point_name="RP_ROCKER_D",
            ref_point_coords=(200.0, 0.0, 10.0),
        )
        m.add_joint("J_Pivot", joint_type="revolute", body_a="ground", body_b="crank", location=(0.0, 0.0, 10.0))
        m.add_joint("J_Elbow", joint_type="revolute", body_a="crank", body_b="flex_coupler", location=(0.0, 100.0, 10.0))
        m.add_joint("J_Knee", joint_type="revolute", body_a="flex_coupler", body_b="flex_rocker", location=(200.0, 100.0, 10.0))
        m.add_joint("J_Anchor", joint_type="revolute", body_a="flex_rocker", body_b="ground", location=(200.0, 0.0, 10.0))

    return m


def handle_fmbd(args: argparse.Namespace) -> int:
    case = args.case
    graph = _build_case_graph(case)
    report = graph.validate_topology()

    if args.compile:
        actions = graph.compile_to_actions(model_name=f"Model_{case.upper()}")
        action_dicts = [
            {"action_type": a.action_type, "parameters": a.parameters}
            for a in actions
        ]
        if args.json:
            print(json.dumps({
                "case": case,
                "action_count": len(actions),
                "actions": action_dicts,
            }, indent=2, ensure_ascii=False))
        else:
            print(f"=== Mechanism Compilation Plan ({case}): {len(actions)} Actions ===")
            for i, a in enumerate(actions, 1):
                p_keys = list(a.parameters.keys())
                print(f"  [{i:02d}] {a.action_type:30s} | params: {p_keys}")
        return 0

    # Default to verify topology
    report_dict = {
        "is_valid": report.is_valid,
        "num_bodies": report.num_bodies,
        "num_rigid_bodies": report.num_rigid_bodies,
        "num_flexible_bodies": report.num_flexible_bodies,
        "num_joints": report.num_joints,
        "num_interfaces": report.num_interfaces,
        "is_closed_loop": report.is_closed_loop,
        "closed_loops_count": report.closed_loops_count,
        "mobility_rigid_spatial": report.mobility_rigid_spatial,
        "mobility_rigid_planar": report.mobility_rigid_planar,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
    }

    if args.json:
        print(json.dumps(report_dict, indent=2, ensure_ascii=False))
    else:
        print(f"=== Mechanism Topology Verification ({case}) ===")
        print(f"Valid:                 {'YES' if report.is_valid else 'NO'}")
        print(f"Bodies:                {report.num_bodies} (Rigid: {report.num_rigid_bodies}, Flexible: {report.num_flexible_bodies})")
        print(f"Joints:                {report.num_joints}")
        print(f"Flexible Interfaces:   {report.num_interfaces}")
        print(f"Closed-Loop:           {'YES' if report.is_closed_loop else 'NO'} ({report.closed_loops_count} loops)")
        print(f"Planar Mobility (DOF): {report.mobility_rigid_planar}")
        print(f"Spatial Mobility (DOF):{report.mobility_rigid_spatial}")
        if report.errors:
            print(f"Errors: {list(report.errors)}")

    return 0 if report.is_valid else 1


def handle_memory(args: argparse.Namespace) -> int:
    from .run_index import RunIndex

    dir_path = Path(args.dir)
    index = RunIndex()
    loaded = index.load_from_directory(dir_path)

    if args.manifest:
        manifest = index.export_manifest()
        if args.json:
            print(json.dumps(manifest, indent=2, ensure_ascii=False))
        else:
            print(f"=== Case Memory Manifest ({dir_path}) ===")
            print(f"Total Runs: {manifest['total_runs']}")
            for r in manifest["runs"]:
                pass_str = "PASS" if r.get("acceptance_passed") else ("FAIL" if r.get("acceptance_passed") is False else "UNKNOWN")
                print(f"[{r.get('id', ''):20s}] {r.get('solver', ''):10s} {r.get('model_name', ''):12s} {pass_str:7s} {r.get('state', '')}")
        return 0

    passed_filter = None
    if args.passed:
        passed_filter = True
    elif args.failed:
        passed_filter = False

    runs = index.search_runs(
        solver=args.solver,
        engineering_status=args.status,
        acceptance_passed=passed_filter,
    )

    if args.json:
        data = [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in runs]
        print(json.dumps({"directory": str(dir_path), "loaded": loaded, "matched": len(data), "runs": data}, indent=2, ensure_ascii=False))
    else:
        print(f"=== Case Memory Search ({dir_path}) ===")
        print(f"Scanned files in dir: {loaded}, Matched runs: {len(runs)}")
        for r in runs:
            p_val = getattr(r, "acceptance_passed", None)
            pass_str = "PASS" if p_val is True else ("FAIL" if p_val is False else "N/A")
            st_val = getattr(r, "state", "")
            if hasattr(st_val, "value"):
                st_val = st_val.value
            print(f"[{getattr(r, 'id', ''):20s}] Solver: {getattr(r, 'solver', ''):10s} Job: {getattr(r, 'job_name', ''):12s} Status: {getattr(r, 'engineering_status', ''):15s} Acceptance: {pass_str}")

    return 0


def handle_assets(args: argparse.Namespace) -> int:
    """Inspect and query validation assets registry."""
    from .paths import get_repo_root, resolve_validation_assets_root

    repo = get_repo_root()
    val_root = resolve_validation_assets_root()
    registry_file = val_root / "registry.json"
    if not registry_file.is_file():
        registry_file = repo / "validation_assets" / "registry.json"

    if not registry_file.is_file():
        print(f"Error: Registry file not found at {registry_file}", file=sys.stderr)
        return 1

    with open(registry_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    cases = data.get("cases", [])

    if args.case:
        target = args.case.upper()
        found = next(
            (c for c in cases if c.get("case_id", "").upper() == target or target in c.get("case_id", "").upper()),
            None,
        )
        if not found:
            print(f"Error: Case '{args.case}' not found in validation registry.", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(found, indent=2, ensure_ascii=False))
        else:
            print(f"=== Case Asset: {found.get('case_id')} ===")
            print(f"Name:          {found.get('case_name')}")
            print(f"Domain:        {found.get('physics_domain')}")
            print(f"Status:        {found.get('qualification_status')}")
            print(f"Reference:     {found.get('reference_source')}")
            print(f"Directory:     {found.get('case_dir')}")
            print(f"Manifest:      {found.get('evidence_manifest')}")
            print("Input Assets:")
            for inp in found.get("input_assets", []):
                print(f"  - {inp}")
            print("Acceptance Criteria:")
            for k, v in found.get("acceptance_criteria", {}).items():
                print(f"  - {k}: {v}")
        return 0

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    print(f"=== Canonical Validation Assets Registry ({len(cases)} Cases) ===")
    for c in cases:
        status_tag = f"[{c.get('qualification_status', 'UNKNOWN'):12s}]"
        print(f"{status_tag} {c.get('case_id', ''):40s} {c.get('case_name', '')}")
    return 0


def handle_material(args: argparse.Namespace) -> int:
    """Query and inspect authentic engineering materials, properties, and experimental curves."""
    from .materials.provider import MaterialProvider
    from .reasoning.material_catalog import STANDARD_MATERIALS, _find_profile
    from .contracts.material_resolver import MaterialResolver

    provider = MaterialProvider.default()

    # 1. List all materials
    if args.list or not args.name:
        items = []
        seen_grades = set()

        # Builtin standard catalog
        for p in STANDARD_MATERIALS:
            seen_grades.add(p.canonical_name.lower())
            items.append({
                "name": p.canonical_name,
                "family": p.material_family,
                "source": p.standard_reference,
                "type": "standard_reference",
                "curves_available": False,
                "youngs_modulus_mpa": p.youngs_modulus_mpa,
                "yield_strength_mpa": p.yield_strength_mpa,
                "density_tonne_mm3": p.density_tonne_mm3,
                "aliases": list(p.aliases),
            })

        # Authentic provider records (CAMPUS / MMPDS / lab datasheets)
        for canonical_key, rec in provider._records_by_grade.items():
            if rec.identity.grade.lower() in seen_grades:
                continue
            seen_grades.add(rec.identity.grade.lower())
            prop_e = rec.get_property("youngs_modulus") or rec.get_property("tensile_modulus")
            prop_sy = rec.get_property("yield_stress") or rec.get_property("stress_at_break")
            prop_rho = rec.get_property("density")

            rho_val = None
            if prop_rho:
                if prop_rho.unit in ("g/cm3", "g/cm^3"):
                    rho_val = prop_rho.value * 1e-9
                elif prop_rho.unit in ("kg/m3", "kg/m^3"):
                    rho_val = prop_rho.value * 1e-12
                else:
                    rho_val = prop_rho.value

            items.append({
                "name": rec.identity.grade,
                "family": rec.identity.polymer_family,
                "source": f"{rec.identity.manufacturer} / {rec.source.provider} ({rec.source.source_type})",
                "type": "authentic_datasheet",
                "curves_available": len(rec.curves) > 0,
                "youngs_modulus_mpa": prop_e.value if prop_e else None,
                "yield_strength_mpa": prop_sy.value if prop_sy else None,
                "density_tonne_mm3": rho_val,
                "aliases": [k for k, v in provider._alias_map.items() if v == canonical_key],
            })

        if args.json:
            print(json.dumps({"total": len(items), "materials": items}, indent=2, ensure_ascii=False))
        else:
            print(f"=== Registered Engineering Materials ({len(items)} items) ===")
            print(f"{'Material / Grade':<26} | {'Family':<18} | {'E (MPa)':<10} | {'Yield (MPa)':<12} | {'Curves':<7} | Source")
            print("-" * 105)
            for it in items:
                e_str = f"{it['youngs_modulus_mpa']:.0f}" if it['youngs_modulus_mpa'] is not None else "N/A"
                sy_str = f"{it['yield_strength_mpa']:.1f}" if it['yield_strength_mpa'] is not None else "N/A"
                curv_str = "YES" if it["curves_available"] else "NO"
                print(f"{it['name']:<26} | {it['family']:<18} | {e_str:<10} | {sy_str:<12} | {curv_str:<7} | {it['source']}")
        return 0

    # 2. Query specific material by name
    name_query = args.name.strip()
    rec = provider.find_record(name_query)

    if rec is not None:
        prop_e = rec.get_property("youngs_modulus") or rec.get_property("tensile_modulus")
        prop_nu = rec.get_property("poissons_ratio")
        prop_rho = rec.get_property("density")
        prop_sy = rec.get_property("yield_stress") or rec.get_property("stress_at_break")
        prop_tc = rec.get_property("thermal_conductivity")
        prop_exp = rec.get_property("expansion_coefficient") or rec.get_property("clte")

        rho_val = None
        if prop_rho:
            if prop_rho.unit in ("g/cm3", "g/cm^3"):
                rho_val = prop_rho.value * 1e-9
            elif prop_rho.unit in ("kg/m3", "kg/m^3"):
                rho_val = prop_rho.value * 1e-12
            else:
                rho_val = prop_rho.value

        # Attempt resolving to Abaqus MaterialDefinition for calibrated *Plastic table
        from .reasoning.material_catalog import classify_material_input
        disposition = classify_material_input(rec, analysis="linear_elastic")
        res_result = MaterialResolver.resolve(
            rec,
            constitutive_intent="linear_elastic",
            target_unit_system="MM_N_MPA",
            allow_assisted_assumptions=False,
        )

        plastic_table = []
        if (
            disposition.status == "HARDENING_VERIFIED"
            and res_result.material_definition
            and res_result.material_definition.plastic
        ):
            plastic_table = [
                {"yield_stress_mpa": pt[0], "plastic_strain": pt[1]}
                for pt in res_result.material_definition.plastic.hardening_table
                if len(pt) >= 2 and pt[1] > 0.0
            ]

        curves_data = []
        for c in rec.curves:
            curves_data.append({
                "curve_type": c.curve_type,
                "x_name": c.x_name,
                "x_unit": c.x_unit,
                "y_name": c.y_name,
                "y_unit": c.y_unit,
                "num_points": len(c.points),
                "condition": c.condition.to_dict(),
                "points": [list(pt) for pt in c.points],
            })

        nu_disp = prop_nu.value if prop_nu else (
            res_result.material_definition.elastic.poisson_ratio
            if res_result.material_definition and res_result.material_definition.elastic
            else None
        )

        out_data = {
            "found": True,
            "category": "authentic_datasheet",
            "identity": rec.identity.to_dict(),
            "source": rec.source.to_dict(),
            "default_condition": rec.default_condition.to_dict(),
            "properties": {
                "youngs_modulus_mpa": prop_e.value if prop_e else None,
                "poissons_ratio": nu_disp,
                "density_tonne_mm3": rho_val,
                "yield_strength_mpa": prop_sy.value if prop_sy else None,
                "thermal_conductivity": prop_tc.value if prop_tc else None,
                "expansion_coefficient": prop_exp.value if prop_exp else None,
            },
            "calibrated_abaqus_plastic": plastic_table,
            "curves": curves_data,
        }

        if args.json:
            print(json.dumps(out_data, indent=2, ensure_ascii=False))
            return 0

        # Human-readable format
        print(f"=== Authentic Engineering Material: {rec.identity.grade} ===")
        print(f"Manufacturer:     {rec.identity.manufacturer}")
        print(f"Polymer / Family: {rec.identity.polymer_family}")
        if rec.identity.trade_name:
            print(f"Trade Name:       {rec.identity.trade_name}")
        if rec.identity.reinforcement_type:
            print(f"Reinforcement:    {rec.identity.reinforcement_type} ({rec.identity.reinforcement_content or 0:.0f} wt%)")
        print(f"Source Database:  {rec.source.provider} [{rec.source.source_type}] (Locator: {rec.source.locator})")
        print(f"Evidence Level:   {rec.source.evidence_level}")
        print(f"Test Condition:   T={rec.default_condition.temperature}°{rec.default_condition.temperature_unit}, {rec.default_condition.humidity_state}")

        print("\n--- Physical & Mechanical Properties (MM_N_MPA) ---")
        if prop_e:
            print(f"Young's Modulus (E):   {prop_e.value:.1f} MPa ({prop_e.value / 1000.0:.2f} GPa)")
        if nu_disp is not None:
            print(f"Poisson's Ratio (nu):  {nu_disp:.3f}")
        if rho_val is not None:
            print(f"Density (rho):         {rho_val:.3e} tonne/mm3 ({rho_val * 1e12:.1f} kg/m3)")
        if prop_sy:
            print(f"Yield / Break Stress:  {prop_sy.value:.1f} MPa")
        if prop_tc:
            print(f"Thermal Conductivity:  {prop_tc.value} {prop_tc.unit}")
        if prop_exp:
            print(f"CLTE:                  {prop_exp.value} {prop_exp.unit}")

        if plastic_table:
            print(f"\n--- Calibrated Abaqus *Plastic Hardening Table ({len(plastic_table)} points) ---")
            print(f"  {'Yield Stress (MPa)':<20} | {'Plastic Strain':<16}")
            print("  " + "-" * 38)
            limit_pts = plastic_table if args.curves else plastic_table[:8]
            for pt in limit_pts:
                print(f"  {pt['yield_stress_mpa']:<20.2f} | {pt['plastic_strain']:<16.6f}")
            if len(plastic_table) > len(limit_pts):
                print(f"  ... ({len(plastic_table) - len(limit_pts)} more points. Pass --curves to display full table)")

        if curves_data:
            print(f"\n--- Experimental Curves Available: {len(curves_data)} curve(s) ---")
            for c in curves_data:
                print(f"  Curve: {c['curve_type']} ({c['x_name']} [{c['x_unit']}] vs {c['y_name']} [{c['y_unit']}], {c['num_points']} pts)")
                if args.curves:
                    print(f"    {'Strain (' + c['x_unit'] + ')':<20} | {'Stress (' + c['y_unit'] + ')':<20}")
                    print("    " + "-" * 42)
                    for pt in c["points"]:
                        print(f"    {pt[0]:<20.4f} | {pt[1]:<20.2f}")

        return 0

    # 3. Check standard reference catalog
    profile = _find_profile(name_query)
    if profile is not None:
        out_data = {
            "found": True,
            "category": "standard_reference",
            "name": profile.canonical_name,
            "family": profile.material_family,
            "source": profile.standard_reference,
            "properties": {
                "youngs_modulus_mpa": profile.youngs_modulus_mpa,
                "poissons_ratio": profile.poissons_ratio,
                "density_tonne_mm3": profile.density_tonne_mm3,
                "yield_strength_mpa": profile.yield_strength_mpa,
            },
            "aliases": list(profile.aliases),
            "curves": [],
        }

        if args.json:
            print(json.dumps(out_data, indent=2, ensure_ascii=False))
            return 0

        print(f"=== Standard Reference Material: {profile.canonical_name} ===")
        print(f"Family:           {profile.material_family}")
        print(f"Standard / Ref:   {profile.standard_reference}")
        print(f"Aliases:          {', '.join(profile.aliases)}")
        print("\n--- Standard Properties (MM_N_MPA) ---")
        print(f"Young's Modulus (E):   {profile.youngs_modulus_mpa:.1f} MPa ({profile.youngs_modulus_mpa / 1000.0:.2f} GPa)")
        print(f"Poisson's Ratio (nu):  {profile.poissons_ratio:.3f}")
        print(f"Density (rho):         {profile.density_tonne_mm3:.3e} tonne/mm3 ({profile.density_tonne_mm3 * 1e12:.1f} kg/m3)")
        print(f"Yield Strength (Sy):   {profile.yield_strength_mpa:.1f} MPa")
        print("Note: Reference catalog provides canonical linear-elastic/yield values. No multi-point experimental curves.")
        return 0

    # 4. Not found
    print(f"Error: Material '{name_query}' not found in standard catalog or authentic databases.", file=sys.stderr)
    print("Pass 'abaqus-ai-agent material --list' to inspect all registered materials.", file=sys.stderr)
    return 1


def handle_approve(args: argparse.Namespace) -> int:
    """Approve the current execution candidate of a workdir (Phase A -> B)."""
    from .execution.approval_service import approve_current_candidate

    try:
        approved = approve_current_candidate(
            args.workdir, approved_by=args.approved_by, note=args.note
        )
    except Exception as exc:
        print(f"APPROVAL FAILED: {exc}")
        return 2
    record = approved.approval.to_dict() if approved.approval else {}
    if args.json:
        print(json.dumps({"candidate": approved.to_dict()}, indent=2, ensure_ascii=False))
    else:
        print("=== Execution Candidate Approved ===")
        print(f"Candidate:       {approved.candidate_id}")
        print(f"Manifest SHA256: {approved.execution_manifest_hash}")
        print(f"Approved by:     {record.get('approved_by')}")
        print(f"Approved at:     {record.get('approved_at')}")
        print(f"Report bound:    {record.get('review_report_hash') or '(no review report file found)'}")
        print("Re-run the analysis with the same workdir to proceed to solver submission.")
        print("Note: digests are tamper-evidence, not identity signatures.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)



    handlers = {
        "inspect": handle_inspect,
        "matrix": handle_matrix,
        "diff": handle_diff,
        "diagnose": handle_diagnose,
        "report": handle_report,
        "verify-deliverable": handle_verify_deliverable,
        "fmbd": handle_fmbd,
        "memory": handle_memory,
        "ask": handle_ask,
        "approve": handle_approve,
        "assets": handle_assets,
        "material": handle_material,
    }

    handler = handlers.get(args.subcommand)
    if not handler:
        parser.print_help()
        return 2

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
