"""Tests for State Reconciliation and Zero-Trust Task Recovery Matrix (TC-REC-01 to TC-REC-06)."""

import json
import os
from pathlib import Path
import pytest

from abaqus_ai_agent.execution.reconciliation import (
    ReconciliationAction,
    ReconciliationReport,
    RunSnapshot,
    default_ledger_path,
    load_snapshot,
    reconcile_run_state,
    resume_from_ledger,
    write_snapshot,
)


def _setup_mock_sandbox(tmp_path: Path, job_name: str = "Job-Test"):
    sdir = tmp_path / "sandbox"
    sdir.mkdir(parents=True, exist_ok=True)
    return sdir


# The reconciliation probe delegates ODB validation to ``is_authentic_binary_odb``,
# which rejects uniformly filled files because no real ODB is a constant byte run.
# Fixtures therefore need a non-uniform head and tail, not zero padding alone.
_STRUCTURED_ODB_HEAD = b"\x7fSIMULIA\x00\x01\x02\x03"


def _write_structured_odb(path: Path, size: int = 8192) -> Path:
    payload = _STRUCTURED_ODB_HEAD + b"\x00" * (size - len(_STRUCTURED_ODB_HEAD) - 1) + b"\x01"
    path.write_bytes(payload)
    return path


def test_tc_rec_01_reconnect_live(tmp_path, monkeypatch):
    """TC-REC-01: Live process with held lock returns RECONNECT_LIVE."""
    sdir = _setup_mock_sandbox(tmp_path)
    job_name = "Job-Live"
    lck_path = sdir / f"{job_name}.lck"
    lck_path.write_text("lock_content")

    # Mock PID alive and lock active
    monkeypatch.setattr("abaqus_ai_agent.execution.reconciliation.is_pid_alive", lambda pid: True)
    monkeypatch.setattr("abaqus_ai_agent.execution.reconciliation.is_lock_active", lambda path, associated_pid=None: True)

    snapshot = RunSnapshot(
        task_id="TASK-01",
        run_id="RUN-01",
        phase="RUNNING",
        job_name=job_name,
        sandbox_dir=str(sdir),
        pid=12345,
    )

    report = reconcile_run_state(snapshot, allow_git_drift=True)
    assert report.action == ReconciliationAction.RECONNECT_LIVE
    assert not report.is_blocked
    assert report.live_pid is True
    assert report.live_lock is True
    assert "Reconnect watchdog" in report.recommended_action


def test_tc_rec_02_silent_completion_read_only(tmp_path, monkeypatch):
    """TC-REC-02: Job finished during absence (.sta completed, ODB present) -> READ_ONLY_RECOVER."""
    sdir = _setup_mock_sandbox(tmp_path)
    job_name = "Job-Done"

    sta_path = sdir / f"{job_name}.sta"
    sta_path.write_text("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")

    odb_path = sdir / f"{job_name}.odb"
    _write_structured_odb(odb_path)

    monkeypatch.setattr("abaqus_ai_agent.execution.reconciliation.is_pid_alive", lambda pid: False)
    monkeypatch.setattr("abaqus_ai_agent.execution.reconciliation.is_lock_active", lambda path, associated_pid=None: False)

    snapshot = RunSnapshot(
        task_id="TASK-02",
        run_id="RUN-02",
        phase="COMPLETED",
        job_name=job_name,
        sandbox_dir=str(sdir),
        odb_path=str(odb_path),
        pid=99999,
    )

    report = reconcile_run_state(snapshot, allow_git_drift=True)
    assert report.action == ReconciliationAction.READ_ONLY_RECOVER
    assert not report.is_blocked
    assert report.sta_status == "COMPLETED"
    assert "Proceed directly with result extraction" in report.recommended_action


