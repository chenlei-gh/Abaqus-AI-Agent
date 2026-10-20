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


# ---------------------------------------------------------------------------
# TC-TOK-01: source purity in the aggregate report
# ---------------------------------------------------------------------------

def _record(tracker, phase, tokens, source):
    return tracker.record_call(
        phase=phase,
        system_tokens=tokens,
        output_tokens=0,
        source=source,
    )


def test_tc_tok_01_single_verified_source_is_promoted_to_kpi(tmp_path: Path):
    """A report built from one verified tier may expose exactly one KPI."""
    tracker = ContextTelemetryTracker(
        case_id="TC_TOK_01_PURE",
        run_id="RUN-TOK-PURE",
        output_dir=tmp_path,
    )
    _record(tracker, EngineeringPhase.INTENT, 500, TokenCountSource.PROVIDER_USAGE)
    _record(tracker, EngineeringPhase.EXECUTION, 300, TokenCountSource.PROVIDER_USAGE)

    summary = tracker.finalize()

    assert summary.kpi_eligible is True
    assert summary.kpi_source == "provider_usage"
    assert summary.kpi_tokens == 800
    assert summary.blended_sources == ("provider_usage",)
    assert summary.token_source_buckets["provider_usage"]["claimable"] is True


def test_tc_tok_01_provider_and_estimated_never_share_one_kpi(tmp_path: Path):
    """provider_usage and estimated must not be summed into a single KPI figure."""
    tracker = ContextTelemetryTracker(
        case_id="TC_TOK_01_MIXED",
        run_id="RUN-TOK-MIXED",
        output_dir=tmp_path,
    )
    _record(tracker, EngineeringPhase.INTENT, 700, TokenCountSource.PROVIDER_USAGE)
    _record(tracker, EngineeringPhase.EXECUTION, 300, TokenCountSource.ESTIMATED)

    summary = tracker.finalize()

    # No KPI is promoted: the tiers cannot be combined.
    assert summary.kpi_eligible is False
    assert summary.kpi_source is None
    assert summary.kpi_tokens is None

    # Each tier keeps its own bucket, and the blended total is not claimable.
    assert summary.token_source_buckets["provider_usage"]["total_tokens"] == 700
    assert summary.token_source_buckets["estimated"]["total_tokens"] == 300
    assert summary.token_source_buckets["estimated"]["claimable"] is False
    assert summary.blended_sources == ("estimated", "provider_usage")
    assert summary.is_synthetic_projection is True
    assert summary.token_accounting_source == "estimated, provider_usage"


def test_tc_tok_01_estimated_only_report_is_never_claimable(tmp_path: Path):
    tracker = ContextTelemetryTracker(
        case_id="TC_TOK_01_EST",
        run_id="RUN-TOK-EST",
        output_dir=tmp_path,
    )
    _record(tracker, EngineeringPhase.INTENT, 400, TokenCountSource.ESTIMATED)

    summary = tracker.finalize()
    assert summary.kpi_eligible is False
    assert summary.token_source_buckets["estimated"]["claimable"] is False


# ---------------------------------------------------------------------------
# TC-TOK-02: external sessions must be recorded as UNMEASURED
# ---------------------------------------------------------------------------

def test_tc_tok_02_external_session_is_labeled_unmeasured(tmp_path: Path):
    """A host that cannot expose usage must record UNMEASURED, never an estimate."""
    tracker = ContextTelemetryTracker(
        case_id="TC_TOK_02_EXT",
        run_id="RUN-TOK-EXT",
        output_dir=tmp_path,
        source=TokenCountSource.UNMEASURED,
    )
    call = tracker.record_call(
        phase=EngineeringPhase.OTHER,
        user_input_text="external IDE session without usage plumbing",
    )

    assert call.breakdown.source is TokenCountSource.UNMEASURED
    assert call.breakdown.is_unmeasured is True
    assert call.breakdown.is_estimated is False
    assert call.breakdown.is_claimable is False

    summary = tracker.finalize()
    assert summary.has_unmeasured_calls is True
    assert summary.kpi_eligible is False
    assert summary.token_source_buckets["unmeasured"]["claimable"] is False

    call_file = tmp_path / "RUN-TOK-EXT" / "telemetry" / "calls" / f"{call.call_id}.json"
    with open(call_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["breakdown"]["source"] == "unmeasured"
    assert saved["breakdown"]["is_unmeasured"] is True


# ---------------------------------------------------------------------------
# Source downgrade: a heuristic component split never rides under a measurement
# ---------------------------------------------------------------------------

def test_heuristic_components_downgrade_a_verified_source(tmp_path: Path):
    """Provider usage is a per-request total, not a component split.

    When any component is derived from text, the record must not be filed as a
    provider measurement: that would promote an estimate into measured evidence.
    """
    tracker = ContextTelemetryTracker(
        case_id="TC_TOK_01_DOWNGRADE",
        run_id="RUN-TOK-DOWNGRADE",
        output_dir=tmp_path,
    )
    call = tracker.record_call(
        phase=EngineeringPhase.EXECUTION,
        system_tokens=500,
        tool_output_text="solver log line\n" * 40,
        output_tokens=60,
        source=TokenCountSource.PROVIDER_USAGE,
    )

    assert call.breakdown.source is TokenCountSource.ESTIMATED
    assert call.breakdown.is_claimable is False
    assert call.metadata["requested_source"] == "provider_usage"
    assert call.metadata["source_downgrade_reason"] == "component_counts_heuristic"
    # Explicit counts are preserved verbatim; nothing is discarded on downgrade.
    assert call.breakdown.system_tokens == 500
    assert call.breakdown.output_tokens == 60
    assert call.breakdown.tool_output_tokens > 0

    summary = tracker.finalize()
    assert summary.kpi_eligible is False
    assert summary.token_source_buckets["estimated"]["claimable"] is False
    assert "provider_usage" not in summary.token_source_buckets


def test_fully_explicit_components_keep_a_verified_source(tmp_path: Path):
    """No downgrade when every component was supplied explicitly."""
    tracker = ContextTelemetryTracker(
        case_id="TC_TOK_01_EXPLICIT",
        run_id="RUN-TOK-EXPLICIT",
        output_dir=tmp_path,
    )
    call = tracker.record_call(
        phase=EngineeringPhase.INTENT,
        system_tokens=500,
        tool_schema_tokens=0,
        conversation_tokens=0,
        tool_output_tokens=0,
        user_input_tokens=120,
        output_tokens=60,
        source=TokenCountSource.PROVIDER_USAGE,
    )

    assert call.breakdown.source is TokenCountSource.PROVIDER_USAGE
    assert "source_downgrade_reason" not in call.metadata
    assert tracker.finalize().kpi_eligible is True
