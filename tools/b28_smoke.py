#!/usr/bin/env python3
"""Run the B28 smoke harness through the host-side Abaqus CLI.

This is intentionally a thin runtime-validation adapter. It does not become
part of the Agent orchestration path: it generates the existing B28 harness
script, invokes ``abaqus cae noGUI=...`` through BatchExecutor, parses the
explicit markers, and writes an auditable JSON result.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.execution.b28_harness import build_b28_smoke_script, parse_b28_output
from abaqus_ai_agent.execution.batch import BatchExecutor


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the Abaqus V5 R2018/B28 smoke harness")
    parser.add_argument("--launcher", default=os.environ.get("ABAQUS_COMMAND", "abaqus"))
    parser.add_argument("--workdir", default=os.getcwd())
    parser.add_argument("--job-name", default="AIAgent_B28Smoke")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument(
        "--output",
        default=os.path.join("machine_validation", "b28_smoke.json"),
        help="JSON evidence output path (relative to --workdir unless absolute)",
    )
    args = parser.parse_args(argv)

    workdir = os.path.abspath(args.workdir)
    os.makedirs(workdir, exist_ok=True)
    validation_dir = os.path.join(workdir, "machine_validation")
    os.makedirs(validation_dir, exist_ok=True)

    script_path = os.path.join(validation_dir, args.job_name + "_script.py")
    with open(script_path, "w", encoding="utf-8") as handle:
        handle.write(build_b28_smoke_script(args.job_name))

    evidence = {
        "status": "fail",
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
        parsed = parse_b28_output((process.stdout or "") + "\n" + (process.stderr or ""))
        evidence.update({
            "command": list(process.command),
            "return_code": process.return_code,
            "process_succeeded": process.succeeded,
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
            },
            "stdout": process.stdout,
            "stderr": process.stderr,
        })
        evidence["status"] = "pass" if process.succeeded and parsed.passed else "fail"
    except (OSError, subprocess.SubprocessError) as exc:
        evidence.update({
            "process_succeeded": False,
            "error_class": exc.__class__.__name__,
            "error_message": str(exc),
        })

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path(workdir) / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(output_path), "w", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")

    summary = {
        "status": evidence["status"],
        "return_code": evidence.get("return_code"),
        "harness_passed": evidence.get("harness", {}).get("passed", False),
        "evidence": str(output_path),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
