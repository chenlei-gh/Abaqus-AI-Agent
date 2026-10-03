"""Tests for Phase GA-3 Real-Machine Production Qualification Suite (G3-R1 ~ G3-R6).

Verifies offline contracts, timeline invariant parsing, orphan run recovery logic,
and evidence manifest structural integrity without requiring external solver licenses.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.execution.queue import (
    AnalysisRunQueue,
    QueueItemState,
    QueuePriority,
    register_task,
)
from abaqus_ai_agent.execution.sandbox import RunSandbox
from abaqus_ai_agent.execution.worker import RunWorkerPool
from tools.ga3_real_machine_qualification import (
    execute_g3_r2_concurrency_cap_timeline,
    execute_g3_r4_worker_crash_and_orphan_recovery,
    execute_g3_r5_license_qualification,
    compute_sha256,
)

ROOT = Path(__file__).resolve().parent.parent


def test_g3_r2_timeline_offline(tmp_path):
    """Verify that G3-R2 concurrency cap and timeline sampling adhere to invariant max(RUNNING) <= 2."""
    res = execute_g3_r2_concurrency_cap_timeline(tmp_path)
    assert res["passed"] is True
    assert res["benchmark_id"] == "G3-R2"
    assert res["cap_strictly_maintained"] is True
    assert res["max_running_observed"] == 2
    assert res["total_tasks_processed"] == 8
    assert len(res["timeline_snippet"]) > 0


def test_g3_r4_orphan_recovery_offline(tmp_path):
    """Verify G3-R4 orphan recovery safely recovers stranded RUNNING runs into RETRYING."""
    res = execute_g3_r4_worker_crash_and_orphan_recovery(tmp_path)
    assert res["passed"] is True
    assert res["benchmark_id"] == "G3-R4"
    assert res["recovered_orphan_count"] == 1
    assert res["final_task_state"] == "completed"


def test_g3_r5_license_contention_offline(tmp_path):
    """Verify G3-R5 contention state machine and honest physical server reporting."""
    res = execute_g3_r5_license_qualification(tmp_path)
    assert res["passed"] is True
    assert res["benchmark_id"] == "G3-R5"
    assert res["offline_contention_passed"] is True
    assert "qualification_status" in res
    assert res["qualification_status"] in ("REAL_LICENSE_SERVER_CONNECTED", "REAL_LICENSE_SERVER_NOT_AVAILABLE")


def test_g3_real_machine_evidence_manifest():
    """Verify the audited real-machine qualification evidence manifest."""
    manifest_path = ROOT / "machine_validation" / "ga3_real_machine_evidence.json"
    assert manifest_path.is_file(), "GA-3 Real-Machine Evidence manifest missing!"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert data["suite_name"] == "Phase GA-3 Real-Machine Production Qualification Suite"
    assert data["all_passed"] is True
    assert data["total_benchmarks"] == 6
    assert data["passed_benchmarks"] == 6

    # Verify G3-R1
    r1 = data["results"]["G3-R1"]
    assert r1["passed"] is True
    assert r1["max_concurrent_running_observed"] == 2
    assert r1["concurrency_overlap_verified"] is True
    assert r1["job_a"]["odb_size_bytes"] > 0
    assert r1["job_b"]["odb_size_bytes"] > 0
    assert len(r1["job_a"]["odb_sha256"]) == 64
    assert len(r1["job_b"]["odb_sha256"]) == 64

    # Verify G3-R3
    r3 = data["results"]["G3-R3"]
    assert r3["passed"] is True
    assert r3["attempts_required"] == 2
    assert r3["final_state"] == "completed"
    assert r3["healed_odb_size_bytes"] > 0
    assert len(r3["healed_odb_sha256"]) == 64
