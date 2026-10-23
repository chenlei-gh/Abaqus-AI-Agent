"""Structured slicing of tool and process output for model context.

Governance Plan 阶段 2 第 2 项:

    success -> one sentence + elapsed time
    failure -> the deepest stack frame and the assertion line only

Rationale: a full subprocess stdout/stderr dump is the single largest avoidable
token sink on a failing Abaqus run, and the useful signal is concentrated in the
innermost frame. The full log is still an engineering artifact, so it is written
to disk and referenced by path rather than discarded.

Boundary: this module only reshapes text. It never decides whether a run itself
succeeded, and it does not touch solver or acceptance semantics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

#: Budget for a single failure message handed to the model.
MAX_FAILURE_CHARS = 1200
#: Budget for a success line. A success needs no diagnosis, so this is tight.
MAX_SUCCESS_CHARS = 300

_FRAME_RE = re.compile(
    r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+?)\s*$'
)
_EXC_RE = re.compile(
    r"^(?P<type>[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Exit|Interrupt)):\s*(?P<msg>.*)$"
)


@dataclass(frozen=True)
class FailureSlice:
    """Minimal, actionable view of a failure."""
    exception_type: str = ""
    exception_message: str = ""
    frame_file: str = ""
    frame_line: Optional[int] = None
    frame_function: str = ""
    assertion_line: str = ""
    evidence_path: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_message(self, max_chars: int = MAX_FAILURE_CHARS) -> str:
        parts: List[str] = []
        head = self.exception_type or "Failure"
        if self.exception_message:
            head = f"{head}: {self.exception_message}"
        parts.append(head)

        if self.frame_file:
            location = f"at {self.frame_file}"
            if self.frame_line is not None:
                location += f":{self.frame_line}"
            if self.frame_function:
                location += f" in {self.frame_function}"
            parts.append(location)

        if self.assertion_line:
            parts.append(f"assert: {self.assertion_line}")

        remedy = self.extra.get("remedy")
        if remedy:
            parts.append(f"remedy: {remedy}")

        if self.evidence_path:
            parts.append(f"full log: {self.evidence_path}")

        text = " | ".join(parts)
        if len(text) > max_chars:
            text = text[: max_chars - 3].rstrip() + "..."
        return text


def summarize_success(
    operation: str,
    elapsed_ms: float,
    detail: Optional[str] = None,
    max_chars: int = MAX_SUCCESS_CHARS,
) -> str:
    """One sentence plus elapsed time. Success needs no diagnostic payload."""
    text = f"{operation} succeeded in {elapsed_ms:.1f} ms"
    if detail:
        text += f" ({detail})"
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def parse_failure(text: str) -> FailureSlice:
    """Extract the deepest frame, the exception line and any assertion text."""
    if not text:
        return FailureSlice(exception_type="Failure", exception_message="empty output")

    lines = text.splitlines()

    frames: List[Dict[str, Any]] = []
    for line in lines:
        m = _FRAME_RE.match(line)
        if m:
            frames.append({
                "file": m.group("file"),
                "line": int(m.group("line")),
                "func": m.group("func"),
            })

    exc_type = ""
    exc_message = ""
    for line in reversed(lines):
        m = _EXC_RE.match(line.strip())
        if m:
            exc_type = m.group("type")
            exc_message = m.group("msg").strip()
            break

    assertion_line = ""
    assertion_error_line = ""
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("AssertionError"):
            assertion_error_line = stripped
            continue
        if stripped.startswith("assert ") or stripped.startswith("assert("):
            assertion_line = stripped
            break
        if "assert " in stripped and not stripped.startswith("#"):
            assertion_line = stripped
            break
    if not assertion_line:
        assertion_line = assertion_error_line

    deepest = frames[-1] if frames else {}
    return FailureSlice(
        exception_type=exc_type or "Failure",
        exception_message=exc_message,
        frame_file=str(deepest.get("file", "")),
        frame_line=deepest.get("line"),
        frame_function=str(deepest.get("func", "")),
        assertion_line=assertion_line,
    )


def persist_full_output(
    stdout: Optional[str],
    stderr: Optional[str],
    target: Path,
) -> Optional[Path]:
    """Write the complete stdout/stderr to disk so slicing loses no evidence."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write("=== STDOUT ===\n")
            f.write((stdout or "").rstrip() + "\n")
            f.write("=== STDERR ===\n")
            f.write((stderr or "").rstrip() + "\n")
        return target
    except OSError:
        return None


def build_failure_slice(
    *,
    returncode: Optional[int],
    stdout: Optional[str],
    stderr: Optional[str],
    operation: str,
    evidence_path: Optional[Path] = None,
) -> FailureSlice:
    """Compose the model-facing failure view from a completed process."""
    combined = "\n".join(x for x in (stderr or "", stdout or "") if x)
    base = parse_failure(combined)

    message = base.exception_message
    if not message and returncode is not None:
        message = f"{operation} exited with returncode {returncode}"

    extra: Dict[str, Any] = {"returncode": returncode} if returncode is not None else {}

    # Environment misuse (wrong interpreter, launcher off PATH, cp936 default)
    # is recoverable without touching the model, so surface the fix inline
    # instead of leaving only a bare traceback.
    from .environment_hints import diagnose_environment

    remedy = diagnose_environment(combined, operation=operation)
    if remedy:
        extra["remedy"] = remedy

    return FailureSlice(
        exception_type=base.exception_type,
        exception_message=message,
        frame_file=base.frame_file,
        frame_line=base.frame_line,
        frame_function=base.frame_function,
        assertion_line=base.assertion_line,
        evidence_path=str(evidence_path) if evidence_path else None,
        extra=extra,
    )


def slice_traceback_text(text: str, max_chars: int = MAX_FAILURE_CHARS) -> str:
    """Convenience: turn a raw traceback blob into a bounded failure message."""
    parsed = parse_failure(text)
    from .environment_hints import diagnose_environment

    remedy = diagnose_environment(text)
    if remedy:
        parsed = FailureSlice(
            exception_type=parsed.exception_type,
            exception_message=parsed.exception_message,
            frame_file=parsed.frame_file,
            frame_line=parsed.frame_line,
            frame_function=parsed.frame_function,
            assertion_line=parsed.assertion_line,
            evidence_path=parsed.evidence_path,
            extra={**parsed.extra, "remedy": remedy},
        )
    return parsed.to_message(max_chars=max_chars)
