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
    register_task,
    get_registered_task,
    task_handler,
)
from abaqus_ai_agent.execution.recovery import (
    RecoveryVerdict,
    RunRecoveryInspection,
    inspect_run_state,
    recover_and_resume,
    is_pid_alive,
    is_lock_active,
    clean_stale_locks,
)
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
from abaqus_ai_agent.execution.worker import RunWorker, RunWorkerPool


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


# ---------------------------------------------------------------------------
# 6. GA-3.6 Production Worker Runtime & Persistent Queue Tests
# ---------------------------------------------------------------------------

def test_queue_disk_persistence_and_reload(tmp_path):
    persist_file = os.path.join(tmp_path, "queue_store.json")
    prov = MockLicenseProvider(initial_tokens={"standard": 5})

    q1 = AnalysisRunQueue(max_concurrency=2, license_provider=prov, persistence_path=persist_file)
    item1 = q1.enqueue(payload={"task": "task1"}, priority=QueuePriority.HIGH)
    item2 = q1.enqueue(payload={"task": "task2"}, priority=QueuePriority.LOW)

    # Dispatch item1
    d1 = q1.process_next()
    assert d1 is not None
    assert d1.item_id == item1.item_id
    q1.complete(item1.item_id, result={"status": "SUCCESS"})

    assert os.path.exists(persist_file)

    # Re-instantiate queue from persistence_path
    q2 = AnalysisRunQueue(max_concurrency=2, license_provider=prov, persistence_path=persist_file)
    loaded1 = q2.get_item(item1.item_id)
    assert loaded1 is not None
    assert loaded1.state == QueueItemState.COMPLETED
    assert loaded1.result == {"status": "SUCCESS"}

    loaded2 = q2.get_item(item2.item_id)
    assert loaded2 is not None
    assert loaded2.state == QueueItemState.PENDING


def test_queue_recover_orphaned_runs(tmp_path):
    persist_file = os.path.join(tmp_path, "queue_crash.json")
    prov = MockLicenseProvider(initial_tokens={"standard": 5})

    q1 = AnalysisRunQueue(max_concurrency=2, license_provider=prov, persistence_path=persist_file)
    item = q1.enqueue(payload={"task": "crash_me"})
    dispatched = q1.process_next()
    assert dispatched.state == QueueItemState.RUNNING

    # Simulate abrupt process death and restart: new queue instance loads state
    q2 = AnalysisRunQueue(max_concurrency=2, license_provider=prov, persistence_path=persist_file)
    reloaded_item = q2.get_item(item.item_id)
    assert reloaded_item.state == QueueItemState.RUNNING  # Left running by previous process

    # Trigger recovery of orphaned runs
    recovered_count = q2.recover_orphaned_runs(recovery_strategy="requeue")
    assert recovered_count == 1
    assert reloaded_item.state == QueueItemState.RETRYING
    assert reloaded_item.retry_count == 1
    assert reloaded_item.license_handle is None

    # Next eligible dispatch can now pick it up cleanly
    redump = q2.process_next()
    assert redump is not None
    assert redump.item_id == item.item_id
    assert redump.state == QueueItemState.RUNNING


