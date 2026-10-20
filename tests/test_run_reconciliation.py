"""Tests for State Reconciliation and Zero-Trust Task Recovery Matrix (TC-REC-01 to TC-REC-06)."""

import json
import os
from pathlib import Path
import pytest

from abaqus_ai_agent.execution.reconciliation import (
    ReconciliationAction,
    ReconciliationReport,
    RunSnapshot,
    reconcile_run_state,
)


def _setup_mock_sandbox(tmp_path: Path, job_name: str = "Job-Test"):
    sdir = tmp_path / "sandbox"
    sdir.mkdir(parents=True, exist_ok=True)
    return sdir


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
    odb_path.write_bytes(b"\x00" * 4096)  # Authentically sized dummy

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
    """TC-REC-03: Dead solver with stale lock and incomplete job -> CLEANUP_AND_RESUBMIT."""
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


def test_tc_rec_05_missing_snapshot_but_valid_sandbox(tmp_path, monkeypatch):
    """TC-REC-05: Snapshot json lost, but sandbox has completed job -> salvage via READ_ONLY_RECOVER."""
    sdir = _setup_mock_sandbox(tmp_path)
    job_name = "Job-Salvage"

    sta_path = sdir / f"{job_name}.sta"
    sta_path.write_text("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")

    odb_path = sdir / f"{job_name}.odb"
    odb_path.write_bytes(b"\x00" * 8192)

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
