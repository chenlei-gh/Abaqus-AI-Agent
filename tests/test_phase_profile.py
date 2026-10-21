"""Phase profiling contract tests (Governance Plan 阶段 3 第 1 项).

Contract under test: ``telemetry/phase_profile.py``.

Layer of evidence: **unit only**. These tests use an injected fake clock and
synthetic durations. They prove the profiling *contract* holds; they do not
measure any real Abaqus run, and they cannot prove real T1~T6 timings.

Deliberately NOT asserted here:
  - any absolute duration for a real CAD/mesh/solver/extraction/report phase;
  - that ``AnalysisRunner`` emits a profile (it is not wired, by decision).
"""

from __future__ import annotations

import pytest

from abaqus_ai_agent.telemetry import phase_profile as pp
from abaqus_ai_agent.telemetry.phase_profile import (
    PhaseProfile,
    PhaseProfileError,
    PhaseProfiler,
    PhaseStatus,
    PipelinePhase,
)


class FakeClock:
    """Deterministic monotonic clock; advancing is explicit."""

    def __init__(self, start: float = 1000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, delta: float) -> None:
        self.value += delta


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(pp.time, "monotonic", fake)
    return fake


# ---------------------------------------------------------------------------
# Closed phase set
# ---------------------------------------------------------------------------

def test_all_six_governance_phases_exist_in_order():
    expected = [
        "T1_cad_parsing",
        "T2_mesh_compilation",
        "T3_license_queue",
        "T4_solver",
        "T5_data_extraction",
        "T6_report_generation",
    ]
    assert [p.value for p in sorted(PipelinePhase, key=lambda p: p.order)] == expected


def test_profile_always_reports_all_six_phases(clock):
    profiler = PhaseProfiler(run_id="R1")
    with profiler.measure(PipelinePhase.SOLVER):
        clock.advance(2.0)
    profile = profiler.finalize()

    assert len(profile.records) == 6
    payload = profile.to_dict()
    assert len(payload["phases"]) == 6
    assert set(payload["not_run"]) == {
        "T1_cad_parsing",
        "T2_mesh_compilation",
        "T3_license_queue",
        "T5_data_extraction",
        "T6_report_generation",
    }


# ---------------------------------------------------------------------------
# Not measuring is distinct from measuring zero
# ---------------------------------------------------------------------------

def test_unentered_phase_is_not_run_with_none_duration(clock):
    profiler = PhaseProfiler()
    with profiler.measure(PipelinePhase.CAD_PARSING):
        clock.advance(1.5)
    profile = profiler.finalize()

    mesh = profile.get(PipelinePhase.MESH_COMPILATION)
    assert mesh.status is PhaseStatus.NOT_RUN
    assert mesh.duration_s is None

    cad = profile.get(PipelinePhase.CAD_PARSING)
    assert cad.status is PhaseStatus.MEASURED
    assert cad.duration_s == pytest.approx(1.5)


def test_zero_duration_is_measured_not_missing(clock):
    """A phase that took no time is MEASURED with 0.0, never NOT_RUN."""
    profiler = PhaseProfiler()
    with profiler.measure(PipelinePhase.LICENSE_QUEUE):
        pass  # no clock advance
    profile = profiler.finalize()

    record = profile.get(PipelinePhase.LICENSE_QUEUE)
    assert record.status is PhaseStatus.MEASURED
    assert record.duration_s == 0.0


def test_mark_not_run_records_a_reason(clock):
    profiler = PhaseProfiler()
    record = profiler.mark_not_run(PipelinePhase.REPORT_GENERATION, reason="no report requested")

    assert record.status is PhaseStatus.NOT_RUN
    assert record.duration_s is None
    assert record.detail["reason"] == "no report requested"


def test_mark_not_run_cannot_erase_a_real_measurement(clock):
    profiler = PhaseProfiler()
    with profiler.measure(PipelinePhase.SOLVER):
        clock.advance(3.0)

    with pytest.raises(PhaseProfileError, match="already has a measurement"):
        profiler.mark_not_run(PipelinePhase.SOLVER)


# ---------------------------------------------------------------------------
# Failure is recorded, not swallowed or lost
# ---------------------------------------------------------------------------

def test_failure_is_recorded_and_exception_propagates_unchanged(clock):
    profiler = PhaseProfiler()

    with pytest.raises(ValueError, match="mesh exploded"):
        with profiler.measure(PipelinePhase.MESH_COMPILATION):
            clock.advance(0.75)
            raise ValueError("mesh exploded")

    profile = profiler.finalize()
    record = profile.get(PipelinePhase.MESH_COMPILATION)

    assert record.status is PhaseStatus.FAILED
    assert record.duration_s == pytest.approx(0.75)
    assert record.exception_type == "ValueError"
    assert record.exception_message == "mesh exploded"
    assert profile.failed_phases == (record,)
    assert profile.to_dict()["failed"] == ["T2_mesh_compilation"]


def test_failure_still_lets_later_phases_be_measured(clock):
    """A failed phase must not poison the rest of the profile."""
    profiler = PhaseProfiler()
    with pytest.raises(RuntimeError):
        with profiler.measure(PipelinePhase.SOLVER):
            raise RuntimeError("solver diverged")

    with profiler.measure(PipelinePhase.DATA_EXTRACTION):
        clock.advance(1.0)

    profile = profiler.finalize()
    assert profile.get(PipelinePhase.SOLVER).status is PhaseStatus.FAILED
    assert profile.get(PipelinePhase.DATA_EXTRACTION).status is PhaseStatus.MEASURED


# ---------------------------------------------------------------------------
# Non-overlap
# ---------------------------------------------------------------------------

