"""Deterministic diagnostic pattern library for Abaqus solver artifacts."""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class DiagnosticIssue:
    """Structured, evidence-backed solver diagnostic issue."""
    diagnosis_id: str
    severity: str  # ERROR, WARNING, INFO
    supporting_evidence: Tuple[str, ...]
    likely_cause: str
    suggested_remediation: str
    file_source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "diagnosis_id": self.diagnosis_id,
            "severity": self.severity,
            "supporting_evidence": list(self.supporting_evidence),
            "likely_cause": self.likely_cause,
            "suggested_remediation": self.suggested_remediation,
            "file_source": self.file_source,
            "metadata": dict(self.metadata),
        }


# Deterministic pattern definitions
PATTERNS = [
    {
        "id": "NEGATIVE_EIGENVALUE",
        "regex": r"(?i)negative eigenvalue",
        "severity": "WARNING",
        "likely_cause": (
            "Stiffness matrix is non-positive definite; typically caused by "
            "unconstrained rigid body modes, material instability, or contact opening."
        ),
        "remediation": (
            "Check boundary conditions for unconstrained rigid body motions, "
            "verify contact stabilization, or check plasticity/hyperelasticity parameters."
        ),
    },
    {
        "id": "ZERO_PIVOT",
        "regex": r"(?i)zero pivot",
        "severity": "ERROR",
        "likely_cause": (
            "Numerical singularity during matrix factorization; unconstrained DOF "
            "or severe kinematic overconstraint."
        ),
        "remediation": (
            "Ensure all rigid parts and free nodes have adequate displacement/rotation constraints."
        ),
    },
    {
        "id": "TIME_INCREMENT_LESS_THAN_MINIMUM",
        "regex": r"(?i)time increment required is less than the minimum specified",
        "severity": "ERROR",
        "likely_cause": (
            "Severe convergence stagnation causing repeated cutbacks down to the "
            "specified minimum time increment."
        ),
        "remediation": (
            "Inspect convergence history in .msg file, reduce load rate, enable displacement/line search, "
            "or provide artificial damping/contact stabilization."
        ),
    },
    {
        "id": "TOO_MANY_CUTBACKS",
        "regex": r"(?i)too many attempts made for this increment",
        "severity": "ERROR",
        "likely_cause": (
            "Solver exceeded maximum cutback count without achieving equilibrium."
        ),
        "remediation": (
            "Inspect severity of residual force / displacement correction, check material softening, "
            "or relax cutback controls if physics are smooth."
        ),
    },
    {
        "id": "EXCESSIVE_DISTORTION",
        "regex": r"(?i)excessive distortion|distorted elements",
        "severity": "ERROR",
        "likely_cause": (
            "Finite elements underwent extreme distortion or negative Jacobian under high localized deformation."
        ),
        "remediation": (
            "Refine mesh locally, use reduced-integration or ALE adaptive meshing, "
            "or check for missing contact pair preventing excessive penetration."
        ),
    },
    {
        "id": "NUMERICAL_SINGULARITY",
        "regex": r"(?i)numerical singularity",
        "severity": "WARNING",
        "likely_cause": (
            "Ill-conditioned stiffness matrix near node or DOF."
        ),
        "remediation": (
            "Verify elastic modulus consistency, node connectivity, and tie constraints."
        ),
    },
    {
        "id": "LICENSE_DENIED",
        "regex": r"(?i)license.*denied|cannot connect to license server",
        "severity": "ERROR",
        "likely_cause": (
            "Abaqus licensing error; tokens unavailable or server unreachable."
        ),
        "remediation": (
            "Verify license server status and token availability; do not retry solver repeatedly."
        ),
    },
    {
        "id": "CONTACT_CHATTER",
        "regex": r"(?i)severe contact overclosure|contact status changes",
        "severity": "WARNING",
        "likely_cause": (
            "Chattering contact status between iterations (open/close oscillation)."
        ),
        "remediation": (
            "Use smoothed penalty contact, adjust contact damping/stabilization, or reduce initial increment."
        ),
    },
]


def diagnose_solver_artifacts(
    msg_text: str = "",
    sta_text: str = "",
    dat_text: str = "",
    log_text: str = "",
    job_status: Optional[str] = None,
) -> Tuple[DiagnosticIssue, ...]:
    """Diagnose real Abaqus solver text artifacts against deterministic patterns."""
    issues: List[DiagnosticIssue] = []

    text_sources = [
        ("msg", msg_text),
        ("sta", sta_text),
        ("dat", dat_text),
        ("log", log_text),
    ]

    for p in PATTERNS:
        pattern_re = re.compile(p["regex"])
        matched_lines = []
        matched_source = None

        for src_name, content in text_sources:
            if not content:
                continue
            for line in content.splitlines():
                if pattern_re.search(line):
                    matched_lines.append(line.strip())
                    if not matched_source:
                        matched_source = src_name

        if matched_lines:
            issues.append(
                DiagnosticIssue(
                    diagnosis_id=p["id"],
                    severity=p["severity"],
                    supporting_evidence=tuple(matched_lines[:10]),  # bounded evidence
                    likely_cause=p["likely_cause"],
                    suggested_remediation=p["remediation"],
                    file_source=matched_source,
                )
            )

    return tuple(issues)
