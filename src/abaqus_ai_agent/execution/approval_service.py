"""Pre-solve approval service: the single admission gate for solver submission.

Phase A builds an ``ExecutionCandidate`` (contracts.approval) bound to the
exact solver deck, its ``*INCLUDE`` dependencies, and the solver/step config,
then refuses submission until a human approves that candidate. Phase B
re-validates the approved candidate against freshly computed content hashes
immediately before the job is submitted.

Placement rules (see docs/presolve-approval-entry-matrix.md):

- The gate runs at the actual submission points (AnalysisRunner before
  ``JobController.submit``, the user-INP batch path, and the bare
  ``agent.submit``), never only in a caller.
- Approval state is a property of the candidate object, not of
  ``AnalysisRunState``. The run ledger keeps answering "how far did the run
  get"; this service answers "which exact version may execute".
- Candidates live beside the solver deck they bind (per-workdir, like the
  run ledger). A Phase B rerun must reuse the Phase A workdir so the
  approved candidate is found; the blocked-run diagnostics state the
  workdir and the exact approve command.
"""

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from ..contracts.approval import (
    ApprovalError,
    CandidateNotApprovedError,
    CandidateStatus,
    ExecutionCandidate,
    archive_candidate,
    assert_submittable,
    candidate_path,
    compute_execution_manifest_hash,
    compute_solver_config_hash,
    detect_drift,
    load_candidate,
    propose_candidate,
    supersede_candidate,
    write_candidate,
)

POLICY_REQUIRED = "required"
POLICY_DISABLED = "disabled"
POLICY_ENV_VAR = "ABAQUS_AI_AGENT_APPROVAL"
REVIEW_REPORT_FILENAME = "pre_solve_review.html"

_INCLUDE_RE = re.compile(r"^\s*\*INCLUDE\s*,\s*INPUT\s*=\s*([^,\s]+)", re.IGNORECASE)


class PreSolveApprovalRequired(ApprovalError):
    """Raised at the submission boundary while a candidate awaits approval."""

    def __init__(self, candidate: ExecutionCandidate, workdir: Any, message: Optional[str] = None):
        self.candidate = candidate
        self.workdir = str(workdir)
        detail = message or (
            "solver submission blocked: execution candidate "
            f"'{candidate.candidate_id}' is {candidate.status.value}. "
            f"Review '{REVIEW_REPORT_FILENAME}' in '{workdir}', then approve with: "
            f'python -m abaqus_ai_agent approve --workdir "{workdir}" --by <name>. '
            "Re-run with the same workdir afterwards; any content change "
            "supersedes the approval and forces a new review."
        )
        super().__init__(detail)


def resolve_approval_policy(explicit: Optional[str] = None, executor: Any = None) -> str:
    """Resolve the approval policy: explicit arg > env var > safe inference.

    Test doubles and explicit test mode resolve to ``disabled`` so the
    offline suite and CI keep running without a human in the loop. Real
    executors default to ``required``: fail-closed is the default, never an
    opt-in. The CI/Golden tool channel (tools/*.py via BatchExecutor) is
    physically separate from this service and documented in the entry matrix.
    """
    if explicit in (POLICY_REQUIRED, POLICY_DISABLED):
        return explicit
    env = os.environ.get(POLICY_ENV_VAR, "").strip().lower()
    if env in (POLICY_REQUIRED, POLICY_DISABLED):
        return env
    if os.environ.get("ABAQUS_AGENT_TEST_MODE", "").lower() in ("1", "true", "yes"):
        return POLICY_DISABLED
    if executor is None:
        return POLICY_DISABLED
    cname = type(executor).__name__
    if any(token in cname for token in ("Mock", "Fake", "Stub", "Dummy")):
        return POLICY_DISABLED
    if getattr(executor, "_is_mock", False) or getattr(executor, "is_test_mode", False):
        return POLICY_DISABLED
    return POLICY_REQUIRED


