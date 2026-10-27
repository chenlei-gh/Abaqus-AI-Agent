"""Pre-solve execution candidate and human approval contract.

This module is the version-binding layer for the two-phase workflow:

    Phase A (no solver submission): compile inputs, build one
    ``ExecutionCandidate`` in ``PROPOSED`` state, render the
    ``PRE_SOLVE_REVIEW`` report, and wait for a human decision.

    Phase B (solver execution): the submission gate admits exactly one
    candidate whose status is ``APPROVED`` and whose re-computed content
    hashes still match the approved manifest. Any drift supersedes the
    candidate and forces a fresh review.

Scope boundary (read before extending):

- A hash here is tamper-evidence and version identity, NOT a keyed
  signature. ``ApprovalRecord.approved_by`` is a caller-supplied label;
  nothing in this contract proves who approved, nor can it stop someone
  with write access from recomputing digests. Do not describe approvals
  produced by this module as non-repudiable.
- This contract does not replace the run ledger
  (``execution.reconciliation``) or the post-solve evidence manifest
  (``contracts.evidence.EvidenceManifestV2``). The ledger answers "how
  far did the run get"; this contract answers "which exact version may
  execute". ``verify_deliverable`` semantics are untouched: an approval
  is not engineering acceptance and a review report is not a deliverable.
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

CANDIDATE_SCHEMA = "execution_candidate_v1"
CANDIDATE_FILENAME = "execution_candidate.json"

#: Fixed marker recorded in every approval payload so auditors can tell
#: content digests apart from identity assertions.
NOT_A_SIGNATURE_DISCLAIMER = (
    "SHA-256 digests identify content and detect drift; they are not keyed "
    "signatures and do not prove the identity of the approver."
)


class CandidateStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ApprovalError(RuntimeError):
    """Base class for candidate/approval contract violations."""


class CandidateStateError(ApprovalError):
    """Illegal lifecycle transition (e.g. approving a non-PROPOSED candidate)."""


class CandidateNotApprovedError(ApprovalError):
    """Submission was attempted without a matching APPROVED candidate."""


class CandidateDriftError(ApprovalError):
    """Submission was attempted after the approved content drifted."""

    def __init__(self, message: str, drift_reasons: Tuple[str, ...] = ()):
        super().__init__(message)
        self.drift_reasons = tuple(drift_reasons)


@dataclass(frozen=True)
class ApprovalRecord:
    """One explicit human approval bound to one candidate manifest digest."""

    candidate_id: str
    execution_manifest_hash: str
    approved_by: str
    approved_at: str
    action: str = "approve"
    review_report_hash: Optional[str] = None
    note: Optional[str] = None
    disclaimer: str = NOT_A_SIGNATURE_DISCLAIMER

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "execution_manifest_hash": self.execution_manifest_hash,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "action": self.action,
            "review_report_hash": self.review_report_hash,
            "note": self.note,
            "disclaimer": self.disclaimer,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ApprovalRecord":
        return cls(
            candidate_id=str(d.get("candidate_id") or ""),
            execution_manifest_hash=str(d.get("execution_manifest_hash") or ""),
            approved_by=str(d.get("approved_by") or ""),
            approved_at=str(d.get("approved_at") or ""),
            action=str(d.get("action") or "approve"),
            review_report_hash=d.get("review_report_hash"),
            note=d.get("note"),
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Deterministic serialization shared by all digest computations."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_solver_config_hash(config: Mapping[str, Any]) -> str:
    """Digest of solver/step settings that change execution semantics."""
    return hashlib.sha256(canonical_json(dict(config)).encode("utf-8")).hexdigest()


def compute_execution_manifest_hash(
    *,
    inp_sha256: str,
    dependency_hashes: Mapping[str, str],
    solver_config_hash: str,
    model_hash: Optional[str],
    intent_hash: Optional[str],
    action_plan_hash: Optional[str],
    generator_version: str,
) -> str:
    """Digest of everything that defines *what would be solved*.

    Approval state, timestamps, and the review report digest are excluded on
    purpose: approving a candidate must never change its manifest hash.
    """
    if not inp_sha256:
        raise ValueError("execution manifest requires the primary INP sha256")
    payload = {
        "schema": CANDIDATE_SCHEMA,
        "inp_sha256": inp_sha256,
        "dependency_hashes": dict(sorted((dependency_hashes or {}).items())),
        "solver_config_hash": solver_config_hash,
        "model_hash": model_hash,
        "intent_hash": intent_hash,
        "action_plan_hash": action_plan_hash,
        "generator_version": generator_version,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExecutionCandidate:
    """One reviewable, approvable, executable version of a run's inputs."""

    candidate_id: str
    run_id: str
    status: CandidateStatus
    inp_sha256: str
    solver_config_hash: str
    execution_manifest_hash: str
    generator_version: str
    created_at: str
    dependency_hashes: Dict[str, str] = field(default_factory=dict)
    model_hash: Optional[str] = None
    intent_hash: Optional[str] = None
    action_plan_hash: Optional[str] = None
    review_report_hash: Optional[str] = None
    approval: Optional[ApprovalRecord] = None
    superseded_by: Optional[str] = None
    schema: str = CANDIDATE_SCHEMA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
            "status": self.status.value,
            "inp_sha256": self.inp_sha256,
            "dependency_hashes": dict(self.dependency_hashes),
            "solver_config_hash": self.solver_config_hash,
            "execution_manifest_hash": self.execution_manifest_hash,
            "model_hash": self.model_hash,
            "intent_hash": self.intent_hash,
            "action_plan_hash": self.action_plan_hash,
            "generator_version": self.generator_version,
            "review_report_hash": self.review_report_hash,
            "created_at": self.created_at,
            "approval": self.approval.to_dict() if self.approval else None,
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ExecutionCandidate":
        approval_raw = d.get("approval")
        return cls(
            candidate_id=str(d.get("candidate_id") or ""),
            run_id=str(d.get("run_id") or ""),
            status=CandidateStatus(str(d.get("status") or "PROPOSED")),
            inp_sha256=str(d.get("inp_sha256") or ""),
            dependency_hashes=dict(d.get("dependency_hashes") or {}),
            solver_config_hash=str(d.get("solver_config_hash") or ""),
            execution_manifest_hash=str(d.get("execution_manifest_hash") or ""),
            model_hash=d.get("model_hash"),
            intent_hash=d.get("intent_hash"),
            action_plan_hash=d.get("action_plan_hash"),
            generator_version=str(d.get("generator_version") or ""),
            review_report_hash=d.get("review_report_hash"),
            created_at=str(d.get("created_at") or ""),
            approval=ApprovalRecord.from_dict(approval_raw) if isinstance(approval_raw, Mapping) else None,
            superseded_by=d.get("superseded_by"),
            schema=str(d.get("schema") or CANDIDATE_SCHEMA),
        )

    def verify_manifest_integrity(self) -> Tuple[bool, str]:
        """Recompute the manifest digest from the content fields.

        A persisted candidate whose content fields were edited without
        recomputing the digest is invalid and must not be approvable or
        submittable.
        """
        expected = compute_execution_manifest_hash(
            inp_sha256=self.inp_sha256,
            dependency_hashes=self.dependency_hashes,
            solver_config_hash=self.solver_config_hash,
            model_hash=self.model_hash,
            intent_hash=self.intent_hash,
            action_plan_hash=self.action_plan_hash,
            generator_version=self.generator_version,
        )
        if expected != self.execution_manifest_hash:
            return False, "manifest_hash_mismatch"
        return True, ""


