#!/usr/bin/env python3
"""REQ-4.8 live probe: classifier disposition must match the deck CAE writes.

Four paths, one tiny cantilever each. This does not solve, and it does not
promote the catalog to an identified material database.

  linear_named     Q235, linear static          expect *ELASTIC, no *PLASTIC
  blocked_family   "钢", plasticity              expect compile refusal, no deck
  ideal_explicit   scalar card + explicit flag  expect *PLASTIC with one (sy, 0)
  hardening_user   user hardening table         expect *PLASTIC with strain > 0
"""

import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.execution.batch import BatchExecutor, completion_sentinel_code
from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, compile_engineering_intent
from abaqus_ai_agent.reasoning.material_catalog import classify_material_input


LAUNCHER = os.environ.get("ABAQUS_BAT", r"C:\SIMULIA\Commands\abaqus.bat")
WORK = ROOT / "runs" / "req48_material_gate"
EVIDENCE = ROOT / "machine_validation" / "req48_material_gate_evidence.json"


def _intent(case_id, material, analysis, description):
    return EngineeringIntent(
        id=case_id,
        kind=analysis,
        analysis_type=analysis,
        description=description,
        material=material,
        metadata={"geometry": IntentGeometrySpec(length=20.0, width=10.0, height=10.0)},
        unit_system="MM_N_MPA",
    )


CASES = (
    {
        "id": "linear_named",
        "material": "Q235",
        "analysis": "linear_static",
        "description": "elastic check below yield",
        "expect_status": "LINEAR_ELASTIC",
        "expect_compile": True,
        "expect_plastic": False,
    },
    {
        "id": "blocked_family",
        "material": "钢",
        "analysis": "plasticity",
        "description": "residual strain",
        "expect_status": "SCREENING",
        "expect_compile": False,
        "expect_plastic": False,
    },
    {
        "id": "ideal_explicit",
        "material": {
            "name": "LabHeat_42",
            "youngs_modulus": 200000.0,
            "poisson": 0.3,
            "yield_strength": 250.0,
            "metadata": {"accept_ideal_plasticity": True},
        },
        "analysis": "plasticity",
        "description": "ideal plastic limit load assumption",
        "expect_status": "IDEAL_PLASTIC_ASSUMPTION",
        "expect_compile": True,
        "expect_plastic": True,
        "expect_points": 1,
    },
    {
        "id": "hardening_user",
        "material": {
            "name": "LabHeat_42",
            "youngs_modulus": 200000.0,
            "poisson": 0.3,
            "yield_strength": 250.0,
            "hardening_table": ((250.0, 0.0), (300.0, 0.02)),
        },
        "analysis": "plasticity",
        "description": "user supplied hardening curve",
        "expect_status": "HARDENING_VERIFIED",
        "expect_compile": True,
        "expect_plastic": True,
        "expect_points": 2,
    },
)


def _plastic_block(text):
    lines = text.splitlines()
    block = []
    capturing = False
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("*PLASTIC"):
            capturing = True
            block = [stripped]
            continue
        if capturing:
            if stripped.startswith("*") or not stripped:
                break
            block.append(stripped)
    return block


def _run_case(spec):
    case_dir = WORK / spec["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    disposition = classify_material_input(
        spec["material"],
        analysis=spec["analysis"],
        description=spec["description"],
    )
    record = {
        "id": spec["id"],
        "disposition": disposition.status,
        "expected_disposition": spec["expect_status"],
        "disposition_ok": disposition.status == spec["expect_status"],
        "compile_ok": False,
        "deck_ok": False,
        "passed": False,
    }
    try:
        plan = compile_engineering_intent(
            _intent(spec["id"], spec["material"], spec["analysis"], spec["description"]),
            submit_job=False,
        )
    except Exception as exc:
        record["compile_error"] = "%s: %s" % (type(exc).__name__, exc)
        record["compile_ok"] = (not spec["expect_compile"]) and spec["expect_status"] in str(exc)
        record["deck_ok"] = not spec["expect_compile"]
        record["passed"] = record["disposition_ok"] and record["compile_ok"] and record["deck_ok"]
        return record

    if not spec["expect_compile"]:
        record["compile_error"] = "compile succeeded but this case must be refused"
        return record

    record["compile_ok"] = True
    record["job_name"] = plan.job_name
    script_path = case_dir / (spec["id"] + "_build.py")
    sentinel = case_dir / "script_end.flag"
    if sentinel.exists():
        sentinel.unlink()
    script_path.write_text(
        plan.cae_script + "\n" + completion_sentinel_code(str(sentinel)),
        encoding="utf-8",
    )
    executor = BatchExecutor(launcher=LAUNCHER, workdir=str(case_dir), timeout=900, settle_timeout=20.0)
    try:
        process = executor.run_nogui(str(script_path), timeout=900, completion_sentinel=str(sentinel))
    except Exception as exc:
        record["kernel_error"] = "%s: %s" % (type(exc).__name__, exc)
        record["traceback"] = traceback.format_exc()
        return record

    record["return_code"] = process.return_code
    record["settled"] = process.settled
    record["completion_evidence"] = process.completion_evidence
    record["duration_s"] = process.duration
    inp_path = case_dir / (plan.job_name + ".inp")
    record["inp_exists"] = inp_path.is_file()
    if not inp_path.is_file():
        record["stdout_tail"] = (process.stdout or "")[-1500:]
        record["stderr_tail"] = (process.stderr or "")[-1500:]
        return record

    text = inp_path.read_text(encoding="utf-8", errors="replace")
    plastic = _plastic_block(text)
    record["has_elastic"] = "*ELASTIC" in text.upper()
    record["has_plastic"] = bool(plastic)
    record["plastic_lines"] = plastic
    elastic_ok = record["has_elastic"]
    if spec["expect_plastic"]:
        plastic_ok = record["has_plastic"] and len(plastic) - 1 == spec["expect_points"]
        if spec["id"] == "hardening_user":
            strains = []
            for line in plastic[1:]:
                parts = [part.strip() for part in line.split(",") if part.strip()]
                if len(parts) >= 2:
                    strains.append(float(parts[1]))
            plastic_ok = plastic_ok and any(strain > 0.0 for strain in strains)
            record["plastic_strains"] = strains
    else:
        plastic_ok = not record["has_plastic"]
    record["deck_ok"] = (
        process.return_code == 0
        and process.settled
        and process.completion_evidence == "script_completed"
        and elastic_ok
        and plastic_ok
    )
    record["passed"] = record["disposition_ok"] and record["compile_ok"] and record["deck_ok"]
    return record


def main():
    if not os.path.isfile(LAUNCHER):
        raise SystemExit("Abaqus launcher missing: %s" % LAUNCHER)
    WORK.mkdir(parents=True, exist_ok=True)
    cases = [_run_case(spec) for spec in CASES]
    evidence = {
        "requirement": "REQ-4.8",
        "claim": (
            "Classifier disposition matches the deck Abaqus/CAE 2025 writes. "
            "This is not a solved plasticity qualification and not a catalog identification."
        ),
        "launcher": LAUNCHER,
        "solver_invoked": False,
        "cases": cases,
        "passed": all(item["passed"] for item in cases),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": evidence["passed"], "cases": [
        {key: item.get(key) for key in ("id", "disposition", "compile_ok", "deck_ok", "passed", "compile_error", "kernel_error")}
        for item in cases
    ]}, indent=2, ensure_ascii=False))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
