"""Unified Golden Case Evidence Schema and Normalizer.

Provides a single standard envelope schema for all real-machine Abaqus Golden Cases:
`case_id, release, runtime, solver, job, odb, solver_status, result_evidence,
 verification, acceptance, artifacts, provenance`.

Includes normalizers and validators to translate legacy or case-specific JSON
evidence outputs into this unified envelope without losing underlying metrics.
"""

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .golden_registry import GoldenCaseDefinition, GoldenMatrixCatalog, standard_golden_catalog


REQUIRED_ENVELOPE_KEYS = (
    "case_id",
    "release",
    "runtime",
    "solver",
    "job",
    "odb",
    "solver_status",
    "result_evidence",
    "verification",
    "acceptance",
    "artifacts",
    "provenance",
)

# Canonical mapping from various legacy case labels/names to registry case_id
CASE_NAME_TO_ID = {
    # Smoke
    "smoke": "smoke",
    "runtime_smoke": "smoke",
    "aiagent_runtimesmoke": "smoke",
    "b28_smoke": "smoke",
    "aiagent_b28smoke": "smoke",
    "b28smoke": "smoke",
    # Static
    "static_cantilever": "static_cantilever",
    "3d_cantilever_static": "static_cantilever",
    "static_golden_e2e": "static_cantilever",
    "staticgolden": "static_cantilever",
    "staticgoldenjob": "static_cantilever",
    # Mesh
    "mesh_convergence": "mesh_convergence",
    "3d_cantilever_mesh_convergence": "mesh_convergence",
    "mesh_convergence_e2e": "mesh_convergence",
    "meshconv": "mesh_convergence",
    "meshconv_fine": "mesh_convergence",
    # Tie
    "tie_contact": "tie_contact",
    "two_block_tied_cantilever_static": "tie_contact",
    "tie_contact_e2e": "tie_contact",
    "tiecontact": "tie_contact",
    "tiecontactjob": "tie_contact",
    # Dynamic
    "implicit_dynamic": "implicit_dynamic",
    "cantilever_implicit_dynamic": "implicit_dynamic",
    "dynamic_golden_e2e": "implicit_dynamic",
    "dynamicgolden": "implicit_dynamic",
    "dynamicgoldenjob": "implicit_dynamic",
    # Thermal
    "steady_thermal": "steady_thermal",
    "1d_steady_state_heat_conduction": "steady_thermal",
    "thermal_golden_e2e": "steady_thermal",
    "thermalgolden": "steady_thermal",
    "thermalgoldenjob": "steady_thermal",
    # General Contact
    "general_contact": "general_contact",
    "two_body_frictional_contact_sliding": "general_contact",
    "general_contact_e2e": "general_contact",
    "generalcontact": "general_contact",
    "generalcontactjob": "general_contact",
    # MBD-1
    "mbd1_rigid_pendulum": "mbd1_rigid_pendulum",
    "mbd_rigid_pendulum": "mbd1_rigid_pendulum",
    "mbd_golden_e2e": "mbd1_rigid_pendulum",
    "mbdgolden": "mbd1_rigid_pendulum",
    "mbdgoldenjob": "mbd1_rigid_pendulum",
    "mbd1": "mbd1_rigid_pendulum",
    # MBD-2
    "mbd2_double_pendulum": "mbd2_double_pendulum",
    "mbd2_revolute_golden_e2e": "mbd2_double_pendulum",
    "mbd2golden": "mbd2_double_pendulum",
    "mbd2goldenjob": "mbd2_double_pendulum",
    "mbd2": "mbd2_double_pendulum",
    # FMBD-4
    "fmbd4_rigid_flexible": "fmbd4_rigid_flexible",
    "fmbd4": "fmbd4_rigid_flexible",
    "fmbd4_rigid_flexible_golden_e2e": "fmbd4_rigid_flexible",
    "fmbd4golden": "fmbd4_rigid_flexible",
    "fmbd4goldenjob": "fmbd4_rigid_flexible",
    # FMBD-5
    "fmbd5_crank_slider": "fmbd5_crank_slider",
    "fmbd5": "fmbd5_crank_slider",
    "fmbd5_crank_slider_golden_e2e": "fmbd5_crank_slider",
    "fmbd5golden": "fmbd5_crank_slider",
    "fmbd5goldenjob": "fmbd5_crank_slider",
}