def propose_candidate(
    *,
    candidate_id: str,
    run_id: str,
    inp_sha256: str,
    solver_config: Mapping[str, Any],
    generator_version: str,
    dependency_hashes: Optional[Mapping[str, str]] = None,
    model_hash: Optional[str] = None,
    intent_hash: Optional[str] = None,
    action_plan_hash: Optional[str] = None,
    created_at: Optional[str] = None,
) -> ExecutionCandidate:
    """Create a PROPOSED candidate. No solver submission may reference it yet."""
    if not candidate_id or not run_id:
        raise ValueError("candidate_id and run_id are required")
    solver_config_hash = compute_solver_config_hash(solver_config)
    manifest_hash = compute_execution_manifest_hash(
        inp_sha256=inp_sha256,
        dependency_hashes=dependency_hashes or {},
        solver_config_hash=solver_config_hash,
        model_hash=model_hash,
        intent_hash=intent_hash,
        action_plan_hash=action_plan_hash,
        generator_version=generator_version,
    )
    return ExecutionCandidate(
        candidate_id=candidate_id,
        run_id=run_id,
        status=CandidateStatus.PROPOSED,
        inp_sha256=inp_sha256,
        dependency_hashes=dict(dependency_hashes or {}),
        solver_config_hash=solver_config_hash,
        execution_manifest_hash=manifest_hash,
        model_hash=model_hash,
        intent_hash=intent_hash,
        action_plan_hash=action_plan_hash,
        generator_version=generator_version,
        created_at=created_at or _utc_now_iso(),
    )


