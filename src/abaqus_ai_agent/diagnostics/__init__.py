"""Diagnostic pattern and attribution package."""

from .solver_patterns import (
    DiagnosticIssue,
    PATTERNS,
    diagnose_solver_artifacts,
)

__all__ = [
    "DiagnosticIssue",
    "PATTERNS",
    "diagnose_solver_artifacts",
]
