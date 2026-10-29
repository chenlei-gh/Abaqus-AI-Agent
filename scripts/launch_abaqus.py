#!/usr/bin/env python3
"""Launch Abaqus with cwd fixed to the project workdir.

Abaqus writes abaqus.rpy, abaqusN.rec, acis_tmp.dbg, and temp-*.sat into the
process cwd. The Zed agent directory is the parent of this checkout. Starting
CAE there drops those files beside the repository. This wrapper always starts
in <repo>/workdir.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "src"))
    from abaqus_ai_agent.execution.batch import resolve_default_launcher
    from abaqus_ai_agent.paths import resolve_project_workdir

    workdir = resolve_project_workdir()
    launcher = resolve_default_launcher("abaqus")
    command = [launcher, *argv]
    completed = subprocess.run(command, cwd=str(workdir), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
