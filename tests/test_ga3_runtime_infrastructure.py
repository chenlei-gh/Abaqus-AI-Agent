import os
import shutil
import tempfile
import time
from typing import Dict, Any

import pytest

from abaqus_ai_agent.contracts.capability import CapabilityResult, CapabilityStatus
from abaqus_ai_agent.execution.license import (
    LicenseHandle,
    LicenseHealthStatus,
    LicenseProvider,
    MockLicenseProvider,
    LocalLicenseProvider,
    FlexNetAdapter,
    DSLSAdapter,
)
from abaqus_ai_agent.execution.sandbox import RunSandbox, PromotedArtifact
from abaqus_ai_agent.execution.queue import (
    AnalysisRunQueue,
    QueueItem,
    QueueItemState,
    QueuePriority,
    RunResourceSpec,
    compute_backoff,
)
from abaqus_ai_agent.execution.recovery import (
    RecoveryVerdict,
    RunRecoveryInspection,
    inspect_run_state,
    recover_and_resume,
)
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState


# ---------------------------------------------------------------------------
# 1. CapabilityResult Contract Tests
# ---------------------------------------------------------------------------

def test_capability_result_contract():
    res = CapabilityResult(
        capability="cad_step_import",
        status=CapabilityStatus.SUPPORTED,
        reason="Native OpenCASCADE topology translation verified",
        evidence={"cad_format": "STEP", "faces": 24},
        next_action="proceed_to_geometry_inspection",
    )
    assert res.is_supported is True
    assert res.is_blocked is False
    assert res.needs_assistance is False

    d = res.to_dict()
    assert d["status"] == "supported"
    assert d["evidence"]["faces"] == 24

    restored = CapabilityResult.from_dict(d)
    assert restored.capability == "cad_step_import"
    assert restored.status == CapabilityStatus.SUPPORTED
    assert restored.is_supported is True


def test_capability_result_blocked_and_assisted():
    blocked = CapabilityResult(
        capability="material_extrapolation",
        status=CapabilityStatus.BLOCKED,
        reason="Extrapolation beyond experimental range is strictly forbidden",
        required_user_input="Please provide high-temperature stress-strain dataset",
    )
    assert blocked.is_blocked is True
    assert blocked.is_supported is False

    assisted = CapabilityResult(
        capability="mesh_partitioning",
        status=CapabilityStatus.ASSISTED,
        reason="Ambiguous sweep path detected",
        required_user_input="Confirm cutting plane normal vector",
    )
    assert assisted.needs_assistance is True


# ---------------------------------------------------------------------------
# 2. LicenseProvider Architecture & Adapters Tests
# ---------------------------------------------------------------------------

def test_mock_license_provider_concurrency_and_release():
    prov = MockLicenseProvider(initial_tokens={"standard": 2, "explicit": 1})
    assert prov.available_tokens("standard") == 2

    # Reserve 1
    h1 = prov.reserve("standard", tokens=1)
    assert h1 is not None
    assert h1.tokens == 1
    assert prov.available_tokens("standard") == 1

    # Reserve 2nd
    h2 = prov.reserve("standard", tokens=1)
    assert h2 is not None
    assert prov.available_tokens("standard") == 0

    # 3rd should fail immediately with timeout=0
    h3 = prov.reserve("standard", tokens=1, timeout=0.0)
    assert h3 is None

    # Release h1
    assert prov.release(h1) is True
    assert prov.available_tokens("standard") == 1

    # Now reserve succeeds
    h4 = prov.reserve("standard", tokens=1, timeout=0.0)
    assert h4 is not None

    # Clean release
    prov.release(h2)
    prov.release(h4)
    assert prov.available_tokens("standard") == 2


def test_mock_license_provider_context_manager():
    prov = MockLicenseProvider(initial_tokens={"standard": 1})
    with prov.acquire("standard", tokens=1) as handle:
        assert handle is not None
        assert prov.available_tokens("standard") == 0
    # Automatically released
    assert prov.available_tokens("standard") == 1


def test_mock_license_provider_health():
    prov = MockLicenseProvider(initial_tokens={"standard": 5}, healthy=True)
    health = prov.health()
    assert health.healthy is True
    assert health.available_tokens == 5

    prov.set_healthy(False)
    health_down = prov.health()
    assert health_down.healthy is False
    assert health_down.available_tokens == 0


def test_local_license_provider():
    local = LocalLicenseProvider()
    assert local.available_tokens("standard") > 1000
    with local.acquire("standard", tokens=5) as h:
        assert h.tokens == 5
    assert local.health().healthy is True