def generator_version() -> str:
    """Version identity of the code that produced the candidate content."""
    try:
        from .. import __version__
    except Exception:
        __version__ = "unknown"
    from ..contracts.approval import CANDIDATE_SCHEMA
    return f"abaqus-ai-agent {__version__} ({CANDIDATE_SCHEMA})"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_include_dependencies(inp_path: Any) -> Dict[str, str]:
    """Hash every ``*INCLUDE`` dependency of a solver deck.

    A missing include is a hard error: the candidate would otherwise bind a
    deck the solver cannot read, and "absent" must never hash to "approved".
    """
    inp_path = Path(inp_path)
    deps: Dict[str, str] = {}
    try:
        text = inp_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise CandidateNotApprovedError(
            f"cannot build execution candidate: solver deck '{inp_path}' unreadable ({exc})"
        ) from exc
    for line in text.splitlines():
        match = _INCLUDE_RE.match(line)
        if not match:
            continue
        include = match.group(1).strip().strip("'").strip('"')
        dep_path = Path(include)
        if not dep_path.is_absolute():
            dep_path = inp_path.parent / include
        if not dep_path.is_file():
            raise CandidateNotApprovedError(
                f"cannot build execution candidate: include dependency '{dep_path}' "
                f"referenced by '{inp_path.name}' is missing"
            )
        deps[str(dep_path)] = _sha256_file(dep_path)
    return deps


def _candidate_id(job_name: str, manifest_hash: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_name)
    return f"{safe}-{manifest_hash[:12]}"


def ensure_candidate(
    workdir: Any,
    *,
    job_name: str,
    inp_path: Any,
    solver_config: Mapping[str, Any],
    model_hash: Optional[str] = None,
    intent_hash: Optional[str] = None,
    action_plan_hash: Optional[str] = None,
    run_id: Optional[str] = None,
) -> ExecutionCandidate:
    """Register the current content as a candidate, superseding drifted ones.

    Idempotent for unchanged content: the same deck and config reproduce the
    same candidate id, so an approval survives process restarts and Phase B
    re-entry. Any drift creates a new PROPOSED candidate and archives the old
    one as SUPERSEDED; the old approval never transfers.
    """
    workdir = Path(workdir)
    inp_path = Path(inp_path)
    if not inp_path.is_file():
        raise CandidateNotApprovedError(
            f"cannot build execution candidate: solver deck '{inp_path}' does not exist"
        )
    inp_sha = _sha256_file(inp_path)
    deps = scan_include_dependencies(inp_path)
    gen_version = generator_version()
    manifest_hash = compute_execution_manifest_hash(
        inp_sha256=inp_sha,
        dependency_hashes=deps,
        solver_config_hash=compute_solver_config_hash(dict(solver_config)),
        model_hash=model_hash,
        intent_hash=intent_hash,
        action_plan_hash=action_plan_hash,
        generator_version=gen_version,
    )
    candidate = propose_candidate(
        candidate_id=_candidate_id(job_name, manifest_hash),
        run_id=str(run_id or job_name),
        inp_sha256=inp_sha,
        solver_config=dict(solver_config),
        generator_version=gen_version,
        dependency_hashes=deps,
        model_hash=model_hash,
        intent_hash=intent_hash,
        action_plan_hash=action_plan_hash,
    )
    assert candidate.execution_manifest_hash == manifest_hash
    current = load_candidate(workdir)
    if current is not None and current.execution_manifest_hash == candidate.execution_manifest_hash:
        return current
    if current is not None:
        superseded = current
        if current.status is not CandidateStatus.SUPERSEDED:
            superseded = supersede_candidate(current, by_candidate_id=candidate.candidate_id)
        archive_candidate(workdir, superseded)
        try:
            candidate_path(workdir).unlink()
        except OSError:
            pass
    write_candidate(workdir, candidate)
    return candidate


def review_report_hash(workdir: Any, filename: str = REVIEW_REPORT_FILENAME) -> Optional[str]:
    path = Path(workdir) / filename
    if not path.is_file():
        return None
    return _sha256_file(path)