def test_run_worker_e2e_execution(tmp_path):
    sandbox_base = os.path.join(tmp_path, "sandboxes")
    target_artifacts = os.path.join(tmp_path, "artifacts")
    prov = MockLicenseProvider(initial_tokens={"standard": 2})
    queue = AnalysisRunQueue(max_concurrency=2, license_provider=prov)

    # Define a mock task payload that writes a fake ODB in the sandbox
    def sample_task(sandbox: RunSandbox):
        odb = sandbox.resolve_path("Job-1.odb")
        with open(odb, "wb") as f:
            f.write(b"SAMPLE_ODB_CONTENT")
        sta = sandbox.resolve_path("Job-1.sta")
        with open(sta, "w") as f:
            f.write("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")
        return AnalysisRun(id=sandbox.run_id, model_name="M1", job_name="Job-1", state=AnalysisRunState.COMPLETED)

    item = queue.enqueue(payload=sample_task)
    worker = RunWorker(
        queue=queue,
        sandbox_base_dir=sandbox_base,
        target_artifacts_dir=target_artifacts,
    )

    executed_item = worker.poll_and_execute_once()
    assert executed_item is not None
    assert executed_item.error is None, f"Worker failed with error: {executed_item.error}"
    assert executed_item.state == QueueItemState.COMPLETED

    # Check that artifact was promoted to target_artifacts
    assert os.path.exists(os.path.join(target_artifacts, "Job-1.odb"))
    assert os.path.exists(os.path.join(target_artifacts, "Job-1.sta"))

    # Check that scratch sandbox was cleaned up
    assert not os.path.exists(os.path.join(sandbox_base, f"abaqus_sandbox_{item.item_id}"))

    # Check license was released
    assert prov.available_tokens("standard") == 2


def test_run_worker_failure_and_retry():
    prov = MockLicenseProvider(initial_tokens={"standard": 2})
    queue = AnalysisRunQueue(max_concurrency=2, license_provider=prov)

    attempt_counter = [0]

    def flaky_task(sandbox: RunSandbox):
        attempt_counter[0] += 1
        if attempt_counter[0] == 1:
            # Leave a lock file and raise error to simulate crash
            lck = sandbox.resolve_path("Job-1.lck")
            with open(lck, "w") as f:
                f.write("CRASH_LOCK")
            raise RuntimeError("Simulated solver crash on step 1")
        return "SUCCESS_ON_ATTEMPT_2"

    item = queue.enqueue(payload=flaky_task, max_retries=2, backoff_base=0.01)
    worker = RunWorker(queue=queue)

    # First attempt fails and transitions to RETRYING
    worker.poll_and_execute_once()
    assert item.state == QueueItemState.RETRYING
    assert item.retry_count == 1
    # License released during backoff
    assert prov.available_tokens("standard") == 2

    # Fast forward time to allow retry
    item.next_eligible_at = time.time() - 0.1

    # Second attempt succeeds
    worker.poll_and_execute_once()
    assert item.state == QueueItemState.COMPLETED
    assert item.result == "SUCCESS_ON_ATTEMPT_2"


def test_run_worker_pool_concurrency(tmp_path):
    prov = MockLicenseProvider(initial_tokens={"standard": 2})
    queue = AnalysisRunQueue(max_concurrency=2, license_provider=prov)

    def quick_task(sandbox: RunSandbox):
        time.sleep(0.05)
        return "OK"

    # Enqueue 4 tasks
    for i in range(4):
        queue.enqueue(payload=quick_task, item_id=f"t_{i}")

    pool = RunWorkerPool(queue=queue, worker_count=2)
    pool.start(poll_interval=0.02)

    drained = pool.wait_until_drained(timeout=5.0)
    pool.stop()

    assert drained is True
    for i in range(4):
        it = queue.get_item(f"t_{i}")
        assert it is not None
        assert it.state == QueueItemState.COMPLETED

    assert prov.available_tokens("standard") == 2


# ---------------------------------------------------------------------------
# 7. GA-3.6.1 Hardening Tests (Durable Descriptor, Thread Safety, Sandbox Binding, Lock Protection)
# ---------------------------------------------------------------------------