def test_flexnet_adapter_parsing():
    sample_output = """
lmutil - Copyright (c) 1989-2023 Flexera Software LLC. All Rights Reserved.
Flexible License Manager status on Fri 10/03/2026 09:30

Users of standard:  (Total of 10 licenses issued;  Total of 3 licenses in use)
  "standard" v2025.0, vendor: ABAQUSLM
  user1 host1 (v2025) (licserv/27000 101), start Fri 10/3 9:00
Users of explicit:  (Total of 8 licenses issued;  Total of 0 licenses in use)
"""

    def mock_runner(cmd):
        return {"exit_code": 0, "stdout": sample_output, "stderr": ""}

    adapter = FlexNetAdapter(server="27000@licserv", command_runner=mock_runner)
    avail_std = adapter.available_tokens("standard")
    assert avail_std == 7  # 10 issued - 3 in use

    avail_exp = adapter.available_tokens("explicit")
    assert avail_exp == 8

    # Reserve 2 tokens locally
    h = adapter.reserve("standard", tokens=2)
    assert h is not None
    assert adapter.available_tokens("standard") == 5

    adapter.release(h)
    assert adapter.available_tokens("standard") == 7

    health = adapter.health()
    assert health.healthy is True
    assert health.total_tokens == 18


def test_dsls_adapter_parsing():
    sample_output = """
Feature               Total  InUse   Free
standard                 12      4      8
explicit                  6      1      5
"""

    def mock_runner(cmd):
        return {"exit_code": 0, "stdout": sample_output, "stderr": ""}

    adapter = DSLSAdapter(server="dsls_server:4085", command_runner=mock_runner)
    assert adapter.available_tokens("standard") == 8
    assert adapter.available_tokens("explicit") == 5


# ---------------------------------------------------------------------------
# 3. RunSandbox Workspace Isolation & Artifact Promotion Tests
# ---------------------------------------------------------------------------

def test_run_sandbox_lifecycle():
    with tempfile.TemporaryDirectory() as temp_root:
        sandbox = RunSandbox(run_id="run_test_123", base_dir=temp_root)
        sandbox.create()
        assert os.path.exists(sandbox.sandbox_dir)

        # Write dummy solver files
        odb_file = sandbox.resolve_path("Job-1.odb")
        with open(odb_file, "wb") as f:
            f.write(b"MOCK_ODB_BINARY_CONTENT")

        sta_file = sandbox.resolve_path("Job-1.sta")
        with open(sta_file, "w") as f:
            f.write("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")

        tmp_scratch = sandbox.resolve_path("Job-1.023")
        with open(tmp_scratch, "w") as f:
            f.write("SCRATCH_RAW_DATA\n")

        # Test locks
        assert sandbox.is_locked() is False
        lck_file = sandbox.resolve_path("Job-1.lck")
        with open(lck_file, "w") as f:
            f.write("LOCK\n")
        assert sandbox.is_locked() is True
        assert len(sandbox.check_locks()) == 1

        sandbox.clear_stale_locks()
        assert sandbox.is_locked() is False

        # Promote artifacts to canonical target directory
        target_dir = os.path.join(temp_root, "permanent_artifacts")
        promoted = sandbox.promote_artifacts(target_dir)
        assert len(promoted) == 2  # .odb and .sta promoted, .023 ignored
        types = {p.artifact_type for p in promoted}
        assert "odb" in types
        assert "sta" in types

        for p in promoted:
            assert os.path.exists(p.target_path)
            assert len(p.sha256) == 64

        # Cleanup scratch
        assert sandbox.cleanup() is True
        assert not os.path.exists(sandbox.sandbox_dir)
        # Promoted artifacts remain intact
        assert os.path.exists(os.path.join(target_dir, "Job-1.odb"))


# ---------------------------------------------------------------------------
# 4. AnalysisRunQueue, Concurrency & Exponential Backoff Tests
# ---------------------------------------------------------------------------

def test_compute_backoff_distribution():
    b0 = compute_backoff(retry_count=0, base=1.0, max_delay=10.0, jitter_ratio=0.1)
    assert 0.8 <= b0 <= 1.2

    b2 = compute_backoff(retry_count=2, base=1.0, max_delay=10.0, jitter_ratio=0.1)
    assert 3.5 <= b2 <= 4.5

    b_capped = compute_backoff(retry_count=10, base=1.0, max_delay=15.0, jitter_ratio=0.0)
    assert b_capped == 15.0


def test_analysis_run_queue_priority_and_concurrency():
    prov = MockLicenseProvider(initial_tokens={"standard": 10})
    queue = AnalysisRunQueue(max_concurrency=2, license_provider=prov)

    item_low = queue.enqueue(payload="LowTask", priority=QueuePriority.LOW)
    item_crit = queue.enqueue(payload="CritTask", priority=QueuePriority.CRITICAL)
    item_norm = queue.enqueue(payload="NormTask", priority=QueuePriority.NORMAL)

    # First dispatch should pick CRITICAL
    dispatched1 = queue.process_next()
    assert dispatched1 is not None
    assert dispatched1.item_id == item_crit.item_id
    assert dispatched1.state == QueueItemState.RUNNING

    # Second dispatch should pick NORMAL (over LOW)
    dispatched2 = queue.process_next()
    assert dispatched2 is not None
    assert dispatched2.item_id == item_norm.item_id
    assert dispatched2.state == QueueItemState.RUNNING

    # Concurrency limit reached (max_concurrency=2)
    dispatched3 = queue.process_next()
    assert dispatched3 is None

    # Complete one task
    queue.complete(dispatched1.item_id, result="DONE")
    assert queue.active_running_count() == 1

    # Now LOW can be dispatched
    dispatched_low = queue.process_next()
    assert dispatched_low is not None
    assert dispatched_low.item_id == item_low.item_id