def test_tc_rec_03_dead_process_with_stale_lock(tmp_path, monkeypatch):
    """TC-REC-03: Dead solver with stale lock and incomplete job -> CLEANUP_AND_RESUBMIT.

    The verdict alone is not enough: the zombie ``.lck`` left by a hard kill must
    actually be removed, otherwise the resubmitted job starts against a lock that
    looks permanently held.
    """
    sdir = _setup_mock_sandbox(tmp_path)
    job_name = "Job-Crashed"

    lck_path = sdir / f"{job_name}.lck"
    lck_path.write_text("stale_lock")

    sta_path = sdir / f"{job_name}.sta"
    sta_path.write_text("STEP 1 INCREMENT 1 ...\n")  # Unfinished

    monkeypatch.setattr("abaqus_ai_agent.execution.reconciliation.is_pid_alive", lambda pid: False)
    monkeypatch.setattr("abaqus_ai_agent.execution.reconciliation.is_lock_active", lambda path, associated_pid=None: False)

    snapshot = RunSnapshot(
        task_id="TASK-03",
        run_id="RUN-03",
        phase="RUNNING",
        job_name=job_name,
        sandbox_dir=str(sdir),
        pid=4567,
    )

    report = reconcile_run_state(snapshot, allow_git_drift=True)
    assert report.action == ReconciliationAction.CLEANUP_AND_RESUBMIT
    assert not report.is_blocked
    assert "Clear stale locks and resubmit" in report.recommended_action

    # Stale lock must be gone and the cleanup result recorded.
    assert not lck_path.exists(), "stale .lck survived the cleanup path"
    assert report.metadata["lock_present_before"] is True
    assert report.metadata["lock_released"] is True
    assert report.metadata["cleaned_locks_count"] == 1


def test_tc_rec_03b_live_lock_is_never_deleted(tmp_path, monkeypatch):
    """TC-REC-03 (negative): a lock proven live must survive cleanup and block resubmit."""
    sdir = _setup_mock_sandbox(tmp_path)
    job_name = "Job-Locked"

    lck_path = sdir / f"{job_name}.lck"
    lck_path.write_text("held_by_live_solver")
    (sdir / f"{job_name}.sta").write_text("STEP 1 INCREMENT 1 ...\n", encoding="utf-8")

    monkeypatch.setattr("abaqus_ai_agent.execution.reconciliation.is_pid_alive", lambda pid: False)

    # Probe 3 (reconciliation namespace) sees no holder, but the barrier inside
    # ``clean_stale_locks`` re-probes in the recovery namespace and finds one.
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.recovery.is_lock_active",
        lambda path, associated_pid=None: True,
    )

    snapshot = RunSnapshot(
        task_id="TASK-03B",
        run_id="RUN-03B",
        phase="RUNNING",
        job_name=job_name,
        sandbox_dir=str(sdir),
        pid=55555,
    )

    report = reconcile_run_state(snapshot, allow_git_drift=True)

    assert lck_path.exists(), "a live lock was deleted during cleanup"
    assert report.action == ReconciliationAction.RECOVERY_REQUIRED
    assert report.is_blocked is True
    assert report.metadata["lock_present_after"] is True
    assert report.metadata["lock_release_failure"] == "lock_still_active"
    assert "still holds it" in report.recommended_action


def test_tc_rec_04_git_commit_drift_blocks(tmp_path, monkeypatch):
    """TC-REC-04: Git commit changed during execution -> RECOVERY_REQUIRED (Fail-Closed)."""
    sdir = _setup_mock_sandbox(tmp_path)
    job_name = "Job-Drift"

    monkeypatch.setattr(
        "abaqus_ai_agent.execution.reconciliation.get_current_git_status",
        lambda repo_root: ("commit_beef_2222", False),
    )

    snapshot = RunSnapshot(
        task_id="TASK-04",
        run_id="RUN-04",
        phase="RUNNING",
        job_name=job_name,
        sandbox_dir=str(sdir),
        git_head_commit="commit_dead_1111",  # Mismatch!
    )

    report = reconcile_run_state(snapshot, allow_git_drift=False)
    assert report.action == ReconciliationAction.RECOVERY_REQUIRED
    assert report.is_blocked is True
    assert report.git_drift_detected is True
    assert any("git_commit_drift" in r for r in report.conflict_reasons)
    assert "Blocked by code drift" in report.recommended_action


