"""Backward compatibility redirection module for runtime_smoke."""

from .runtime_smoke import (
    RuntimeSmokeResult,
    B28HarnessResult,
    build_runtime_smoke_script,
    build_b28_smoke_script,
    classify_smoke_markers,
    classify_b28_markers,
    execute_runtime_smoke,
    execute_b28_smoke,
    parse_smoke_output,
    parse_b28_output,
)

__all__ = [
    "RuntimeSmokeResult",
    "B28HarnessResult",
    "build_runtime_smoke_script",
    "build_b28_smoke_script",
    "classify_smoke_markers",
    "classify_b28_markers",
    "execute_runtime_smoke",
    "execute_b28_smoke",
    "parse_smoke_output",
    "parse_b28_output",
]