@dataclass
class GoldenEvidenceEnvelope:
    """Standardized envelope representing verified machine evidence for a Golden Case."""
    case_id: str
    release: str
    runtime: Dict[str, Any]
    solver: str
    job: str
    odb: Dict[str, Any]
    solver_status: str
    result_evidence: Dict[str, Any]
    verification: Dict[str, Any]
    acceptance: Dict[str, Any]
    artifacts: List[Any]
    provenance: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert the envelope to a clean, serializable dictionary."""
        return {
            "case_id": self.case_id,
            "release": self.release,
            "runtime": self.runtime,
            "solver": self.solver,
            "job": self.job,
            "odb": self.odb,
            "solver_status": self.solver_status,
            "result_evidence": self.result_evidence,
            "verification": self.verification,
            "acceptance": self.acceptance,
            "artifacts": self.artifacts,
            "provenance": self.provenance,
        }

    @property
    def passed(self) -> bool:
        """Convenience property indicating overall acceptance pass."""
        acc = self.acceptance
        if isinstance(acc, dict):
            return bool(acc.get("passed", False))
        return False


def validate_golden_evidence_dict(data: Dict[str, Any]) -> List[str]:
    """Validate a dictionary against the unified evidence schema.

    Returns a list of error strings; empty if perfectly valid.
    """
    errors = []
    if not isinstance(data, dict):
        return ["Evidence data must be a dictionary"]

    for key in REQUIRED_ENVELOPE_KEYS:
        if key not in data:
            errors.append(f"Missing required envelope key: '{key}'")

    if "case_id" in data and not isinstance(data["case_id"], str):
        errors.append("case_id must be a string")
    if "release" in data and not isinstance(data["release"], str):
        errors.append("release must be a string")
    if "runtime" in data and not isinstance(data["runtime"], dict):
        errors.append("runtime must be a dictionary")
    if "solver" in data and not isinstance(data["solver"], str):
        errors.append("solver must be a string")
    if "job" in data and not isinstance(data["job"], str):
        errors.append("job must be a string")
    if "odb" in data and not isinstance(data["odb"], dict):
        errors.append("odb must be a dictionary")
    if "solver_status" in data and not isinstance(data["solver_status"], str):
        errors.append("solver_status must be a string")
    if "result_evidence" in data and not isinstance(data["result_evidence"], dict):
        errors.append("result_evidence must be a dictionary")
    if "verification" in data and not isinstance(data["verification"], dict):
        errors.append("verification must be a dictionary")
    if "acceptance" in data and not isinstance(data["acceptance"], dict):
        errors.append("acceptance must be a dictionary")
    if "artifacts" in data and not isinstance(data["artifacts"], list):
        errors.append("artifacts must be a list")
    if "provenance" in data and not isinstance(data["provenance"], dict):
        errors.append("provenance must be a dictionary")

    return errors


def resolve_case_id(raw: Dict[str, Any], default: Optional[str] = None) -> str:
    """Infer the canonical case_id from raw evidence dictionary."""
    if "case_id" in raw and raw["case_id"]:
        candidate = str(raw["case_id"]).lower()
        if candidate in CASE_NAME_TO_ID:
            return CASE_NAME_TO_ID[candidate]
        return candidate

    for key in ("case", "name", "id"):
        if key in raw and raw[key]:
            val = str(raw[key]).lower()
            if val in CASE_NAME_TO_ID:
                return CASE_NAME_TO_ID[val]

    # Check job_name
    job = raw.get("job") or raw.get("job_name") or raw.get("jobName")
    if not job and isinstance(raw.get("report"), dict):
        job = raw["report"].get("job_name")
    if job:
        j_lower = str(job).lower()
        for k, v in CASE_NAME_TO_ID.items():
            if k in j_lower:
                return v

    # Check script path
    script = raw.get("script") or ""
    s_lower = str(script).lower()
    for k, v in CASE_NAME_TO_ID.items():
        if k in s_lower:
            return v

    if default:
        return default
    raise ValueError("Cannot resolve case_id from raw evidence")


def _detect_release(raw: Dict[str, Any], report: Dict[str, Any], default: Optional[str] = None) -> str:
    """Detect release string from raw evidence, report, or runtime context without blind invention."""
    if raw.get("release"):
        return str(raw["release"])
    if report.get("release"):
        return str(report["release"])
    prov = raw.get("provenance") or report.get("provenance") or {}
    if isinstance(prov, dict) and prov.get("release"):
        return str(prov["release"])

    # Check launcher path or content
    launcher = str(raw.get("launcher", ""))
    stderr = str(raw.get("stderr", "")) + " " + str(report.get("stderr", ""))
    stdout = str(raw.get("stdout", "")) + " " + str(report.get("stdout", ""))
    combined = f"{launcher} {stderr} {stdout}"
    if "2025" in combined:
        return "Abaqus 2025"

    # If launcher is a batch file on disk, check if it invokes a versioned abaqus
    if launcher:
        p = Path(launcher)
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                if "2025" in content or "abq2025" in content:
                    return "Abaqus 2025"
            except Exception:
                pass

    if default:
        return default
    return "unspecified"


def normalize_golden_evidence(
    raw: Dict[str, Any],
    case_id: Optional[str] = None,
    catalog: Optional[GoldenMatrixCatalog] = None,
    release_default: Optional[str] = None,
) -> GoldenEvidenceEnvelope:
    """Normalize raw case evidence dictionary into the standard GoldenEvidenceEnvelope.

    Applies strict parsing rules to avoid evidence invention:
    - Release is detected from explicit fields, launcher context, or recorded provenance.
    - Solver status requires explicit completion flags from workflow, checks, or harness.
    - Acceptance evaluates nested standard gates without fabricating PASS from top-level status.
    """
    cat = catalog or standard_golden_catalog
    cid = resolve_case_id(raw, default=case_id)
    definition = cat.get_case(cid)
    report = raw.get("report") if isinstance(raw.get("report"), dict) else {}

    # 1. Release
    release = _detect_release(raw, report, default=release_default)

    # 2. Runtime
    runtime: Dict[str, Any] = {
        "launcher": raw.get("launcher", "abaqus"),
        "workdir": raw.get("workdir", ""),
        "script": raw.get("script", ""),
        "command": raw.get("command", []),
        "return_code": raw.get("return_code", 0 if raw.get("process_succeeded") else 1),
        "process_succeeded": bool(raw.get("process_succeeded", raw.get("return_code") == 0)),
        "stdout": raw.get("stdout", ""),
        "stderr": raw.get("stderr", ""),
    }
    if "execution_time_s" in raw:
        runtime["execution_time_s"] = raw["execution_time_s"]

    # 3. Solver
    solver = str(raw.get("solver") or (definition.solver if definition else "standard"))

    # 4. Job Name
    job = str(
        raw.get("job")
        or report.get("job_name")
        or (definition.job_name if definition else "GoldenJob")
    )
    if job == "GoldenJob" and "odb_path" in report.get("solver", {}):
        job = Path(report["solver"]["odb_path"]).stem
    elif job == "GoldenJob" and "odb_path" in report.get("workflow", {}):
        job = Path(report["workflow"]["odb_path"]).stem

    # 5. ODB Information
    odb_path = ""
    if "odb" in raw and isinstance(raw["odb"], dict):
        odb_info = raw["odb"]
        odb_path = str(odb_info.get("path", ""))
    elif "odb_path" in raw:
        odb_path = str(raw["odb_path"])
    elif "solver" in report and "odb_path" in report["solver"]:
        odb_path = str(report["solver"]["odb_path"])
    elif "workflow" in report and "odb_path" in report["workflow"]:
        odb_path = str(report["workflow"]["odb_path"])
    elif "workflow" in raw and "odb_path" in raw["workflow"]:
        odb_path = str(raw["workflow"]["odb_path"])
    elif "runs" in report and isinstance(report["runs"], list) and len(report["runs"]) > 0:
        last_run = report["runs"][-1]
        if isinstance(last_run, dict) and last_run.get("odb_path"):
            odb_path = str(last_run["odb_path"])
    elif "harness" in raw:
        workdir = raw.get("workdir") or ""
        odb_path = os.path.join(workdir, f"{job}.odb") if workdir else f"{job}.odb"

    odb_exists = bool(raw.get("odb_exists", False))
    if odb_path and os.path.exists(odb_path):
        odb_exists = True
    elif "harness" in raw:
        odb_exists = bool(raw.get("harness", {}).get("odb_exists", False))
    elif "checks" in report and "all_odbs_exist" in report["checks"]:
        odb_exists = bool(report["checks"]["all_odbs_exist"])

    odb: Dict[str, Any] = {
        "path": odb_path,
        "exists": odb_exists,
    }
    if odb_path and os.path.exists(odb_path):
        try:
            odb["size_bytes"] = os.path.getsize(odb_path)
        except OSError:
            pass

    # 6. Solver Status (Requires explicit positive evidence; no invention from status=="pass")
    solver_status = "unknown"
    if "solver_status" in raw:
        solver_status = str(raw["solver_status"])
    elif "solver_completed" in report.get("workflow", {}):
        solver_status = "completed" if report["workflow"]["solver_completed"] else "failed"
    elif "workflow" in raw and "solver_completed" in raw["workflow"]:
        solver_status = "completed" if raw["workflow"]["solver_completed"] else "failed"
    elif "all_solvers_completed" in report.get("checks", {}):
        solver_status = "completed" if report["checks"]["all_solvers_completed"] else "failed"
    elif "runs" in report and isinstance(report["runs"], list) and len(report["runs"]) > 0:
        all_comp = all(bool(r.get("solver_completed")) for r in report["runs"] if isinstance(r, dict))
        solver_status = "completed" if all_comp else "failed"
    elif "harness" in raw and isinstance(raw["harness"], dict):
        h = raw["harness"]
        if h.get("job_completed") is True:
            solver_status = "completed"
        elif h.get("error_class") or h.get("job_completed") is False:
            solver_status = "failed"

    # 7. Result Evidence (physics observables)
    result_evidence: Dict[str, Any] = {}
    if "result_evidence" in raw and isinstance(raw["result_evidence"], dict):
        result_evidence = dict(raw["result_evidence"])
    elif "results" in report and isinstance(report["results"], dict):
        result_evidence = dict(report["results"])
    elif "simulation_results" in report and isinstance(report["simulation_results"], dict):
        result_evidence = dict(report["simulation_results"])
    elif "simulation_results" in raw and isinstance(raw["simulation_results"], dict):
        result_evidence = dict(raw["simulation_results"])
    elif "forces_and_equilibrium" in report:
        result_evidence["forces_and_equilibrium"] = report["forces_and_equilibrium"]
        if "contact_metrics" in report:
            result_evidence["contact_metrics"] = report["contact_metrics"]
    elif "harness" in raw and isinstance(raw["harness"], dict):
        result_evidence = dict(raw["harness"])

    # 8. Verification (analytical reference comparison)
    verification: Dict[str, Any] = {}
    if "verification" in raw and isinstance(raw["verification"], dict):
        verification = dict(raw["verification"])
    elif "verification" in report and isinstance(report["verification"], dict):
        verification = dict(report["verification"])
    elif "numerical_verification" in report and isinstance(report["numerical_verification"], dict):
        verification = dict(report["numerical_verification"])
        if "mesh_convergence" in report:
            verification["mesh_convergence"] = report["mesh_convergence"]
    elif "engineering_checks" in report and isinstance(report["engineering_checks"], dict):
        verification = dict(report["engineering_checks"])
    elif "theory" in raw and isinstance(raw["theory"], dict):
        verification = dict(raw["theory"])
    elif "theory" in report and isinstance(report["theory"], dict):
        verification = dict(report["theory"])
    elif "harness" in raw and isinstance(raw["harness"], dict):
        verification = {"harness_passed": bool(raw["harness"].get("passed", False))}

    # 9. Acceptance (formal engineering gate result without invention)
    raw_acc = raw.get("acceptance") or report.get("acceptance")
    acceptance: Dict[str, Any] = {}
    if isinstance(raw_acc, dict):
        if "standard" in raw_acc and isinstance(raw_acc["standard"], dict):
            # Nested standard/strict structure (e.g. mesh convergence)
            std = raw_acc["standard"]
            acceptance = {
                "passed": bool(std.get("passed", False)),
                "criteria": list(std.get("criteria", [])),
                "failures": list(std.get("failures", [])),
                "warnings": list(std.get("warnings", [])),
                "standard": std,
            }
            if "strict" in raw_acc:
                acceptance["strict"] = raw_acc["strict"]
        else:
            acceptance = dict(raw_acc)
            if "passed" not in acceptance:
                if "criteria" in acceptance and isinstance(acceptance["criteria"], list):
                    all_crit_passed = len(acceptance["criteria"]) > 0 and all(
                        bool(c.get("passed", False)) for c in acceptance["criteria"] if isinstance(c, dict)
                    )
                    has_failures = bool(acceptance.get("failures"))
                    acceptance["passed"] = bool(all_crit_passed and not has_failures)
                else:
                    acceptance["passed"] = False
    elif "harness" in raw and isinstance(raw["harness"], dict):
        h = raw["harness"]
        acceptance = {
            "passed": bool(h.get("passed", False)),
            "criteria": [
                {"name": "job_completed", "passed": bool(h.get("job_completed"))},
                {"name": "odb_exists", "passed": bool(h.get("odb_exists"))},
                {"name": "required_outputs_present", "passed": bool(h.get("required_outputs_present"))},
            ],
            "failures": [h["error_message"]] if h.get("error_message") else [],
            "warnings": [],
        }
    else:
        # No formal acceptance gate record found in evidence
        acceptance = {
            "passed": False,
            "criteria": [],
            "failures": ["No formal acceptance gate record found in evidence"],
            "warnings": [],
        }

    # 10. Artifacts
    artifacts: List[Any] = []
    if "artifacts" in raw and isinstance(raw["artifacts"], list):
        artifacts = list(raw["artifacts"])
    elif "solver" in report and "artifacts" in report["solver"]:
        artifacts = list(report["solver"]["artifacts"])
    else:
        if runtime.get("script"):
            artifacts.append({"path": runtime["script"], "kind": "script"})
        if odb_path:
            artifacts.append({"path": odb_path, "kind": "odb"})

    # 11. Provenance
    provenance: Dict[str, Any] = {}
    if "provenance" in raw and isinstance(raw["provenance"], dict):
        provenance = dict(raw["provenance"])
    elif "provenance" in report and isinstance(report["provenance"], dict):
        provenance = dict(report["provenance"])
    else:
        provenance = {
            "launcher": runtime.get("launcher"),
            "script": runtime.get("script"),
            "workdir": runtime.get("workdir"),
        }

    envelope = GoldenEvidenceEnvelope(
        case_id=cid,
        release=release,
        runtime=runtime,
        solver=solver,
        job=job,
        odb=odb,
        solver_status=solver_status,
        result_evidence=result_evidence,
        verification=verification,
        acceptance=acceptance,
        artifacts=artifacts,
        provenance=provenance,
    )
    return envelope


def load_and_normalize_evidence_file(file_path: Union[str, Path]) -> GoldenEvidenceEnvelope:
    """Load a JSON evidence file from disk and normalize into GoldenEvidenceEnvelope."""
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"Evidence file not found: {file_path}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    # Infer default case_id from filename stem if needed
    stem_candidate = p.stem.lower()
    default_id = CASE_NAME_TO_ID.get(stem_candidate)
    return normalize_golden_evidence(raw, case_id=default_id)
