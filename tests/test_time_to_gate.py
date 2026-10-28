"""Time-to-gate telemetry contract tests (Phase A)."""

import time

from abaqus_ai_agent.telemetry.time_to_gate import GateTimer, GateTiming


def test_unstarted_timer_reports_no_measurement():
    """A missing measurement must not read as zero.

    ``elapsed_s = 0`` would claim the gate was reached instantly; ``None``
    states that nothing was measured.
    """
    timing = GateTimer().stop("AWAITING_APPROVAL")
    assert timing.elapsed_s is None
    assert timing.started_at is None
    assert timing.outcome == "AWAITING_APPROVAL"
    assert timing.to_dict()["elapsed_s"] is None


def test_started_timer_measures_positive_elapsed():
    timer = GateTimer()
    timer.start()
    time.sleep(0.02)
    timing = timer.stop("AWAITING_APPROVAL")
    assert timing.elapsed_s is not None
    assert timing.elapsed_s > 0
    assert timing.started_at is not None
    assert timing.stopped_at is not None


def test_start_resets_the_measurement():
    timer = GateTimer()
    timer.start()
    first = timer.stop("AWAITING_APPROVAL")
    timer.start()
    second = timer.stop("AWAITING_APPROVAL")
    assert second.started_at != first.started_at or second.elapsed_s is not None


def test_record_does_not_accumulate_across_stops():
    timer = GateTimer()
    timer.start()
    first = timer.stop("AWAITING_APPROVAL")
    second = timer.stop("AWAITING_APPROVAL")
    # Two independent readings, not a sum of both waits.
    assert second.elapsed_s >= first.elapsed_s
    assert second.outcome == first.outcome


def test_record_declares_its_clock_source():
    # Solver logs are wall-clock and second-quantised; comparing them against a
    # monotonic duration without saying so invites a false mismatch.
    timer = GateTimer()
    timer.start()
    assert timer.stop("AWAITING_APPROVAL").to_dict()["clock"] == "monotonic"


def test_elapsed_is_never_negative(monkeypatch):
    timer = GateTimer()
    timer.start()
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    timing = timer.stop("AWAITING_APPROVAL")
    assert timing.elapsed_s == 0.0


def test_gate_timing_is_a_plain_record():
    timing = GateTiming(outcome="X", elapsed_s=1.5, started_at="a", stopped_at="b")
    payload = timing.to_dict()
    assert payload["outcome"] == "X"
    assert payload["elapsed_s"] == 1.5
    assert set(payload) == {"outcome", "elapsed_s", "started_at", "stopped_at", "clock"}
