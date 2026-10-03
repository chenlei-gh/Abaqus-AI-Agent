import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .analysis_run import AnalysisRun, AnalysisRunState
from .jobs import JobState, JobStatus


class RecoveryVerdict(str, Enum):
    """Deterministic verdict on how to recover an interrupted or failed AnalysisRun."""

    COMPLETED_READY = "completed_ready"
    RECOVERABLE_RECONNECT = "recoverable_reconnect"
    NON_RECOVERABLE_RESUBMIT = "non_recoverable_resubmit"
    CLEANUP_FAILED = "cleanup_failed"


@dataclass(frozen=True)
class RunRecoveryInspection:
    verdict: RecoveryVerdict
    job_name: str
    workdir: str
    has_lock: bool
    lock_files: List[str]
    has_odb: bool
    odb_size: int
    sta_status: str
    msg_error_count: int
    reason: str
    recommended_action: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value if hasattr(self.verdict, "value") else str(self.verdict),
            "job_name": self.job_name,
            "workdir": self.workdir,
            "has_lock": self.has_lock,
            "lock_files": list(self.lock_files),
            "has_odb": self.has_odb,
            "odb_size": self.odb_size,
            "sta_status": self.sta_status,
            "msg_error_count": self.msg_error_count,
            "reason": self.reason,
            "recommended_action": self.recommended_action,
            "metadata": dict(self.metadata),
        }


def inspect_run_state(workdir: str, job_name: str) -> RunRecoveryInspection:
    """Inspect solver artifacts (.lck, .odb, .sta, .msg) in workdir to determine recovery strategy."""
    abs_workdir = os.path.abspath(workdir)
    lock_files = []
    lck_path = os.path.join(abs_workdir, f"{job_name}.lck")
    if os.path.exists(lck_path):
        lock_files.append(lck_path)

    # General .lck check
    if os.path.exists(abs_workdir):
        for f in os.listdir(abs_workdir):
            if f.endswith(".lck") and f not in lock_files:
                lock_files.append(os.path.join(abs_workdir, f))

    odb_path = os.path.join(abs_workdir, f"{job_name}.odb")
    has_odb = os.path.exists(odb_path)
    odb_size = os.path.getsize(odb_path) if has_odb else 0

    sta_path = os.path.join(abs_workdir, f"{job_name}.sta")
    sta_status = "MISSING"
    if os.path.exists(sta_path):
        try:
            with open(sta_path, "r", errors="ignore") as f:
                lines = f.readlines()
            sta_tail = "\n".join(lines[-20:]).upper()
            if "COMPLETED SUCCESSFULLY" in sta_tail or "ANALYSIS COMPLETED" in sta_tail:
                sta_status = "COMPLETED"
            elif "ERROR" in sta_tail or "ABORTED" in sta_tail:
                sta_status = "ABORTED"
            else:
                sta_status = "IN_PROGRESS"
        except Exception:
            sta_status = "UNREADABLE"

    msg_path = os.path.join(abs_workdir, f"{job_name}.msg")
    msg_error_count = 0
    if os.path.exists(msg_path):
        try:
            with open(msg_path, "r", errors="ignore") as f:
                content = f.read()
            msg_error_count = len(re.findall(r"\*\*\*ERROR|\*\*\*FATAL", content, re.IGNORECASE))
        except Exception:
            pass

    # Recovery verdict reasoning
    if sta_status == "COMPLETED" and has_odb and odb_size > 0 and not lock_files:
        return RunRecoveryInspection(
            verdict=RecoveryVerdict.COMPLETED_READY,
            job_name=job_name,
            workdir=abs_workdir,
            has_lock=False,
            lock_files=[],
            has_odb=True,
            odb_size=odb_size,
            sta_status=sta_status,
            msg_error_count=msg_error_count,
            reason="Solver finished normally; complete ODB available without active locks",
            recommended_action="Validate ODB and extract metrics directly without resubmission",
        )

    if (sta_status in ("COMPLETED", "IN_PROGRESS") or not lock_files) and has_odb and odb_size > 1024:
        # Reconnectable run
        return RunRecoveryInspection(
            verdict=RecoveryVerdict.RECOVERABLE_RECONNECT,
            job_name=job_name,
            workdir=abs_workdir,
            has_lock=len(lock_files) > 0,
            lock_files=lock_files,
            has_odb=True,
            odb_size=odb_size,
            sta_status=sta_status,
            msg_error_count=msg_error_count,
            reason="Partial or finished ODB detected with recoverable artifacts",
            recommended_action="Reconnect to existing ODB and inspect field/history outputs",
        )

    return RunRecoveryInspection(
        verdict=RecoveryVerdict.NON_RECOVERABLE_RESUBMIT,
        job_name=job_name,
        workdir=abs_workdir,
        has_lock=len(lock_files) > 0,
        lock_files=lock_files,
        has_odb=has_odb,
        odb_size=odb_size,
        sta_status=sta_status,
        msg_error_count=msg_error_count,
        reason="Solver crashed, corrupted, aborted, or ODB incomplete; locks require cleanup",
        recommended_action="Clear stale .lck files and resubmit fresh job",
    )


def recover_and_resume(
    run: AnalysisRun,
    workdir: str,
) -> Tuple[AnalysisRun, RunRecoveryInspection]:
    """Execute recovery actions deterministically and update AnalysisRun state."""
    inspection = inspect_run_state(workdir, run.job_name)
    metadata = dict(run.metadata)
    metadata["recovery_inspection"] = inspection.to_dict()

    if inspection.verdict == RecoveryVerdict.COMPLETED_READY:
        odb_path = os.path.join(workdir, f"{run.job_name}.odb")
        updated_run = run.with_state(
            AnalysisRunState.ODB_VALIDATED,
            odb_path=odb_path,
            job_status=JobStatus(name=run.job_name, state=JobState.COMPLETED),
            metadata=metadata,
        )
        return updated_run, inspection

    elif inspection.verdict == RecoveryVerdict.RECOVERABLE_RECONNECT:
        odb_path = os.path.join(workdir, f"{run.job_name}.odb")
        updated_run = run.with_state(
            AnalysisRunState.RUNNING if inspection.has_lock else AnalysisRunState.ODB_VALIDATED,
            odb_path=odb_path,
            metadata=metadata,
        )
        return updated_run, inspection

    elif inspection.verdict == RecoveryVerdict.NON_RECOVERABLE_RESUBMIT:
        # Clear stale locks
        cleaned_locks = 0
        for lck in inspection.lock_files:
            try:
                if os.path.exists(lck):
                    os.remove(lck)
                    cleaned_locks += 1
            except OSError:
                pass
        metadata["cleaned_locks_count"] = cleaned_locks
        updated_run = run.with_state(
            AnalysisRunState.PREFLIGHTED,
            metadata=metadata,
        )
        return updated_run, inspection

    else:
        updated_run = run.with_state(
            AnalysisRunState.FAILED,
            metadata=metadata,
        )
        return updated_run, inspection