def approve_candidate(
    candidate: ExecutionCandidate,
    *,
    approved_by: str,
    review_report_hash: Optional[str] = None,
    note: Optional[str] = None,
    approved_at: Optional[str] = None,
) -> ExecutionCandidate:
    """Approve a PROPOSED candidate, binding the decision to its manifest.

    The approval records the manifest digest it decided on; approving "the
    run" in the abstract is not representable here. Only a PROPOSED
    candidate can be approved, so a second approval click or a superseded
    version cannot silently re-arm execution.
    """
    if not approved_by or not approved_by.strip():
        raise ValueError("approved_by must name the approving subject")
    ok, reason = candidate.verify_manifest_integrity()
    if not ok:
        raise CandidateStateError(
            f"candidate '{candidate.candidate_id}' failed manifest integrity ({reason}); refusing approval"
        )
    if candidate.status is not CandidateStatus.PROPOSED:
        raise CandidateStateError(
            f"candidate '{candidate.candidate_id}' is {candidate.status.value}; only PROPOSED candidates can be approved"
        )
    record = ApprovalRecord(
        candidate_id=candidate.candidate_id,
        execution_manifest_hash=candidate.execution_manifest_hash,
        approved_by=approved_by.strip(),
        approved_at=approved_at or _utc_now_iso(),
        review_report_hash=review_report_hash or candidate.review_report_hash,
        note=note,
    )
    return replace(
        candidate,
        status=CandidateStatus.APPROVED,
        approval=record,
        review_report_hash=record.review_report_hash,
    )


def supersede_candidate(
    candidate: ExecutionCandidate,
    *,
    by_candidate_id: str,
) -> ExecutionCandidate:
    """Mark a candidate as replaced by a newer version.

    Any content/config drift must produce a NEW candidate and supersede the
    old one; mutating an APPROVED candidate in place is not representable.
    """
    if candidate.status is CandidateStatus.SUPERSEDED:
        raise CandidateStateError(
            f"candidate '{candidate.candidate_id}' is already SUPERSEDED"
        )
    if not by_candidate_id or by_candidate_id == candidate.candidate_id:
        raise ValueError("superseding candidate id must differ from the superseded one")
    return replace(candidate, status=CandidateStatus.SUPERSEDED, superseded_by=by_candidate_id)


def detect_drift(
    candidate: ExecutionCandidate,
    *,
    current_inp_sha256: str,
    current_dependency_hashes: Optional[Mapping[str, str]] = None,
    current_solver_config: Optional[Mapping[str, Any]] = None,
    current_generator_version: Optional[str] = None,
) -> Tuple[str, ...]:
    """Compare live content against the candidate. Empty tuple means no drift."""
    reasons = []
    if current_inp_sha256 != candidate.inp_sha256:
        reasons.append("inp_sha256_changed")
    if current_dependency_hashes is not None:
        expected = dict(candidate.dependency_hashes)
        current = dict(current_dependency_hashes)
        for path, digest in sorted(expected.items()):
            if current.get(path) != digest:
                reasons.append(f"dependency_changed:{path}")
        for path in sorted(set(current) - set(expected)):
            reasons.append(f"dependency_added:{path}")
    if current_solver_config is not None:
        if compute_solver_config_hash(current_solver_config) != candidate.solver_config_hash:
            reasons.append("solver_config_changed")
    if current_generator_version is not None and current_generator_version != candidate.generator_version:
        reasons.append("generator_version_changed")
    return tuple(reasons)


