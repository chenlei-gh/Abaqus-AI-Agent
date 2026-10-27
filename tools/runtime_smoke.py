#!/usr/bin/env python3
"""Run the live Abaqus runtime smoke harness through the host-side Abaqus CLI.

This is intentionally a thin runtime-validation adapter. It generates the
runtime smoke script, invokes ``abaqus cae noGUI=...`` through BatchExecutor,
parses the explicit markers, and writes an auditable JSON result.
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.execution.runtime_smoke import build_runtime_smoke_script, parse_smoke_output
from abaqus_ai_agent.execution.batch import BatchExecutor


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the live Abaqus runtime smoke harness")
    parser.add_argument("--launcher", default=os.environ.get("ABAQUS_COMMAND", "abaqus"))
    parser.add_argument(
        "--workdir",
        default=os.path.join(str(ROOT), "runs", "runtime_smoke_run"),
    )
    parser.add_argument("--job-name", default="AIAgent_RuntimeSmoke")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument(
        "--output",
        default=os.path.join(str(ROOT), "machine_validation", "runtime_smoke.json"),
        help="JSON evidence output path",
    )
    args = parser.parse_args(argv)

    workdir = os.path.abspath(args.workdir)
    os.makedirs(workdir, exist_ok=True)
    run_id = uuid.uuid4().hex[:12]
    script_path = os.path.join(workdir, args.job_name + "_script.py")
    with open(script_path, "w", encoding="utf-8") as handle:
        handle.write(build_runtime_smoke_script(args.job_name, run_id=run_id))

    evidence = {
        # Missing-evidence is itself a verdict: if this file is absent or this
        # default survives, the run never produced a defensible result.
        "status": "fail",
        "run_id": run_id,
        "launcher": args.launcher,
        "workdir": workdir,
        "script": os.path.abspath(script_path),
    }

    try:
        executor = BatchExecutor(
            launcher=args.launcher,
            workdir=workdir,
            timeout=args.timeout,
        )
        process = executor.run_nogui(script_path, timeout=args.timeout)
        combined_output = (process.stdout or "") + "\n" + (process.stderr or "")
        parsed = parse_smoke_output(combined_output, expected_run_id=run_id)
        rpy_diagnostics = []
        if not parsed.passed:
            # Fallback to inspecting abaqus.rpy in workdir if CAE captured
            # stdout. The fallback is bound to THIS run_id: a stale .rpy from
            # a previous run is diagnostic material, never a pass.
            for rpy in sorted(Path(workdir).glob("abaqus.rpy*"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    content = rpy.read_text(encoding="utf-8", errors="replace")
                    fallback_parsed = parse_smoke_output(content, expected_run_id=run_id)
                    rpy_diagnostics.append({
                        "rpy": str(rpy),
                        "passed": fallback_parsed.passed,
                        "invalid_reasons": list(fallback_parsed.invalid_reasons),
                    })
                    if fallback_parsed.passed:
                        parsed = fallback_parsed
                        break
                except Exception as exc:
                    rpy_diagnostics.append({"rpy": str(rpy), "read_error": str(exc)})
        evidence.update({
            "command": list(process.command),
            "return_code": process.return_code,
            "process_succeeded": process.succeeded,
            "artifacts_settled": getattr(process, "settled", None),
            "harness": {
                "passed": parsed.passed,
                "script_completed": parsed.script_completed,
                "model_created": parsed.model_created,
                "input_written": parsed.input_written,
                "job_submitted": parsed.job_submitted,
                "job_completed": parsed.job_completed,
                "odb_exists": parsed.odb_exists,
                "odb_opened": parsed.odb_opened,
                "required_outputs_present": parsed.required_outputs_present,
                "error_class": parsed.error_class,
                "error_message": parsed.error_message,
                "invalid_reasons": list(parsed.invalid_reasons),
            },
            "rpy_fallback": rpy_diagnostics,
            "stdout": process.stdout,
            "stderr": process.stderr,
        })
        # Launcher exit is process-level evidence only. A run whose artifacts
        # never settled after the launcher exited has no terminal proof.
        settled = getattr(process, "settled", True)
        evidence["status"] = "pass" if (process.succeeded and settled and parsed.passed) else "fail"
    except Exception as exc:
        # Broad on purpose: stall/timeout errors (SolverProcessStalledError is a
        # RuntimeError), launch failures and unexpected defects must ALL leave
        # classified evidence instead of skipping the JSON write.
        evidence.update({
            "process_succeeded": False,
            "error_class": exc.__class__.__name__,
            "error_message": str(exc),
        })

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: a half-written JSON is indistinguishable from corruption to
    # a later reader, so the swap goes through a temp file.
    tmp_output = output_path.with_name(output_path.name + ".tmp")
    with open(str(tmp_output), "w", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(str(tmp_output), str(output_path))

    summary = {
        "status": evidence["status"],
        "run_id": run_id,
        "return_code": evidence.get("return_code"),
        "harness_passed": evidence.get("harness", {}).get("passed", False),
        "evidence": str(output_path),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