def test_unconfirmable_odb_never_authorizes_read_only_recovery(tmp_path, monkeypatch):
    """A .sta that claims completion cannot outvote a corrupt ODB.

    Probes 4 and 5 are evaluated independently and the ODB verdict is
    fail-closed: when the artifact cannot be confirmed, the run is never routed
    to READ_ONLY_RECOVER, because that path hands results to the caller as if a
    solve had produced them.
    """
    sdir = _setup_mock_sandbox(tmp_path)
    job_name = "Job-Corrupt"

    (sdir / f"{job_name}.sta").write_text(
        "THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n", encoding="utf-8"
    )
    # All-zero artifact: right size, no record structure.
    (sdir / f"{job_name}.odb").write_bytes(b"\x00" * 8192)

    monkeypatch.setattr("abaqus_ai_agent.execution.reconciliation.is_pid_alive", lambda pid: False)
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.reconciliation.is_lock_active",
        lambda path, associated_pid=None: False,
    )

    # (a) No ledger to salvage from: resubmission is allowed, silent reuse is not.
    report = reconcile_run_state(
        snapshot_or_path=None,
        fallback_workdir=str(sdir),
        job_name=job_name,
        allow_git_drift=True,
    )
    assert report.action != ReconciliationAction.READ_ONLY_RECOVER
    assert report.metadata["odb_authentic_prefilter"] is False

    # (b) A ledger claiming COMPLETED against this artifact is a contradiction:
    #     block for manual review instead of offering a resubmit.
    snapshot = RunSnapshot(
        task_id="TASK-CORRUPT",
        run_id="RUN-CORRUPT",
        phase="COMPLETED",
        job_name=job_name,
        sandbox_dir=str(sdir),
        odb_path=str(sdir / f"{job_name}.odb"),
    )
    blocked = reconcile_run_state(snapshot, allow_git_drift=True)
    assert blocked.action == ReconciliationAction.RECOVERY_REQUIRED
    assert blocked.is_blocked is True
    assert "snapshot_claims_completed_but_odb_missing_or_empty" in blocked.conflict_reasons
    # A refused run must not have mutated the workspace.
    assert (sdir / f"{job_name}.odb").exists()


def test_tc_rec_05_missing_snapshot_but_valid_sandbox(tmp_path, monkeypatch):
    """TC-REC-05: Snapshot json lost, but sandbox has completed job -> salvage via READ_ONLY_RECOVER."""
    sdir = _setup_mock_sandbox(tmp_path)
    job_name = "Job-Salvage"

    sta_path = sdir / f"{job_name}.sta"
    sta_path.write_text("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")

    odb_path = sdir / f"{job_name}.odb"
    _write_structured_odb(odb_path)

    monkeypatch.setattr("abaqus_ai_agent.execution.reconciliation.is_lock_active", lambda path, associated_pid=None: False)

    report = reconcile_run_state(
        snapshot_or_path=None,
        fallback_workdir=str(sdir),
        job_name=job_name,
        allow_git_drift=True,
    )

    assert report.action == ReconciliationAction.READ_ONLY_RECOVER
    assert not report.is_blocked
    assert report.sta_status == "COMPLETED"


def test_tc_rec_06_atomic_snapshot_persistence(tmp_path):
    """TC-REC-06: Atomic snapshot write via temp file and os.replace protects from corrupt writes."""
    state_file = tmp_path / ".state" / "run_lifecycle.json"
    snapshot = RunSnapshot(
        task_id="TASK-06",
        run_id="RUN-06",
        phase="PREFLIGHTED",
        job_name="Job-Atomic",
        sandbox_dir=str(tmp_path / "sandbox"),
        git_head_commit="761af9fc",
        pid=8888,
        metadata={"priority": "high"},
    )

    saved_path = snapshot.save_atomic(state_file)
    assert saved_path.is_file()

    # Load and verify integrity
    loaded = RunSnapshot.load(saved_path)
    assert loaded.task_id == "TASK-06"
    assert loaded.job_name == "Job-Atomic"
    assert loaded.git_head_commit == "761af9fc"
    assert loaded.pid == 8888
    assert loaded.metadata == {"priority": "high"}


def test_tc_rec_06b_failed_replace_preserves_previous_snapshot(tmp_path, monkeypatch):
    """TC-REC-06 (fault injection): a mid-swap failure must not damage the ledger.

    ``os.replace`` failing is the worst realistic case: the temp file is already
    written, so a naive implementation would either truncate the ledger or leave
    debris that a later run mistakes for a partial snapshot.
    """
    state_file = tmp_path / ".state" / "run_lifecycle.json"
    original = RunSnapshot(
        task_id="TASK-06B-OLD",
        run_id="RUN-06B-OLD",
        phase="SOLVING",
        job_name="Job-Atomic-Old",
        sandbox_dir=str(tmp_path / "sandbox"),
        pid=1111,
        metadata={"attempt": 1},
    )
    original.save_atomic(state_file)
    original_bytes = state_file.read_bytes()

    def failing_replace(src, dst):
        raise OSError("simulated power loss during atomic swap")

    monkeypatch.setattr("abaqus_ai_agent.execution.reconciliation.os.replace", failing_replace)

    replacement = RunSnapshot(
        task_id="TASK-06B-NEW",
        run_id="RUN-06B-NEW",
        phase="COMPLETED",
        job_name="Job-Atomic-New",
        sandbox_dir=str(tmp_path / "sandbox"),
        pid=2222,
        metadata={"attempt": 2},
    )

    with pytest.raises(OSError, match="simulated power loss"):
        replacement.save_atomic(state_file)

    # (a) The previous snapshot is byte-for-byte intact and still parseable.
    assert state_file.read_bytes() == original_bytes
    surviving = RunSnapshot.load(state_file)
    assert surviving.task_id == "TASK-06B-OLD"
    assert surviving.phase == "SOLVING"

    # (b) No temp file is left behind for a later load to trip over.
    residue = [p.name for p in state_file.parent.iterdir() if p.name != state_file.name]
    assert residue == [], f"atomic write left temp residue: {residue}"


