"""Actionable remedies for environment-misuse failures.

Three failure modes recur when driving Abaqus from a generic shell and cost a
full round-trip each time because the raw traceback names the symptom but not
the fix:

1. ``ModuleNotFoundError: No module named 'odbAccess'`` -- the script was run by
   the system Python instead of the interpreter bundled with Abaqus. ``odbAccess``
   only exists inside Abaqus' own Python runtime.
2. ``abaqus: command not found`` -- the SIMULIA ``Commands`` directory is often
   absent from ``PATH`` even when Abaqus is installed. The launcher must be
   referenced by absolute path.
3. ``UnicodeDecodeError: 'gbk' codec can't decode ...`` -- on Chinese-locale
   Windows the default text encoding is ``cp936``/GBK. Any file containing UTF-8
   non-ASCII bytes fails to open unless ``encoding="utf-8"`` is explicit.

Boundary: this module only classifies text that already failed. It never retries,
never rewrites the command, and never decides whether a run succeeded.
"""

from __future__ import annotations

import re
from typing import Optional

#: Shown only when no launcher can be discovered from PATH or the environment.
_UNRESOLVED_LAUNCHER = "abaqus"

_ODB_IMPORT_RE = re.compile(
    r"No module named '(?:odbAccess|abaqusConstants|abaqus|regionToolset|"
    r"part|step|section|material|mesh|assembly|visualization)'"
)

_COMMAND_NOT_FOUND_RE = re.compile(
    r"(?:command not found|is not recognized as an internal or external command|"
    r"No such file or directory)[^\n]*\babaqus\b"
    r"|\babaqus\b[^\n]*(?:command not found|is not recognized)",
    re.IGNORECASE,
)

_ENCODING_RE = re.compile(
    r"UnicodeDecodeError[^\n]*(?:gbk|cp936|cp1252|ascii|charmap)"
    r"|'(?:gbk|cp936)' codec can't decode"
    r"|codec can't decode byte"
    r"|UnicodeEncodeError[^\n]*'(?:gbk|cp936)'",
    re.IGNORECASE,
)


def _launcher() -> str:
    """Resolve a usable Abaqus launcher for the remedy text, best effort."""
    try:
        from .solver import find_abaqus_executable

        found = find_abaqus_executable()
        if found:
            return found
    except Exception:
        pass
    return _UNRESOLVED_LAUNCHER


def diagnose_environment(text: Optional[str], *, operation: str = "") -> str:
    """Return a one-line remedy for a recognised environment-misuse failure.

    Returns an empty string when the failure does not match a known environment
    problem, so callers can leave their existing diagnostics untouched.
    """
    if not text:
        return ""

    hints = []

    if _ODB_IMPORT_RE.search(text):
        hints.append(
            "Abaqus modules (odbAccess etc.) are unavailable to the system Python; "
            f"rerun the script with the Abaqus interpreter: \"{_launcher()}\" python <script>"
        )

    if _COMMAND_NOT_FOUND_RE.search(text):
        hints.append(
            "the SIMULIA Commands directory is not on PATH; invoke the launcher by "
            f"absolute path: \"{_launcher()}\" <command>"
        )

    if _ENCODING_RE.search(text):
        hints.append(
            "the file is UTF-8 but was opened with the cp936/GBK default; pass "
            "encoding=\"utf-8\" (optionally errors=\"replace\") when opening "
            "Abaqus text artifacts"
        )

    if not hints:
        return ""

    prefix = f"{operation}: " if operation else ""
    return prefix + "; ".join(hints)