def test_overlapping_phases_are_a_contract_violation(clock):
    profiler = PhaseProfiler()
    with pytest.raises(PhaseProfileError, match="still active"):
        with profiler.measure(PipelinePhase.SOLVER):
            with profiler.measure(PipelinePhase.DATA_EXTRACTION):
                pass


def test_finalize_refuses_while_a_phase_is_active(clock):
    profiler = PhaseProfiler()
    with profiler.measure(PipelinePhase.SOLVER):
        with pytest.raises(PhaseProfileError, match="still active"):
            profiler.finalize()


def test_measure_after_finalize_is_refused(clock):
    profiler = PhaseProfiler()
    profiler.finalize()
    with pytest.raises(PhaseProfileError, match="after finalize"):
        with profiler.measure(PipelinePhase.SOLVER):
            pass


def test_double_finalize_is_refused():
    profiler = PhaseProfiler()
    profiler.finalize()
    with pytest.raises(PhaseProfileError, match="already called"):
        profiler.finalize()


# ---------------------------------------------------------------------------
# Reconciliation against the wall clock
# ---------------------------------------------------------------------------

def test_unattributed_time_is_reported_not_absorbed(clock):
    profiler = PhaseProfiler()
    clock.advance(5.0)  # pre-phase bookkeeping starts the wall clock
    with profiler.measure(PipelinePhase.SOLVER):
        clock.advance(10.0)
    clock.advance(2.0)  # teardown
    profile = profiler.finalize()

    assert profile.sum_phase_s == pytest.approx(10.0)
    assert profile.total_wall_clock_s == pytest.approx(17.0)
    assert profile.unattributed_s == pytest.approx(7.0)
    assert profile.reconciliation_error is None
    assert profile.to_dict()["unattributed_s"] == pytest.approx(7.0)


def test_phases_exceeding_wall_clock_raise_a_reconciliation_error(clock):
    """Over-counting must be surfaced, never clamped to a clean zero."""
    profile = PhaseProfile(
        run_id="R-bad",
        records=(
            pp.PhaseRecord(
                phase=PipelinePhase.SOLVER,
                status=PhaseStatus.MEASURED,
                duration_s=10.0,
            ),
            pp.PhaseRecord(
                phase=PipelinePhase.DATA_EXTRACTION,
                status=PhaseStatus.MEASURED,
                duration_s=5.0,
            ),
        ),
        total_wall_clock_s=12.0,
    )

    assert profile.reconciliation_error is not None
    assert "exceed wall clock" in profile.reconciliation_error
    assert profile.to_dict()["reconciliation_error"] == profile.reconciliation_error


def test_not_run_phases_contribute_nothing_to_the_sum(clock):
    profiler = PhaseProfiler()
    with profiler.measure(PipelinePhase.CAD_PARSING):
        clock.advance(4.0)
    profiler.mark_not_run(PipelinePhase.SOLVER, reason="cached ODB")
    profile = profiler.finalize()

    assert profile.sum_phase_s == pytest.approx(4.0)
    assert profile.measured_phases and all(
        r.status is PhaseStatus.MEASURED for r in profile.measured_phases
    )


# ---------------------------------------------------------------------------
# External (already-measured) durations
# ---------------------------------------------------------------------------

def test_external_duration_enters_the_profile(clock):
    profiler = PhaseProfiler()
    profiler.record_external(
        PipelinePhase.SOLVER, 42.5, source="WatchedProcessResult.duration"
    )
    clock.advance(50.0)
    profile = profiler.finalize()

    record = profile.get(PipelinePhase.SOLVER)
    assert record.duration_s == 42.5
    assert record.detail["source"] == "WatchedProcessResult.duration"


@pytest.mark.parametrize(
    "bad_duration",
    [True, "10", None, -1.0],
    ids=["bool", "string", "none", "negative"],
)
def test_external_duration_validates_its_input(clock, bad_duration):
    profiler = PhaseProfiler()
    with pytest.raises(PhaseProfileError):
        profiler.record_external(PipelinePhase.SOLVER, bad_duration)


def test_external_duration_refused_while_another_phase_is_active(clock):
    profiler = PhaseProfiler()
    with profiler.measure(PipelinePhase.SOLVER):
        with pytest.raises(PhaseProfileError, match="while"):
            profiler.record_external(PipelinePhase.DATA_EXTRACTION, 1.0)


# ---------------------------------------------------------------------------
# Profiler bookkeeping is not caller territory
# ---------------------------------------------------------------------------

def test_caller_cannot_forge_the_attempts_counter(clock):
    profiler = PhaseProfiler()
    with pytest.raises(PhaseProfileError, match="reserved"):
        with profiler.measure(PipelinePhase.SOLVER, attempts=99):
            pass


# ---------------------------------------------------------------------------
# Model-facing summary stays bounded
# ---------------------------------------------------------------------------

def test_llm_summary_is_bounded_and_marks_missing_phases(clock):
    profiler = PhaseProfiler(run_id="R-summary")
    with profiler.measure(PipelinePhase.SOLVER):
        clock.advance(8.0)
    profile = profiler.finalize()

    summary = profile.to_llm_summary(max_chars=400)
    assert len(summary) < 400
    assert "T4_solver" in summary
    assert "not_run" in summary


def test_llm_summary_surfaces_reconciliation_errors():
    profile = PhaseProfile(
        run_id="R-bad",
        records=(
            pp.PhaseRecord(
                phase=PipelinePhase.SOLVER,
                status=PhaseStatus.MEASURED,
                duration_s=9.0,
            ),
        ),
        total_wall_clock_s=1.0,
    )
    assert "reconciliation_error" in profile.to_llm_summary()
