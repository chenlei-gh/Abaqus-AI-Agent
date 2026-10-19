"""Deterministic diagnostic pattern library for Abaqus solver artifacts."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
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
        # Abaqus/Standard 2025 reports a chattering contact as status transitions
        # between iterations, e.g.
        #   "           45 POINTS CHANGED FROM CLOSED TO OPEN"
        #   "           22 POINTS CHANGED FROM STICKING TO SLIPPING"
        # The legacy phrases are kept because older/other releases and prior
        # captured artifacts may use them; they are not what this release emits.
        "regex": (
            r"(?i)points changed from "
            r"(?:closed to open|open to closed|sticking to slipping|slipping to sticking)"
            r"|severe contact overclosure|contact status changes"
        ),
        "severity": "WARNING",
        # Status transitions also occur a few times per run in jobs that converge.
        # Diagnosing chatter from the wording alone would make contact stabilization
        # fire on healthy models, so this pattern only applies once the job is known
        # to have failed.
        "requires_failure_evidence": True,
        "likely_cause": (
            "Chattering contact status between iterations (open/close oscillation)."
        ),
        "remediation": (
            "Use smoothed penalty contact, adjust contact damping/stabilization, or reduce initial increment."
        ),
    },
]


# Job states that are not a successful solve. Kept explicit so an unknown status is
# never silently treated as failure.
_FAILED_JOB_STATUSES = frozenset({
    "FAILED",
    "ERROR",
    "ABORTED",
    "TERMINATED",
    "EXECUTION_FAILED",
    "SOLVER_FAILED",
    "ODB_MISSING",
    "RESULT_INVALID",
})

# Terminal solver errors. Presence of any of these means the analysis did not
# complete, independent of what the caller reported as job status.
_TERMINAL_SOLVER_ERROR = re.compile(
    r"(?i)too many attempts made for this increment"
    r"|time increment required is less than the minimum specified"
    r"|the analysis has not been completed"
    r"|analysis cannot proceed"
)


def _failure_evidence_reason(msg_text: str, sta_text: str, job_status: Optional[str]) -> Optional[str]:
    """Return why the artifacts prove failure, or None when they do not.

    Three independent signals are accepted, because no single one is available in
    every call path: an explicit non-success ``job_status``, a ``.sta`` file that
    never reached successful completion, or a terminal solver error in ``.msg``.
    The message names the signal actually used so the audit trail cannot claim a
    status that was not what triggered the gate.

    A ``.sta`` that reached "COMPLETED SUCCESSFULLY" is the strongest evidence and
    vetoes the gate: real converged runs also emit a handful of status transitions,
    and a caller-supplied status must not turn a healthy run into a contact fix.
    """
    sta_upper = (sta_text or "").upper()
    if "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in sta_upper:
        return None

    status = (job_status or "").strip().upper()
    if status in _FAILED_JOB_STATUSES:
        return "job_status=%s" % status
    if sta_upper:
        return "sta: analysis not completed"
    if msg_text and _TERMINAL_SOLVER_ERROR.search(msg_text):
        return "msg: terminal solver error"
    return None


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

    failure_evidence: Optional[str] = None

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

        if not matched_lines:
            continue

        metadata: Dict[str, Any] = {}
        if p.get("requires_failure_evidence"):
            if failure_evidence is None:
                failure_evidence = _failure_evidence_reason(msg_text, sta_text, job_status)
            if not failure_evidence:
                continue
            metadata["failure_gated"] = True
            metadata["failure_evidence"] = failure_evidence

        issues.append(
            DiagnosticIssue(
                diagnosis_id=p["id"],
                severity=p["severity"],
                supporting_evidence=tuple(matched_lines[:10]),  # bounded evidence
                likely_cause=p["likely_cause"],
                suggested_remediation=p["remediation"],
                file_source=matched_source,
                metadata=metadata,
            )
        )

    return tuple(issues)


def _nset_sizes(inp_text: str) -> Dict[str, Optional[int]]:
    """Best-effort node-set sizes. Unparseable generate sets stay None and are not flagged."""
    sizes: Dict[str, Optional[int]] = {}
    current_name: Optional[str] = None
    generated = False
    count = 0
    known = True

    def _flush() -> None:
        if current_name is not None:
            sizes[current_name] = count if known else None

    for raw in (inp_text or "").splitlines():
        body = raw.split("**", 1)[0].strip()
        if not body:
            continue
        if body.startswith("*"):
            _flush()
            current_name = None
            if body.upper().startswith("*NSET"):
                name_match = re.search(r"nset\s*=\s*([^,\s]+)", body, re.IGNORECASE)
                if name_match:
                    current_name = name_match.group(1)
                    generated = "GENERATE" in body.upper()
                    count = 0
                    known = True
            continue
        if current_name is None:
            continue
        parts = [p.strip() for p in body.split(",") if p.strip()]
        if generated and len(parts) >= 2:
            try:
                start = int(float(parts[0]))
                end = int(float(parts[1]))
                step = int(float(parts[2])) if len(parts) > 2 else 1
                if step <= 0 or end < start:
                    known = False
                else:
                    count += ((end - start) // step) + 1
            except ValueError:
                known = False
        else:
            count += len(parts)
    _flush()
    return sizes


def _following_data(inp_text: str, header_line: str) -> List[str]:
    lines = (inp_text or "").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line == header_line)
    except StopIteration:
        return []
    data = []
    for line in lines[start + 1:]:
        body = line.split("**", 1)[0].strip()
        if not body:
            continue
        if body.startswith("*"):
            break
        data.append(body)
    return data


def extract_inp_element_types(inp_text: str = "") -> frozenset:
    """Return the set of element type codes declared in an inp deck.

    Public helper shared by the diagnose command and report reconciliation so
    both parse element types identically. Returns an empty frozenset when no
    *ELEMENT card is present. Codes are upper-cased (e.g. {"C3D4", "C3D8R"}).
    """
    upper = (inp_text or "").upper()
    return frozenset(
        re.findall(r"\*ELEMENT\s*,\s*TYPE\s*=\s*([A-Z0-9]+)", upper)
    )


def extract_inp_has_plasticity(inp_text: str = "") -> bool:
    """Return True when the deck defines any *PLASTIC hardening block."""
    return "*PLASTIC" in (inp_text or "").upper()


def read_job_inp_text(workdir=None, job_name=None, inp_path=None):
    """Read the job deck that was actually solved, if it is on disk.

    Prefers an explicit path, then ``<workdir>/<job_name>.inp``. Returns
    ``(text, source_path)`` or ``(None, None)``. Never raises: a missing or
    unreadable deck means the caller cannot apply a deck-dependent gate.
    """
    candidates = []
    if inp_path:
        candidates.append(inp_path)
    if workdir and job_name:
        candidates.append(os.path.join(str(workdir), "%s.inp" % job_name))
    for candidate in candidates:
        try:
            path = Path(candidate)
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="ignore"), str(path)
        except Exception:
            continue
    return None, None


def diagnose_inp_contract(inp_text: str = "", source: Optional[str] = None) -> Tuple[DiagnosticIssue, ...]:
    """Warn on model-contract smells seen in the MS13L bypass.

    Severity is WARNING. These checks must not fail a legitimate model that
    happens to use C3D4, a tie, or an elastic material for a different purpose.
    """
    text = inp_text or ""
    upper = text.upper()
    issues: List[DiagnosticIssue] = []

    element_types = set(re.findall(r"\*ELEMENT\s*,\s*TYPE\s*=\s*([A-Z0-9]+)", upper))
    has_static = "*STATIC" in upper
    has_load = any(token in upper for token in ("*CLOAD", "*DLOAD", "*DSLOAD"))
    if has_static and has_load and element_types == {"C3D4"}:
        issues.append(DiagnosticIssue(
            diagnosis_id="STATIC_BENDING_TET4_ONLY",
            severity="WARNING",
            supporting_evidence=("element type set is exactly C3D4 under *STATIC with applied load",),
            likely_cause=(
                "A static loaded model discretized only with linear tetrahedra can lock "
                "and mis-state bending stiffness."
            ),
            suggested_remediation=(
                "Do not treat C3D4-only bending results as deliverable without a higher-order "
                "or hex mesh check. This warning does not reject every C3D4 model."
            ),
            file_source=source or "inp",
        ))

    tie_names = re.findall(r"\*TIE\s*,\s*NAME\s*=\s*([^,\s]+)", text, re.IGNORECASE)
    encastre = "ENCASTRE" in upper or re.search(r",\s*1\s*,\s*6\s*$", text, re.MULTILINE) is not None
    pin_named = any(re.search(r"pin|\u9500", name, re.IGNORECASE) for name in tie_names)
    if tie_names and encastre and pin_named:
        issues.append(DiagnosticIssue(
            diagnosis_id="PIN_HOLE_TIED_AND_FIXED",
            severity="WARNING",
            supporting_evidence=tuple(tie_names[:5]),
            likely_cause=(
                "A pin-named tie combined with a fully fixed boundary can remove the mechanism "
                "the pin was supposed to allow."
            ),
            suggested_remediation=(
                "Confirm the pin is not both tied through the hole and fully fixed. "
                "Use a connector or contact if rotation is part of the requirement."
            ),
            file_source=source or "inp",
        ))

    large_sets = []
    try:
        sizes = _nset_sizes(text)
        for raw in text.splitlines():
            body = raw.split("**", 1)[0].strip()
            if not body.upper().startswith("*BOUNDARY"):
                continue
            for item in _following_data(text, raw):
                parts = [p.strip() for p in item.split(",")]
                if not parts:
                    continue
                fixed = any(token in item.upper() for token in ("ENCASTRE", "PINNED")) or (
                    len(parts) >= 3 and parts[1] == "1" and parts[2] == "6"
                )
                if not fixed:
                    continue
                size = sizes.get(parts[0])
                if size is not None and size > 200:
                    large_sets.append(f"{parts[0]}:{size}")
    except Exception:
        large_sets = []
    if large_sets:
        issues.append(DiagnosticIssue(
            diagnosis_id="OVERSIZED_FIXED_NODE_SET",
            severity="WARNING",
            supporting_evidence=tuple(large_sets[:10]),
            likely_cause="A fully fixed node set is large enough to over-constrain a mechanism or contact pair.",
            suggested_remediation="Review whether the fixed set is a support or an accidental weld of a moving surface.",
            file_source=source or "inp",
        ))

    claims_plastic = bool(re.search(r"elastoplastic|\u5f39\u5851\u6027|plasticity", text, re.IGNORECASE))
    if claims_plastic and "*PLASTIC" not in upper and "*ELASTIC" in upper:
        issues.append(DiagnosticIssue(
            diagnosis_id="ELASTIC_ONLY_CLAIMS_PLASTICITY",
            severity="WARNING",
            supporting_evidence=("*Elastic present, *Plastic absent, plasticity claimed in text",),
            likely_cause="The deck is linear-elastic while surrounding text claims elastoplastic behavior.",
            suggested_remediation="Add a *Plastic definition or stop claiming plasticity for this run.",
            file_source=source or "inp",
        ))

    return tuple(issues)