def test_atomic_persistence_and_durable_analysis_run(tmp_path):
    persist_file = os.path.join(tmp_path, "durable_queue.json")
    prov = MockLicenseProvider(initial_tokens={"standard": 5})

    q1 = AnalysisRunQueue(max_concurrency=2, license_provider=prov, persistence_path=persist_file)

    # 1. Enqueue structured AnalysisRun
    ar = AnalysisRun(
        id="run-durable-1",
        model_name="BeamModel",
        job_name="Job-Durable-1",
        state=AnalysisRunState.CREATED,
    )
    item_ar = q1.enqueue(payload=ar, priority=QueuePriority.HIGH)

    # 2. Enqueue registered callable task
    @task_handler("test_registered_task_handler")
    def my_registered_task(sandbox: RunSandbox):
        return "SUCCESSFUL_EXECUTION"

    item_fn = q1.enqueue(payload=my_registered_task, priority=QueuePriority.NORMAL)

    # Dispatch item_ar to RUNNING
    d1 = q1.process_next()
    assert d1 is not None
    assert d1.item_id == item_ar.item_id
    assert d1.state == QueueItemState.RUNNING

    # Re-instantiate queue from disk
    q2 = AnalysisRunQueue(max_concurrency=2, license_provider=prov, persistence_path=persist_file)

    reloaded_ar = q2.get_item(item_ar.item_id)
    assert reloaded_ar is not None
    # Payload restored as AnalysisRun instance, not None or raw dict
    assert isinstance(reloaded_ar.payload, AnalysisRun)
    assert reloaded_ar.payload.id == "run-durable-1"
    assert reloaded_ar.payload.model_name == "BeamModel"

    reloaded_fn = q2.get_item(item_fn.item_id)
    assert reloaded_fn is not None
    assert callable(reloaded_fn.payload) or (isinstance(reloaded_fn.payload, dict) and reloaded_fn.payload.get("task_name") == "test_registered_task_handler")

    # Recover orphaned runs
    recovered = q2.recover_orphaned_runs(recovery_strategy="requeue")
    assert recovered == 1
    assert reloaded_ar.state == QueueItemState.RETRYING
    assert isinstance(reloaded_ar.payload, AnalysisRun)


def test_queue_thread_safe_concurrent_dispatch(tmp_path):
    import concurrent.futures

    prov = MockLicenseProvider(initial_tokens={"standard": 10})
    queue = AnalysisRunQueue(max_concurrency=3, license_provider=prov)

    # Enqueue 15 items
    for i in range(15):
        queue.enqueue(payload=f"Task_{i}", item_id=f"item_{i}")

    max_observed_concurrency = [0]
    import threading
    lock = threading.Lock()

    def dispatch_worker():
        for _ in range(20):
            item = queue.process_next()
            if item is not None:
                running_now = queue.active_running_count()
                with lock:
                    if running_now > max_observed_concurrency[0]:
                        max_observed_concurrency[0] = running_now
                time.sleep(0.01)
                queue.complete(item.item_id, result="DONE")
            time.sleep(0.005)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(dispatch_worker) for _ in range(8)]
        concurrent.futures.wait(futures)

    # Concurrency never exceeded max_concurrency
    assert max_observed_concurrency[0] <= 3
    # All items successfully drained
    completed = queue.list_items(state=QueueItemState.COMPLETED)
    assert len(completed) == 15


def test_process_aware_stale_lock_protection(tmp_path):
    workdir = str(tmp_path)
    job_name = "Job-Protected"
    lck_path = os.path.join(workdir, f"{job_name}.lck")

    with open(lck_path, "w") as f:
        f.write("LOCK_CONTENT")

    # 1. Protection when process is alive: pass current process PID
    my_pid = os.getpid()
    assert is_pid_alive(my_pid) is True

    cleaned = clean_stale_locks(workdir, job_name=job_name, associated_pid=my_pid)
    assert cleaned == 0
    assert os.path.exists(lck_path) is True  # Lock protected!

    # 2. When process is dead (e.g. non-existent PID): safe cleanup
    cleaned_dead = clean_stale_locks(workdir, job_name=job_name, associated_pid=99999999)
    assert cleaned_dead == 1
    assert os.path.exists(lck_path) is False  # Safely removed

    # 3. Test RunSandbox.clear_stale_locks honors process awareness
    sandbox = RunSandbox(run_id="test_lock_sandbox", base_dir=workdir)
    sandbox.create()
    s_lck = sandbox.resolve_path("Solver.lck")
    with open(s_lck, "w") as f:
        f.write("LOCK")

    # Alive PID -> refused
    assert sandbox.clear_stale_locks(associated_pid=my_pid) == 0
    assert os.path.exists(s_lck) is True

    # Dead PID -> cleared
    assert sandbox.clear_stale_locks(associated_pid=99999999) == 1
    assert os.path.exists(s_lck) is False
    sandbox.cleanup()


