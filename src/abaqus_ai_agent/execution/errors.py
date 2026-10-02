import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class NormalizedExecutionError:
    """Structured, normalized runtime error representation."""
    execution_id: str
    category: str
    message: str
    source_line: Optional[int] = None
    code_excerpt: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    traceback: Optional[str] = None
    abaqus_context: Dict[str, Any] = field(default_factory=dict)
    recovery_hint: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "category": self.category,
            "message": self.message,
            "source_line": self.source_line,
            "code_excerpt": self.code_excerpt,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "traceback": self.traceback,
            "abaqus_context": dict(self.abaqus_context),
            "recovery_hint": self.recovery_hint,
            "timestamp": self.timestamp,
        }


class AbaqusExecutionError(RuntimeError):
    def __init__(self, message, *, payload=None, category="execution", traceback=None,
                 source_line=None, code_excerpt=None, context=None, recovery_hint=None):
        super().__init__(message)
        self.payload = payload
        self.category = category
        self.traceback = traceback
        self.source_line = source_line
        self.code_excerpt = code_excerpt
        self.context = context or {}
        self.recovery_hint = recovery_hint or get_recovery_hint(category)

    def diagnostic(self):
        return {"category": self.category, "message": str(self), "traceback": self.traceback,
                "source_line": self.source_line, "code_excerpt": self.code_excerpt,
                "context": self.context, "recovery_hint": self.recovery_hint}


class AbaqusConnectionError(AbaqusExecutionError):
    def __init__(self, message, *, payload=None, **kwargs):
        super().__init__(message, payload=payload, category="connection", **kwargs)


def classify_execution_error(message, payload=None):
    low = str(message or "").lower()
    markers = (("syntax", "syntax"), ("license", "license"), ("timeout", "timeout"),
               ("attributeerror", "abaqus_api"), ("typeerror", "abaqus_api"),
               ("keyerror", "object_missing"), ("indexerror", "object_missing"),
               ("region", "region_invalid"), ("set not found", "region_invalid"),
               ("solver", "solver"), ("odb", "odb"))
    for marker, category in markers:
        if marker in low:
            return category
    return "execution"


def recovery_hint(category):
    return get_recovery_hint(category)


def get_recovery_hint(category):
    return {
        "syntax": "Inspect the generated code around the reported source line before retrying.",
        "abaqus_api": "Check the API signature against the detected Abaqus release before retrying.",
        "object_missing": "Refresh ModelSnapshot and verify the referenced object still exists.",
        "region_invalid": "Re-ground the region or validate the named region before retrying.",
        "license": "Check the required Abaqus license/token availability; do not retry blindly.",
        "solver": "Inspect the job/solver diagnostics and ODB/log state before retrying.",
        "odb": "Verify ODB path, job completion and ODB readability.",
        "timeout": "Inspect job state before retrying; a timeout does not prove solver failure.",
        "connection": "Check the local bridge process and connection before retrying.",
        "execution": "Inspect the structured error payload and current model state before retrying.",
    }.get(category, "Inspect the structured error payload and current model state before retrying.")


def normalize_runtime_error(
    error: Any,
    execution_id: Optional[str] = None,
    stdout: Optional[str] = None,
    stderr: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> NormalizedExecutionError:
    """Normalize any runtime exception or payload into a deterministic NormalizedExecutionError."""
    exec_id = execution_id or "exec-unknown"
    if isinstance(error, AbaqusExecutionError):
        cat = error.category or classify_execution_error(str(error), error.payload)
        hint = error.recovery_hint or get_recovery_hint(cat)
        ctx = dict(error.context or {})
        if context:
            ctx.update(context)
        return NormalizedExecutionError(
            execution_id=exec_id,
            category=cat,
            message=str(error),
            source_line=error.source_line,
            code_excerpt=error.code_excerpt,
            stdout=stdout,
            stderr=stderr,
            traceback=error.traceback,
            abaqus_context=ctx,
            recovery_hint=hint,
        )
    msg = str(error)
    cat = classify_execution_error(msg)
    hint = get_recovery_hint(cat)
    return NormalizedExecutionError(
        execution_id=exec_id,
        category=cat,
        message=msg,
        stdout=stdout,
        stderr=stderr,
        abaqus_context=dict(context or {}),
        recovery_hint=hint,
    )
