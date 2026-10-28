"""Host-side Python syntax gate for scripts about to enter Abaqus.

``preflight_plan()`` checks action structure. This module checks Python syntax
of a source that already exists, before ``abaqus cae noGUI`` or a kernel
``execute()`` is invoked. It is not an API checker and not a physics checker:
``compile(..., "exec")`` only answers "would CPython parse this".

Missing files are not a syntax failure. Existing ``run_nogui`` callers pass
paths that the watchdog, not this gate, is responsible for.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScriptSyntaxError:
    """One syntax failure that must not start Abaqus."""

    path: str
    line: Optional[int]
    offset: Optional[int]
    message: str
    excerpt: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "offset": self.offset,
            "message": self.message,
            "excerpt": self.excerpt,
            "category": "syntax",
        }

    def format(self) -> str:
        where = self.path
        if self.line is not None:
            where = "%s:%s" % (where, self.line)
        return "syntax error in %s: %s | %s" % (where, self.message, self.excerpt)


def check_python_source(source: str, filename: str) -> Optional[ScriptSyntaxError]:
    """Return a structured error when ``source`` is not valid Python 3.

    A successful compile returns ``None``. This never executes the source.
    """
    name = filename or "<script>"
    try:
        compile(source, name, "exec")
    except SyntaxError as exc:
        line_no = exc.lineno
        excerpt = (exc.text or "").strip()
        if not excerpt and line_no:
            lines = source.splitlines()
            if 1 <= line_no <= len(lines):
                excerpt = lines[line_no - 1].strip()
        return ScriptSyntaxError(
            path=name,
            line=line_no,
            offset=exc.offset,
            message=exc.msg or str(exc),
            excerpt=excerpt[:240],
        )
    except ValueError as exc:
        # compile() raises ValueError for embedded null bytes. That is still a
        # source defect that must not be handed to the CAE launcher.
        return ScriptSyntaxError(
            path=name,
            line=None,
            offset=None,
            message=str(exc),
            excerpt="",
        )
    return None


def check_script_file(path: str) -> Optional[ScriptSyntaxError]:
    """Check an on-disk script. Missing or non-Python paths are not blocked.

    Only an existing ``.py`` whose source fails ``compile()`` is a gate failure.
    Callers that pass a path the watchdog is expected to discover keep that
    contract.
    """
    if not path or not str(path).lower().endswith(".py"):
        return None
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()
    except OSError:
        # Unreadable is a launcher/filesystem problem, not a syntax verdict.
        return None
    return check_python_source(source, os.path.abspath(path))