def test_ledger_path_lives_under_state_directory(tmp_path):
    """The canonical ledger path is <root>/.state/run_lifecycle.json, not the repo root."""
    assert default_ledger_path(tmp_path) == tmp_path.resolve() / ".state" / "run_lifecycle.json"


def test_write_and_load_snapshot_roundtrip(tmp_path):
    """write_snapshot persists atomically and load_snapshot reads it back identically."""
    sdir = tmp_path / "sandbox"
    sdir.mkdir()
    snapshot = RunSnapshot(
        task_id="TASK-RT",
        run_id="RUN-RT",
        phase="RUNNING",
        job_name="Job-RT",
        sandbox_dir=str(sdir),
        pid=4321,
    )

    ledger = default_ledger_path(tmp_path)
    written = write_snapshot(snapshot, ledger)

    assert written == ledger
    assert ledger.is_file()
    # No temp residue may survive the atomic replace.
    assert [p.name for p in ledger.parent.iterdir()] == ["run_lifecycle.json"]

    loaded = load_snapshot(ledger)
    assert loaded is not None
    assert loaded.task_id == "TASK-RT"
    assert loaded.pid == 4321


def test_load_snapshot_tolerates_missing_and_corrupt_ledger(tmp_path):
    """A missing ledger yields None; a corrupt one is not trusted either."""
    assert load_snapshot(None) is None
    assert load_snapshot(tmp_path / ".state" / "run_lifecycle.json") is None

    ledger = default_ledger_path(tmp_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{not valid json", encoding="utf-8")
    assert load_snapshot(ledger) is None


def test_resume_from_ledger_reconnects_live_job(tmp_path, monkeypatch):
    """Cross-session resume reads the ledger but still defers to physical probes."""
    sdir = tmp_path / "sandbox"
    sdir.mkdir()
    (sdir / "Job-Resume.lck").write_text("locked", encoding="utf-8")

    snapshot = RunSnapshot(
        task_id="TASK-RESUME",
        run_id="RUN-RESUME",
        phase="RUNNING",
        job_name="Job-Resume",
        sandbox_dir=str(sdir),
        pid=7777,
    )
    ledger = default_ledger_path(tmp_path)
    write_snapshot(snapshot, ledger)

    monkeypatch.setattr("abaqus_ai_agent.execution.reconciliation.is_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        "abaqus_ai_agent.execution.reconciliation.is_lock_active", lambda path, associated_pid=None: True
    )

    report = resume_from_ledger(ledger, allow_git_drift=True)
    assert report.action == ReconciliationAction.RECONNECT_LIVE
    assert report.snapshot is not None
    assert report.snapshot.task_id == "TASK-RESUME"


def test_resume_from_ledger_ignores_corrupt_snapshot_and_probes_workdir(tmp_path, monkeypatch):
    """A corrupt ledger must not authorize resubmission; it is treated as absent."""
    sdir = tmp_path / "sandbox"
    sdir.mkdir()
    (sdir / "Job-Salvage2.sta").write_text("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n", encoding="utf-8")
    (sdir / "Job-Salvage2.odb").write_bytes(
        _STRUCTURED_ODB_HEAD + b"\x00" * 4090 + b"\x01"
    )

    ledger = default_ledger_path(tmp_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{corrupt", encoding="utf-8")

    monkeypatch.setattr(
        "abaqus_ai_agent.execution.reconciliation.is_lock_active", lambda path, associated_pid=None: False
    )

    report = resume_from_ledger(
        ledger,
        fallback_workdir=str(sdir),
        job_name="Job-Salvage2",
        allow_git_drift=True,
    )

    assert report.snapshot is None
    assert report.action == ReconciliationAction.READ_ONLY_RECOVER
