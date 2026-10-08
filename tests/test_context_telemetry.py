"""Tests for P0-0: Context Telemetry and Token Profiling."""

import json
from pathlib import Path

from abaqus_ai_agent.telemetry.contracts import (
    EngineeringPhase,
    TokenCountSource,
)
from abaqus_ai_agent.telemetry.tracker import ContextTelemetryTracker


def test_telemetry_call_recording_and_persistence(tmp_path: Path):
    tracker = ContextTelemetryTracker(
        case_id="TEST_CASE_01",
        run_id="RUN-TEST-001",
        output_dir=tmp_path,
        source=TokenCountSource.PROVIDER_REPORTED,
    )

    # Record Call 1: Intent Phase with explicit provider usage
    call1 = tracker.record_call(
        phase=EngineeringPhase.INTENT,
        system_tokens=820,
        tool_schema_tokens=410,
        conversation_tokens=190,
        tool_output_tokens=120,
        user_input_tokens=150,
        output_tokens=260,
        source=TokenCountSource.PROVIDER_REPORTED,
    )

    assert call1.call_id == "CALL-RUN-TEST-001-0001"
    assert call1.run_id == "RUN-TEST-001"
    assert call1.phase == EngineeringPhase.INTENT
    assert call1.breakdown.total_tokens == (820 + 410 + 190 + 120 + 150 + 260)
    assert not call1.breakdown.is_estimated

    # Verify disk persistence for Call 1
    call1_file = tmp_path / "RUN-TEST-001" / "telemetry" / "calls" / f"{call1.call_id}.json"
    assert call1_file.is_file()
    with open(call1_file, "r", encoding="utf-8") as f:
        saved_call1 = json.load(f)
    assert saved_call1["call_id"] == call1.call_id

    # Record Call 2: Execution Phase with text (heuristic fallback explicitly labeled)
    call2 = tracker.record_call(
        phase=EngineeringPhase.EXECUTION,
        system_text="System instructions for solver execution.",
        tool_output_text="Abaqus job completed with status COMPLETED.\n" * 50,
        source=TokenCountSource.ESTIMATED,
        pointers_count=2,
        pointers_size_bytes=1024,
    )

    assert call2.call_id == "CALL-RUN-TEST-001-0002"
    assert call2.phase == EngineeringPhase.EXECUTION
    assert call2.breakdown.is_estimated
    assert call2.artifacts.pointers_count == 2

    # Check LLM Context Safety (Zero context pollution)
    llm_status = tracker.get_llm_status()
    assert llm_status == {"telemetry_status": "available", "run_id": "RUN-TEST-001"}
    assert "breakdown" not in llm_status
    assert "tokens" not in llm_status

    # Finalize and verify summary aggregation
    summary = tracker.finalize()
    assert summary.total_calls == 2
    assert summary.total_tokens > 0
    assert "intent" in summary.phases
    assert "execution" in summary.phases

    # Check ranking
    assert len(summary.ranking_by_component) == 6
    top_component = summary.ranking_by_component[0]
    assert top_component[1] >= summary.ranking_by_component[1][1]

    # Verify disk persistence for summary
    summary_file = tmp_path / "RUN-TEST-001" / "telemetry" / "summary.json"
    assert summary_file.is_file()
    with open(summary_file, "r", encoding="utf-8") as f:
        saved_summary = json.load(f)
    assert saved_summary["run_id"] == "RUN-TEST-001"
    assert len(saved_summary["ranking_by_component"]) > 0
