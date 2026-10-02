#!/usr/bin/env python3
"""Backward-compatibility wrapper forwarding to tools/runtime_smoke.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.runtime_smoke import BatchExecutor, main

if __name__ == "__main__":
    sys.exit(main())
