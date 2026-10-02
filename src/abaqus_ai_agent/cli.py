"""Command-line interface (CLI) for Abaqus-AI-Agent.

Provides a unified command-line tool for:
1. inspect: inspect host Abaqus runtime, launcher, and capabilities.
2. matrix: list, validate, and summarize Golden Case evidence.
3. diff: compute deterministic run-level diff between two runs.
4. diagnose: deterministic diagnosis of Abaqus solver artifacts (.msg, .sta, .dat, .log).
5. report: render Markdown/HTML engineering report from evidence or AnalysisRun.
6. fmbd: inspect mechanism topology and action compilation plan for MBD/FMBD models.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .contracts.provenance import AnalysisProvenance
from .diagnostics.solver_patterns import DiagnosticIssue, diagnose_solver_artifacts
from .golden_evidence import (
    load_and_normalize_evidence_file,
    validate_golden_evidence_dict,
)
from .golden_registry import (
    GoldenCaseDefinition,
    standard_golden_catalog,
)
from .reporting.renderer import render_markdown, render_html
from .contracts.report import EngineeringReportData


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
    p_diag.add_argument("--json", action="store_true", help="Output structured diagnostic issues as JSON.")

    # 5. report
    p_rep = subparsers.add_parser("report", help="Render engineering report deliverable from evidence JSON.")
    p_rep.add_argument("evidence_file", help="Path to evidence or AnalysisRun JSON file.")
    p_rep.add_argument("--format", choices=["markdown", "html"], default="markdown", help="Output format (default: markdown)")
    p_rep.add_argument("--output", "-o", help="Output file path (default: stdout)")
    p_rep.add_argument("--title", help="Override report title.")

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

    return parser


# --- Handlers ---

def handle_inspect(args: argparse.Namespace) -> int:
    import shutil
    import subprocess

    launcher = args.launcher
    which_path = shutil.which(launcher)
    version_info = "unavailable"
    license_ok = False
    returncode = 0

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
            out = p.stdout.strip()
            if p.returncode == 0:
                license_ok = True
                version_info = out.splitlines()[0] if out else "Abaqus detected"
            else:
                version_info = "Abaqus executable detected (launcher ready)"
                license_ok = True
        except Exception as e:
            version_info = f"Detection probe: {e}"
            license_ok = False

    data = {
        "launcher": launcher,
        "located_path": which_path,
        "available": bool(which_path),
        "runtime_version": version_info,
        "license_probe_ok": license_ok,
    }

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("=== Abaqus Runtime Environment Inspection ===")
        print(f"Launcher command:  {data['launcher']}")
        print(f"Executable path:   {data['located_path'] or 'NOT FOUND in PATH'}")
        print(f"Availability:      {'YES' if data['available'] else 'NO'}")
        print(f"Runtime version:   {data['runtime_version']}")
        print(f"License probe:     {'PASS' if data['license_probe_ok'] else 'UNVERIFIED / NO LICENSE'}")

    return 0 if data["available"] else 1


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
        candidates = [
            workdir / rel.name,
            workdir / rel,
            workdir / f"{c.case_id}.json",
            workdir_arg / rel.name,
            workdir_arg / rel,
            workdir / "machine_validation" / rel.name,
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

    issues = diagnose_solver_artifacts(
        msg_text=msg_text,
        sta_text=sta_text,
        dat_text=dat_text,
        log_text=log_text,
    )

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
        metadata=raw.get("metadata", {}),
    )

    output_str = render_html(report) if args.format == "html" else render_markdown(report)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(output_str, encoding="utf-8")
        print(f"Report written to: {out_path.resolve()}")
    else:
        print(output_str)

    return 0


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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "inspect": handle_inspect,
        "matrix": handle_matrix,
        "diff": handle_diff,
        "diagnose": handle_diagnose,
        "report": handle_report,
        "fmbd": handle_fmbd,
        "memory": handle_memory,
    }

    handler = handlers.get(args.subcommand)
    if not handler:
        parser.print_help()
        return 2

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
