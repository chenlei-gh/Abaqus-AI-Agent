"""Isolated, persistent execution namespace for in-kernel agent code.

Golden/qualification scripts that run inside ``abaqus cae noGUI`` need to
``exec`` agent-compiled fragments while keeping their own bookkeeping safe.
The historical pattern — ``exec(code, globals(), globals())`` — let
``from abaqusConstants import *`` silently shadow harness variables (a
``SymbolicConstant`` named ``LOG`` destroyed a real validation log on
2026-10-27) and forced scripts to hand-clean a leaked ``result`` between
fragments.

``KernelNamespace`` is the reusable replacement:

- one persistent namespace per run, so later fragments can reference names
  defined by earlier fragments (cross-fragment persistence is a feature);
- harness bookkeeping never shares the namespace, so star imports and agent
  variables cannot clobber it;
- the ``result`` channel is cleared before each fragment and read after it,
  which is the same contract the legacy ``globals().pop("result")`` idiom
  implemented by hand.

The seed snippets run inside the namespace. In a real CAE kernel they are the
abaqus imports; in offline tests they can be any plain Python.
"""

import ast
import io
import sys
from typing import Iterable, Optional


class KernelNamespace:
    """Persistent agent namespace isolated from the caller's globals."""

    def __init__(self, seed_code: Iterable[str] = ()):
        self.namespace = {}
        for snippet in seed_code:
            exec(compile(snippet, "<kernel-seed>", "exec"), self.namespace, self.namespace)

    def execute(self, code: str, filename: str = "<agent>"):
        """Execute one fragment; return the agent result dict or stdout payload.

        Mirrors the legacy golden-script contract so migration is a drop-in:
        a dict bound to ``result`` wins; otherwise the last printed line is
        parsed as a literal dict; otherwise the captured stdout is returned.
        """
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            self.namespace.pop("result", None)
            exec(compile(code, filename, "exec"), self.namespace, self.namespace)
        finally:
            sys.stdout = old_stdout
        out = buf.getvalue().strip()
        res = self.namespace.get("result")
        if isinstance(res, dict):
            return res
        if out:
            last_line = out.splitlines()[-1].strip()
            try:
                val = ast.literal_eval(last_line)
                if isinstance(val, dict):
                    return val
            except Exception:
                pass
            return {"status": "COMPLETED", "stdout": out, "output": out}
        return {"status": "COMPLETED"}


def build_cae_seed() -> tuple:
    """The standard CAE-kernel seed: abaqus globals inside the namespace only."""
    return ("from abaqus import *", "from abaqusConstants import *")
