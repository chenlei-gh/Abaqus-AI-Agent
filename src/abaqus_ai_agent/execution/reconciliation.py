"""State Reconciliation and Life-Cycle Recovery Dispatcher.

Fulfills Recovery Contract A: Zero-Trust physical inspection prior to resumption.
Never assumes the snapshot ledger is true on its own.
Dispatches deterministic recovery actions:
  - READ_ONLY_RECOVER
  - RECONNECT_LIVE
  - CLEANUP_AND_RESUBMIT
  - RECOVERY_REQUIRED (Conflict / Fail-Closed blocker)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .recovery import RecoveryVerdict, inspect_run_state, is_lock_active, is_pid_alive


class ReconciliationAction(str, Enum):
    """Deterministic verdict on how to handle an interrupted or prior task run."""

    READ_ONLY_RECOVER = "read_only_recover"
    RECONNECT_LIVE = "reconnect_live"
    CLEANUP_AND_RESUBMIT = "cleanup_and_resubmit"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True)
class RunSnapshot:
    """Serializable light-weight execution snapshot for cross-session resumption."""

    task_id: str
    run_id: str
    phase: str
    job_name: str
    sandbox_dir: str
    git_head_commit: Optional[str] = None
    git_is_dirty: bool = False
    pid: Optional[int] = None
    odb_path: Optional[str] = None
    last_saved_timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "phase": self.phase,
            "job_name": self.job_name,
            "sandbox_dir": str(self.sandbox_dir),
            "git_head_commit": self.git_head_commit,
            "git_is_dirty": self.git_is_dirty,
            "pid": self.pid,
            "odb_path": str(self.odb_path) if self.odb_path else None,
            "last_saved_timestamp": self.last_saved_timestamp,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RunSnapshot:
        return cls(
            task_id=str(data.get("task_id", "")),
            run_id=str(data.get("run_id", "")),
            phase=str(data.get("phase", "UNKNOWN")),
            job_name=str(data.get("job_name", "")),
            sandbox_dir=str(data.get("sandbox_dir", "")),
            git_head_commit=data.get("git_head_commit"),
            git_is_dirty=bool(data.get("git_is_dirty", False)),
            pid=int(data["pid"]) if data.get("pid") is not None else None,
            odb_path=data.get("odb_path"),
            last_saved_timestamp=float(data.get("last_saved_timestamp", time.time())),
            metadata=dict(data.get("metadata", {})),
        )

    def save_atomic(self, target_path: Union[str, Path]) -> Path:
        """Write snapshot atomically via a temp file and os.replace."""
        resolved = Path(target_path).resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = resolved.parent / f"{resolved.name}.tmp_{uuid.uuid4().hex[:8]}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, resolved)
        return resolved

    @classmethod
    def load(cls, source_path: Union[str, Path]) -> RunSnapshot:
        resolved = Path(source_path).resolve()
        with open(resolved, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


@dataclass(frozen=True)
class ReconciliationReport:
    """Detailed result of physical reality verification against snapshot state."""

    action: ReconciliationAction
    is_blocked: bool
    conflict_reasons: Tuple[str, ...]
    recommended_action: str
    snapshot: Optional[RunSnapshot]
    git_drift_detected: bool
    live_pid: bool
    live_lock: bool
    sta_status: str
    workdir: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "is_blocked": self.is_blocked,
            "conflict_reasons": list(self.conflict_reasons),
            "recommended_action": self.recommended_action,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "git_drift_detected": self.git_drift_detected,
            "live_pid": self.live_pid,
            "live_lock": self.live_lock,
            "sta_status": self.sta_status,
            "workdir": self.workdir,
            "metadata": dict(self.metadata),
        }


def get_current_git_status(repo_root: Optional[Union[str, Path]] = None) -> Tuple[Optional[str], bool]:
    """Retrieve current (commit_sha, is_dirty) for repo_root."""
    root = Path(repo_root).resolve() if repo_root else Path.cwd()
    if not (root / ".git").exists():
        return None, False
    try:
        head_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5.0,
            check=False,
        )
        head_sha = head_proc.stdout.strip() if head_proc.returncode == 0 else None

        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5.0,
            check=False,
        )
        is_dirty = bool(status_proc.stdout.strip()) if status_proc.returncode == 0 else False
        return head_sha, is_dirty
    except Exception:
        return None, False


def reconcile_run_state(
    snapshot_or_path: Optional[Union[RunSnapshot, str, Path]] = None,
    *,
    fallback_workdir: Optional[Union[str, Path]] = None,
    job_name: Optional[str] = None,
    repo_root: Optional[Union[str, Path]] = None,
    allow_git_drift: bool = False,
) -> ReconciliationReport:
    """Execute 5-probe zero-trust reconciliation between snapshot and physical reality.

    Probes:
      1. Git tree consistency (detect uncommitted changes or checkout drift).
      2. PID kernel aliveness probe.
      3. File-level .lck lock contention probe.
      4. Solver tail examination (.sta and .msg status).
      5. ODB integrity and presence check.
    """
    snapshot: Optional[RunSnapshot] = None
    if isinstance(snapshot_or_path, RunSnapshot):
        snapshot = snapshot_or_path
    elif snapshot_or_path:
        p = Path(snapshot_or_path)
        if p.is_file():
            try:
                snapshot = RunSnapshot.load(p)
            except Exception:
                snapshot = None

    eff_workdir = ""
    eff_job_name = job_name or ""
    if snapshot:
        eff_workdir = snapshot.sandbox_dir
        if not eff_job_name:
            eff_job_name = snapshot.job_name
    elif fallback_workdir:
        eff_workdir = str(fallback_workdir)

    conflicts: List[str] = []

    # If no snapshot and no physical workdir exists, we cannot reconcile
    if not eff_workdir or not os.path.exists(eff_workdir):
        return ReconciliationReport(
            action=ReconciliationAction.RECOVERY_REQUIRED,
            is_blocked=True,
            conflict_reasons=("missing_snapshot_and_workdir",),
            recommended_action="Cannot recover: workspace directory not found.",
            snapshot=snapshot,
            git_drift_detected=False,
            live_pid=False,
            live_lock=False,
            sta_status="MISSING",
            workdir=eff_workdir,
        )

    # 1. Probe 1: Git tree consistency
    git_drift = False
    current_head, current_dirty = get_current_git_status(repo_root)
    if snapshot and snapshot.git_head_commit and current_head:
        if snapshot.git_head_commit != current_head:
            git_drift = True
            if not allow_git_drift:
                conflicts.append(
                    f"git_commit_drift: snapshot on {snapshot.git_head_commit[:8]} but current HEAD is {current_head[:8]}"
                )

    # 2. Probe 2: PID kernel check
    pid = snapshot.pid if snapshot else None
    live_pid = is_pid_alive(pid) if pid else False

    # 3. Probe 3: Lock file inspection
    lck_file = os.path.join(eff_workdir, f"{eff_job_name}.lck") if eff_job_name else None
    live_lock = False
    if lck_file and os.path.exists(lck_file):
        live_lock = is_lock_active(lck_file, associated_pid=pid)

    # 4. Probe 4 & 5: Tail status and ODB presence via recovery inspection
    inspection = inspect_run_state(eff_workdir, eff_job_name)
    sta_status = inspection.sta_status
    has_valid_odb = inspection.has_odb and inspection.odb_size > 1024

    # Evaluate physical conflicts against snapshot expectations
    if snapshot:
        if snapshot.phase == "COMPLETED" and not has_valid_odb:
            conflicts.append("snapshot_claims_completed_but_odb_missing_or_empty")
        if snapshot.phase == "COMPLETED" and sta_status not in ("COMPLETED", "MISSING"):
            conflicts.append(f"snapshot_claims_completed_but_sta_is_{sta_status}")
        if snapshot.phase == "RUNNING" and not live_pid and not live_lock and sta_status != "COMPLETED":
            conflicts.append("snapshot_claims_running_but_solver_process_is_dead")

    # Decision Matrix
    # Case A: Git Drift or critical conflicting evidence -> Fail-Closed Block
    if git_drift and not allow_git_drift:
        return ReconciliationReport(
            action=ReconciliationAction.RECOVERY_REQUIRED,
            is_blocked=True,
            conflict_reasons=tuple(conflicts),
            recommended_action="Blocked by code drift. Align workspace git commit before resuming.",
            snapshot=snapshot,
            git_drift_detected=True,
            live_pid=live_pid,
            live_lock=live_lock,
            sta_status=sta_status,
            workdir=eff_workdir,
        )

    # Case B: Analysis completed normally with authentic ODB and no locks
    if sta_status == "COMPLETED" and has_valid_odb and not live_lock:
        return ReconciliationReport(
            action=ReconciliationAction.READ_ONLY_RECOVER,
            is_blocked=False,
            conflict_reasons=tuple(conflicts),
            recommended_action="Solver completed. Proceed directly with result extraction without re-solving.",
            snapshot=snapshot,
            git_drift_detected=False,
            live_pid=live_pid,
            live_lock=False,
            sta_status=sta_status,
            workdir=eff_workdir,
            metadata={"odb_size": inspection.odb_size},
        )

    # Case C: Process is actively executing with live PID or live lock
    if live_pid or live_lock:
        return ReconciliationReport(
            action=ReconciliationAction.RECONNECT_LIVE,
            is_blocked=False,
            conflict_reasons=tuple(conflicts),
            recommended_action="Solver process is active. Reconnect watchdog to monitor ongoing execution.",
            snapshot=snapshot,
            git_drift_detected=False,
            live_pid=live_pid,
            live_lock=live_lock,
            sta_status=sta_status,
            workdir=eff_workdir,
        )

    # Case D: Dead process with stale lock or aborted analysis
    if sta_status in ("ABORTED", "IN_PROGRESS") or not has_valid_odb:
        rec_action = ReconciliationAction.CLEANUP_AND_RESUBMIT
        rec_reason = "Solver crashed, aborted, or was terminated abnormally. Clear stale locks and resubmit."
        # If there were strict contradictions, block instead
        if "snapshot_claims_completed_but_odb_missing_or_empty" in conflicts:
            rec_action = ReconciliationAction.RECOVERY_REQUIRED
            rec_reason = "Contradiction: Snapshot marked completed but ODB artifact is missing. Manual review needed."

        return ReconciliationReport(
            action=rec_action,
            is_blocked=(rec_action == ReconciliationAction.RECOVERY_REQUIRED),
            conflict_reasons=tuple(conflicts),
            recommended_action=rec_reason,
            snapshot=snapshot,
            git_drift_detected=False,
            live_pid=False,
            live_lock=False,
            sta_status=sta_status,
            workdir=eff_workdir,
            metadata={"msg_errors": inspection.msg_error_count},
        )

    # Fallback
    return ReconciliationReport(
        action=ReconciliationAction.RECOVERY_REQUIRED,
        is_blocked=True,
        conflict_reasons=tuple(conflicts or ["unrecognized_physical_state"]),
        recommended_action="Unknown state combination. Requires manual inspection.",
        snapshot=snapshot,
        git_drift_detected=False,
        live_pid=live_pid,
        live_lock=live_lock,
        sta_status=sta_status,
        workdir=eff_workdir,
    )