def test_queue_license_exhaustion_and_backoff():
    # Only 1 token available
    prov = MockLicenseProvider(initial_tokens={"standard": 1})
    queue = AnalysisRunQueue(max_concurrency=3, license_provider=prov)

    item1 = queue.enqueue(payload="Task1", max_retries=2, backoff_base=0.1)
    item2 = queue.enqueue(payload="Task2", max_retries=2, backoff_base=0.1)

    t0 = time.time()
    # First item takes the 1 token
    d1 = queue.process_next(current_time=t0)
    assert d1 is not None
    assert d1.item_id == item1.item_id

    # Second item finds tokens exhausted -> transitions to RETRYING with next_eligible_at in future
    d2 = queue.process_next(current_time=t0)
    assert d2 is None
    assert item2.state == QueueItemState.RETRYING
    assert item2.retry_count == 1
    assert item2.next_eligible_at > t0

    # Before next_eligible_at, item2 is not processed
    assert queue.process_next(current_time=t0 + 0.01) is None

    # Task1 finishes and releases license
    queue.complete(item1.item_id)
    assert prov.available_tokens("standard") == 1

    # At t0 + 1.0 (past backoff delay), item2 is successfully dispatched!
    d2_retry = queue.process_next(current_time=t0 + 1.0)
    assert d2_retry is not None
    assert d2_retry.item_id == item2.item_id
    assert d2_retry.state == QueueItemState.RUNNING


def test_queue_cancel():
    prov = MockLicenseProvider(initial_tokens={"standard": 5})
    queue = AnalysisRunQueue(max_concurrency=2, license_provider=prov)
    item = queue.enqueue(payload="CancelMe")
    dispatched = queue.process_next()
    assert dispatched.state == QueueItemState.RUNNING

    assert queue.cancel(item.item_id, reason="User abort") is True
    assert item.state == QueueItemState.CANCELLED
    assert item.license_handle is None
    # Token returned
    assert prov.available_tokens("standard") == 5


# ---------------------------------------------------------------------------
# 5. RunRecovery Deterministic Inspection & Auto-Resume Tests
# ---------------------------------------------------------------------------

def test_run_recovery_completed_ready(tmp_path):
    job_name = "Job-T1"
    workdir = str(tmp_path)

    # Mock completed run artifacts
    sta_file = os.path.join(workdir, f"{job_name}.sta")
    with open(sta_file, "w") as f:
        f.write("STEP 1 INCREMENT 5\nTHE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")

    odb_file = os.path.join(workdir, f"{job_name}.odb")
    with open(odb_file, "wb") as f:
        f.write(b"MOCK_ODB_HEADER_AND_RESULTS")

    inspection = inspect_run_state(workdir, job_name)
    assert inspection.verdict == RecoveryVerdict.COMPLETED_READY
    assert inspection.sta_status == "COMPLETED"
    assert inspection.has_odb is True
    assert inspection.has_lock is False

    # Execute recovery on AnalysisRun
    run = AnalysisRun(id="r1", model_name="M1", job_name=job_name, state=AnalysisRunState.CREATED)
    recovered_run, _ = recover_and_resume(run, workdir)
    assert recovered_run.state == AnalysisRunState.ODB_VALIDATED
    assert recovered_run.odb_path == odb_file


def test_run_recovery_crashed_clears_stale_lock(tmp_path):
    job_name = "Job-Crash"
    workdir = str(tmp_path)

    # Crash artifacts: stale lock, aborted .sta
    lck_file = os.path.join(workdir, f"{job_name}.lck")
    with open(lck_file, "w") as f:
        f.write("STALE_LOCK")

    sta_file = os.path.join(workdir, f"{job_name}.sta")
    with open(sta_file, "w") as f:
        f.write("ABNORMAL TERMINATION / ABORTED BY SYSTEM\n")

    inspection = inspect_run_state(workdir, job_name)
    assert inspection.verdict == RecoveryVerdict.NON_RECOVERABLE_RESUBMIT
    assert inspection.has_lock is True

    run = AnalysisRun(id="r2", model_name="M2", job_name=job_name, state=AnalysisRunState.RUNNING)
    recovered_run, _ = recover_and_resume(run, workdir)
    # Stale lock must be cleared and state reset to PREFLIGHTED
    assert not os.path.exists(lck_file)
    assert recovered_run.state == AnalysisRunState.PREFLIGHTED
    assert recovered_run.metadata.get("cleaned_locks_count") == 1