def test_worker_executes_registered_task_after_recovery(tmp_path):
    persist_file = os.path.join(tmp_path, "recovered_task_queue.json")
    sandbox_base = os.path.join(tmp_path, "sandboxes")
    target_artifacts = os.path.join(tmp_path, "artifacts")
    prov = MockLicenseProvider(initial_tokens={"standard": 2})

    @task_handler("durable_resilient_task")
    def resilient_task(sandbox: RunSandbox):
        sta = sandbox.resolve_path("Job-Resilient.sta")
        with open(sta, "w") as f:
            f.write("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")
        return "RESILIENT_RUN_FINISHED"

    q1 = AnalysisRunQueue(max_concurrency=1, license_provider=prov, persistence_path=persist_file)
    item = q1.enqueue(payload=resilient_task)

    # Dispatch to RUNNING
    d1 = q1.process_next()
    assert d1.state == QueueItemState.RUNNING

    # Crash & restart
    q2 = AnalysisRunQueue(max_concurrency=1, license_provider=prov, persistence_path=persist_file)
    q2.recover_orphaned_runs(recovery_strategy="requeue")

    worker = RunWorker(
        queue=q2,
        sandbox_base_dir=sandbox_base,
        target_artifacts_dir=target_artifacts,
    )

    # Worker executes the recovered registered task seamlessly
    executed = worker.poll_and_execute_once()
    assert executed is not None
    assert executed.state == QueueItemState.COMPLETED
    assert executed.result == "RESILIENT_RUN_FINISHED"
    assert os.path.exists(os.path.join(target_artifacts, "Job-Resilient.sta"))


def test_worker_runner_sandbox_binding(tmp_path):
    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

    class MockBoundExecutor:
        def __init__(self):
            self.workdir = None

        def execute(self, code):
            # If code is checking for odb in workdir
            if "exists" in code and self.workdir:
                return os.path.join(self.workdir, "Job-Bound.odb")
            return ""

    sandbox_base = os.path.join(tmp_path, "sandboxes")
    target_artifacts = os.path.join(tmp_path, "artifacts")
    prov = MockLicenseProvider(initial_tokens={"standard": 2})
    queue = AnalysisRunQueue(max_concurrency=1, license_provider=prov)

    mock_exec = MockBoundExecutor()
    runner = AnalysisRunner(executor=mock_exec)

    ar = AnalysisRun(
        id="run-bound-1",
        model_name="BoundModel",
        job_name="Job-Bound",
        state=AnalysisRunState.CREATED,
    )
    queue.enqueue(payload=ar)

    # Create dummy solver hook by monkeypatching JobController.submit
    from abaqus_ai_agent.execution.jobs import JobController, JobStatus, JobState
    orig_submit = JobController.submit

    def mock_submit(self, job_name, wait=True, timeout=3600):
        # Write ODB and STA inside executor workdir
        if mock_exec.workdir:
            with open(os.path.join(mock_exec.workdir, f"{job_name}.odb"), "wb") as f:
                f.write(b"MOCK_ODB")
            with open(os.path.join(mock_exec.workdir, f"{job_name}.sta"), "w") as f:
                f.write("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")
        return JobStatus(name=job_name, state=JobState.COMPLETED)

    JobController.submit = mock_submit
    try:
        worker = RunWorker(
            queue=queue,
            runner=runner,
            sandbox_base_dir=sandbox_base,
            target_artifacts_dir=target_artifacts,
        )
        executed = worker.poll_and_execute_once()
        assert executed is not None
        assert executed.state == QueueItemState.COMPLETED
        # Verify artifact promotion succeeded from the sandbox directory
        assert os.path.exists(os.path.join(target_artifacts, "Job-Bound.odb"))
        assert os.path.exists(os.path.join(target_artifacts, "Job-Bound.sta"))
    finally:
        JobController.submit = orig_submit
