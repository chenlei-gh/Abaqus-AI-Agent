"""Diagnostic pattern, attribution, remediation, and self-healing package."""

from .solver_patterns import (
    DiagnosticIssue,
    PATTERNS,
    diagnose_solver_artifacts,
)
from .remediator import SolverRemediator
from .orchestrator import SelfHealingOrchestrator

__all__ = [
    "DiagnosticIssue",
    "PATTERNS",
    "diagnose_solver_artifacts",
    "SolverRemediator",
    "SelfHealingOrchestrator",
]
