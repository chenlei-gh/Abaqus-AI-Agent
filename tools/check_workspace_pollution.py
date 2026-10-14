"""Fail if tests or tool runs left protected repository paths dirty.

Protected paths:
- tracked machine_validation JSON
- deliverables/
- runs/

Ignored solver artifacts that were never tracked are not a commit failure by
themselves. This script checks git status, so an untracked diagnostic report
or a rewritten evidence bundle still fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.evidence_guard import EvidenceRewriteError, assert_workspace_unpolluted


def main() -> int:
    try:
        violations = assert_workspace_unpolluted(ROOT)
    except EvidenceRewriteError as exc:
        print(f"workspace pollution check failed: {exc}")
        return 2
    if violations:
        print("workspace pollution check failed:")
        for item in violations:
            print(f"  {item}")
        return 1
    print("workspace pollution check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