def approve_current_candidate(
    workdir: Any,
    *,
    approved_by: str,
    note: Optional[str] = None,
    report_filename: str = REVIEW_REPORT_FILENAME,
) -> ExecutionCandidate:
    """Approve the current candidate of a workdir (the CLI entry point).

    Binds the review report digest when the report file exists, so the
    approval records which document the reviewer actually saw. Absence of
    the report is allowed but recorded as ``review_report_hash=None``.
    """
    from ..contracts.approval import approve_candidate

    candidate = load_candidate(workdir)
    if candidate is None:
        raise CandidateNotApprovedError(
            f"no execution candidate registered in '{workdir}'; run the analysis first "
            "so Phase A can produce one"
        )
    approved = approve_candidate(
        candidate,
        approved_by=approved_by,
        review_report_hash=review_report_hash(workdir, report_filename),
        note=note,
    )
    write_candidate(workdir, approved)
    return approved


def _import_project_approval(workdir: Path, candidate: "ExecutionCandidate") -> Optional["ExecutionCandidate"]:
    """Adopt an approval recorded for identical candidate content in a sibling
    run directory of the same project.

    Candidate ids are content-addressed (job name + manifest hash), so an
    approval recorded for the same candidate id in a sibling ``solver/<run>``
    dir is an approval of byte-identical content. The search is deliberately
    restricted to the ExternalProjectContext layout (parent dir named
    ``solver``) so arbitrary neighbouring directories are never scanned.
    Submission still has to pass ``assert_submittable`` against the deck bytes
    in THIS workdir, so a drifted deck cannot ride on an imported approval.
    """
    from dataclasses import replace as _dc_replace

    from ..contracts.approval import (
        CandidateStatus,
        load_candidate,
        write_candidate,
    )

    solver_root = workdir.parent
    if solver_root.name != "solver" or not solver_root.is_dir():
        return None
    for sibling_file in sorted(solver_root.glob("*/execution_candidate.json")):
        try:
            if sibling_file.parent.resolve() == workdir.resolve():
                continue
            other = load_candidate(sibling_file.parent)
        except Exception:
            continue
        if other is None:
            continue
        if other.candidate_id != candidate.candidate_id:
            continue
        if other.status is not CandidateStatus.APPROVED or other.approval is None:
            continue
        record = _dc_replace(
            other.approval,
            note=(
                (other.approval.note + " | " if other.approval.note else "")
                + f"approval adopted from sibling run dir: {sibling_file.parent.name}"
            ),
        )
        adopted = _dc_replace(
            candidate,
            status=CandidateStatus.APPROVED,
            approval=record,
            review_report_hash=record.review_report_hash,
        )
        write_candidate(workdir, adopted)
        return adopted
    return None


def enforce_pre_solve_approval(
    *,
    workdir: Any,
    job_name: str,
    solver_config: Mapping[str, Any],
    executor: Any = None,
    policy: Optional[str] = None,
    run_id: Optional[str] = None,
    model_hash: Optional[str] = None,
    intent_hash: Optional[str] = None,
    action_plan_hash: Optional[str] = None,
    ensure_deck: Any = None,
    inp_path: Any = None,
) -> Optional[ExecutionCandidate]:
    """The submission gate. Returns the admitted candidate or raises.

    ``ensure_deck`` is an optional zero-argument callable that (re)generates
    the solver deck when it is missing (e.g. CAE-session ``writeInput``); it
    runs before hashing so the candidate always binds real bytes. With the
    policy disabled the function returns None and touches nothing.
    """
    resolved = resolve_approval_policy(explicit=policy, executor=executor)
    if resolved == POLICY_DISABLED:
        return None
    workdir = Path(workdir)
    deck = Path(inp_path) if inp_path else workdir / f"{job_name}.inp"
    if not deck.is_file() and ensure_deck is not None:
        ensure_deck()
    candidate = ensure_candidate(
        workdir,
        job_name=job_name,
        inp_path=deck,
        solver_config=solver_config,
        model_hash=model_hash,
        intent_hash=intent_hash,
        action_plan_hash=action_plan_hash,
        run_id=run_id,
    )
    if candidate.status is not CandidateStatus.APPROVED:
        imported = _import_project_approval(workdir, candidate)
        if imported is not None:
            candidate = imported
    if candidate.status is not CandidateStatus.APPROVED:
        raise PreSolveApprovalRequired(candidate, workdir)
    return assert_submittable(
        candidate,
        current_inp_sha256=_sha256_file(deck),
        current_dependency_hashes=scan_include_dependencies(deck),
        current_solver_config=dict(solver_config),
        current_generator_version=generator_version(),
    )