def assert_submittable(
    candidate: Optional[ExecutionCandidate],
    *,
    current_inp_sha256: str,
    current_dependency_hashes: Optional[Mapping[str, str]] = None,
    current_solver_config: Optional[Mapping[str, Any]] = None,
    current_generator_version: Optional[str] = None,
) -> ExecutionCandidate:
    """The submission gate predicate. Fail-closed on every ambiguity.

    Returns the APPROVED candidate when admission is granted; raises
    otherwise. Callers must treat any exception as "do not submit".
    """
    if candidate is None:
        raise CandidateNotApprovedError("no execution candidate is registered for this run")
    ok, reason = candidate.verify_manifest_integrity()
    if not ok:
        raise CandidateNotApprovedError(
            f"candidate '{candidate.candidate_id}' failed manifest integrity ({reason})"
        )
    if candidate.status is CandidateStatus.SUPERSEDED:
        raise CandidateNotApprovedError(
            f"candidate '{candidate.candidate_id}' was superseded by "
            f"'{candidate.superseded_by}'; the newer version needs its own review"
        )
    if candidate.status is not CandidateStatus.APPROVED:
        raise CandidateNotApprovedError(
            f"candidate '{candidate.candidate_id}' is {candidate.status.value}; "
            "human approval is required before solver submission"
        )
    approval = candidate.approval
    if approval is None or approval.execution_manifest_hash != candidate.execution_manifest_hash:
        raise CandidateNotApprovedError(
            f"candidate '{candidate.candidate_id}' approval record does not bind its manifest hash"
        )
    drift = detect_drift(
        candidate,
        current_inp_sha256=current_inp_sha256,
        current_dependency_hashes=current_dependency_hashes,
        current_solver_config=current_solver_config,
        current_generator_version=current_generator_version,
    )
    if drift:
        raise CandidateDriftError(
            f"approved candidate '{candidate.candidate_id}' no longer matches live content",
            drift_reasons=drift,
        )
    return candidate


# ---------------------------------------------------------------------------
# Persistence (atomic, per-run-workdir; not a parallel run ledger)
# ---------------------------------------------------------------------------

def candidate_path(workdir: Any) -> Path:
    return Path(workdir) / CANDIDATE_FILENAME


def _archive_path(workdir: Any, candidate_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in candidate_id)
    return Path(workdir) / f"execution_candidate.{safe}.json"


def write_candidate(workdir: Any, candidate: ExecutionCandidate) -> Path:
    """Atomically persist the candidate; archives any previous current file.

    The atomic replace gives crash safety for a single writer. It is NOT
    cross-process mutual exclusion: two concurrent approvers can both read
    PROPOSED and both write APPROVED. That race is harmless because the
    submission gate re-validates the persisted candidate at submit time and
    the run ledger/reconciliation layer owns exactly-once submission.
    """
    target = candidate_path(workdir)
    previous = load_candidate(workdir)
    if previous is not None and previous.candidate_id != candidate.candidate_id:
        archive = _archive_path(workdir, previous.candidate_id)
        try:
            os.replace(str(target), str(archive))
        except OSError:
            pass
    payload = candidate.to_dict()
    fd, tmp = tempfile.mkstemp(prefix=".execution_candidate.", suffix=".tmp", dir=str(workdir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        os.replace(tmp, str(target))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return target


def archive_candidate(workdir: Any, candidate: ExecutionCandidate) -> Path:
    """Persist a candidate to its id-keyed archive slot (kept for audit).

    Archives are append-only evidence: the current file may move on to a new
    version, but the exact record a human approved stays addressable.
    """
    target = _archive_path(workdir, candidate.candidate_id)
    fd, tmp = tempfile.mkstemp(prefix='.execution_candidate_archive.', suffix='.tmp', dir=str(workdir))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(candidate.to_dict(), fh, indent=2, sort_keys=True)
        os.replace(tmp, str(target))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return target


def load_candidate(workdir: Any) -> Optional[ExecutionCandidate]:
    """Load the current candidate, or None when none was ever registered.

    A file that fails to parse or whose manifest digest does not match its
    content is treated as absent-or-invalid: callers on the submission path
    must fail closed, so this function raises ``ApprovalError`` for a
    present-but-corrupt file instead of silently returning None.
    """
    path = candidate_path(workdir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        candidate = ExecutionCandidate.from_dict(raw)
    except (ValueError, TypeError, KeyError) as exc:
        raise ApprovalError(f"persisted execution candidate at '{path}' is unreadable: {exc}") from exc
    ok, reason = candidate.verify_manifest_integrity()
    if not ok:
        raise ApprovalError(
            f"persisted execution candidate at '{path}' failed manifest integrity ({reason})"
        )
    return candidate
