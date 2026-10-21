"""T4b solver-timing parser contract tests.

Layer of evidence: **unit only**, plus one assertion against the real ``.log``
that a real Abaqus 2025 job produced (see ``REAL_LOG`` below). The real-log test
runs only when that file is present on this machine -- it is git-ignored, so CI
alone does not prove the parser matches reality.

What these tests protect:

* a missing or unreadable measurement is ``None``, never ``0.0``;
* a truncated log is not reported as a short solve;
* multi-segment logs are summed only when they are demonstrably sequential;
* T4b is never derived from T4a by subtraction.

They do **not** establish that the parser handles every Abaqus log shape:
multi-step and restart layouts are unverified (no sample on this machine), which
is recorded in ``docs/phase-leftovers-tracking.md``.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from abaqus_ai_agent.execution.solver_timing import (
    LOG_RESOLUTION_S,
    SolverTimingStatus,
    parse_log_text,
    read_solver_timing,
    summarize_solver_timing,
)

#: A real single-element Abaqus 2025 job on this machine. Git-ignored; absent on
#: CI, where the matching test is skipped rather than faked.
REAL_LOG = pathlib.Path("runs/odb_sample_run/AIAgent_ODBSample.log")

_HEADER = "Analysis initiated from SIMULIA established products\nAbaqus JOB Job1\nAbaqus 2025\n"


def _log(*blocks: tuple[str, str, str, str, str]) -> str:
    """Build a log body from (begin, exe, t0, t1, end) tuples."""
    out = [_HEADER]
    for begin, exe, t0, t1, end in blocks:
        out.append(f"{begin}\n{t0}\nRun {exe}\n{t1}\n{end}\n")
    out.append("Abaqus JOB Job1 COMPLETED\n")
    return "".join(out)


_PRE = (
    "Begin Analysis Input File Processor",
    "pre.exe",
    "10/21/2026 9:27:46 AM",
    "10/21/2026 9:27:53 AM",
    "End Analysis Input File Processor",
)
_SOLVER = (
    "Begin Abaqus/Standard Analysis",
    "standard.exe",
    "10/21/2026 9:27:53 AM",
    "10/21/2026 9:28:00 AM",
    "End Abaqus/Standard Analysis",
)
_WRAP = (
    "Begin SIM Wrap-up",
    "SMASimUtility.exe",
    "10/21/2026 9:28:00 AM",
    "10/21/2026 9:28:01 AM",
    "End SIM Wrap-up",
)


# ---------------------------------------------------------------------------
# Single segment
# ---------------------------------------------------------------------------

def test_single_solver_segment_is_measured():
    timing = parse_log_text(_log(_PRE, _SOLVER, _WRAP))
    assert timing.status is SolverTimingStatus.MEASURED
    assert timing.solver_seconds == pytest.approx(7.0)
    assert timing.measured
    assert len(timing.solver_segments) == 1


def test_input_processing_and_wrap_up_are_not_counted_as_solve_time():
    """The whole point: 15s of job time, 7s of solver."""
    timing = parse_log_text(_log(_PRE, _SOLVER, _WRAP))
    assert timing.solver_seconds == pytest.approx(7.0)
    assert len(timing.segments) == 3


def test_segment_records_expose_boundaries():
    timing = parse_log_text(_log(_SOLVER))
    seg = timing.solver_segments[0]
    assert seg.executable == "standard.exe"
    assert seg.duration_s == pytest.approx(7.0)
    assert seg.complete
    assert seg.solver_match == "block_name"
    assert seg.started_local is not None and seg.finished_local is not None


def test_explicit_solver_is_recognised_by_block_name():
    text = _log((
        "Begin Abaqus/Explicit Analysis",
        "explicit.exe",
        "10/21/2026 10:00:00 AM",
        "10/21/2026 10:00:30 AM",
        "End Abaqus/Explicit Analysis",
    ))
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.MEASURED
    assert timing.solver_seconds == pytest.approx(30.0)


def test_unfamiliar_block_name_falls_back_to_executable():
    """A renamed block must not lose the solve time."""
    text = _log((
        "Begin Some Future Analysis",
        "standard.exe",
        "10/21/2026 10:00:00 AM",
        "10/21/2026 10:01:00 AM",
        "End Some Future Analysis",
    ))
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.MEASURED
    assert timing.solver_seconds == pytest.approx(60.0)
    assert timing.solver_segments[0].solver_match == "executable"


def test_crlf_and_lf_produce_identical_results():
    body = _log(_PRE, _SOLVER, _WRAP)
    assert parse_log_text(body).solver_seconds == parse_log_text(
        body.replace("\n", "\r\n")
    ).solver_seconds


# ---------------------------------------------------------------------------
# Multiple segments
# ---------------------------------------------------------------------------

def test_sequential_solver_segments_are_summed():
    """Restart-style layouts: successive runs of the same job."""
    text = _log(
        (
            "Begin Abaqus/Standard Analysis",
            "standard.exe",
            "10/21/2026 10:00:00 AM",
            "10/21/2026 10:00:20 AM",
            "End Abaqus/Standard Analysis",
        ),
        (
            "Begin Abaqus/Standard Analysis",
            "standard.exe",
            "10/21/2026 10:00:20 AM",
            "10/21/2026 10:00:35 AM",
            "End Abaqus/Standard Analysis",
        ),
    )
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.MEASURED
    assert timing.solver_seconds == pytest.approx(35.0)
    assert timing.detail["multi_segment"] is True
    assert any("summed" in n for n in timing.notes)


def test_overlapping_solver_segments_are_ambiguous_not_summed():
    """Two overlapping runs cannot both be this job's solve."""
    text = _log(
        (
            "Begin Abaqus/Standard Analysis",
            "standard.exe",
            "10/21/2026 10:00:00 AM",
            "10/21/2026 10:00:30 AM",
            "End Abaqus/Standard Analysis",
        ),
        (
            "Begin Abaqus/Standard Analysis",
            "standard.exe",
            "10/21/2026 10:00:10 AM",
            "10/21/2026 10:00:40 AM",
            "End Abaqus/Standard Analysis",
        ),
    )
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.AMBIGUOUS
    assert timing.solver_seconds is None
    assert not timing.measured


def test_identical_solver_segments_are_rejected_as_duplicates():
    """The same record counted twice would double the reported time."""
    text = _log(_SOLVER, _SOLVER)
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.AMBIGUOUS
    assert timing.solver_seconds is None


def test_two_job_headers_with_two_solver_runs_is_rejected():
    """Looks like two logs concatenated; summing would mix runs."""
    text = (
        _HEADER
        + _format(_SOLVER)
        + "Analysis initiated from SIMULIA established products\nAbaqus JOB Job1\n"
        + _format((
            "Begin Abaqus/Standard Analysis",
            "standard.exe",
            "10/21/2026 11:00:00 AM",
            "10/21/2026 11:00:10 AM",
            "End Abaqus/Standard Analysis",
        ))
    )
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.AMBIGUOUS
    assert timing.solver_seconds is None
    assert any("job headers" in n for n in timing.notes)


def _format(block: tuple[str, str, str, str, str]) -> str:
    begin, exe, t0, t1, end = block
    return f"{begin}\n{t0}\nRun {exe}\n{t1}\n{end}\n"


# ---------------------------------------------------------------------------
# Missing records: never a zero
# ---------------------------------------------------------------------------

def test_no_solver_segment_reports_none_not_zero():
    text = _log(_PRE, _WRAP)
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.NO_SOLVER_SEGMENT
    assert timing.solver_seconds is None
    assert timing.measured is False


def test_truncated_solver_segment_is_incomplete():
    """Solver started, end never written: the duration is unknown, not short."""
    text = (
        _HEADER
        + "Begin Analysis Input File Processor\n10/21/2026 9:27:46 AM\nRun pre.exe\n"
        + "10/21/2026 9:27:53 AM\nEnd Analysis Input File Processor\n"
        + "Begin Abaqus/Standard Analysis\n10/21/2026 9:27:53 AM\nRun standard.exe\n"
    )
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.INCOMPLETE
    assert timing.solver_seconds is None
    assert not timing.measured


def test_truncated_midway_through_end_marker_is_incomplete():
    """A log cut after the closing time but before 'End' still cannot be trusted."""
    text = (
        _HEADER
        + "Begin Abaqus/Standard Analysis\n10/21/2026 9:27:53 AM\nRun standard.exe\n"
        + "10/21/2026 9:28:00 AM\n"
    )
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.INCOMPLETE
    assert timing.solver_seconds is None


def test_empty_file_is_unparseable():
    timing = parse_log_text("")
    assert timing.status is SolverTimingStatus.UNPARSEABLE
    assert timing.solver_seconds is None


def test_garbage_file_is_unparseable():
    timing = parse_log_text("this is not an abaqus log\n" * 20)
    assert timing.status is SolverTimingStatus.UNPARSEABLE
    assert timing.solver_seconds is None


def test_missing_file_is_reported_not_raised(tmp_path):
    timing = read_solver_timing(tmp_path / "Absent.log")
    assert timing.status is SolverTimingStatus.FILE_MISSING
    assert timing.solver_seconds is None
    assert not timing.measured


# ---------------------------------------------------------------------------
# Malformed content
# ---------------------------------------------------------------------------

def test_missing_timestamps_leave_segment_incomplete():
    text = _log((
        "Begin Abaqus/Standard Analysis",
        "standard.exe",
        "",
        "",
        "End Abaqus/Standard Analysis",
    ))
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.INCOMPLETE
    assert timing.solver_seconds is None


def test_reversed_timestamps_are_not_accepted_as_negative_time():
    """A clock change or corrupted line must not yield a negative duration."""
    text = _log((
        "Begin Abaqus/Standard Analysis",
        "standard.exe",
        "10/21/2026 10:00:30 AM",
        "10/21/2026 10:00:00 AM",
        "End Abaqus/Standard Analysis",
    ))
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.INCOMPLETE
    assert timing.solver_seconds is None
    seg = timing.solver_segments[0]
    assert seg.duration_s is None


def test_malformed_timestamp_is_ignored_not_fatal():
    text = _log((
        "Begin Abaqus/Standard Analysis",
        "standard.exe",
        "99/99/2026 25:99:99 PM",
        "10/21/2026 10:00:00 AM",
        "End Abaqus/Standard Analysis",
    ))
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.INCOMPLETE
    assert timing.solver_seconds is None


def test_extra_timestamps_inside_a_segment_are_rejected():
    text = (
        _HEADER
        + "Begin Abaqus/Standard Analysis\n10/21/2026 10:00:00 AM\nRun standard.exe\n"
        + "10/21/2026 10:00:10 AM\n10/21/2026 10:00:20 AM\n"
        + "End Abaqus/Standard Analysis\n"
    )
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.INCOMPLETE
    assert timing.solver_seconds is None
    assert any("timestamps" in n for n in timing.notes)


def test_end_without_begin_does_not_crash():
    text = _HEADER + "End Abaqus/Standard Analysis\n"
    timing = parse_log_text(text)
    assert timing.solver_seconds is None
    assert timing.measured is False


def test_unclosed_segment_is_reported():
    text = (
        _HEADER
        + "Begin Abaqus/Standard Analysis\n10/21/2026 10:00:00 AM\nRun standard.exe\n"
        + "10/21/2026 10:00:10 AM\n"
        + "Begin SIM Wrap-up\n10/21/2026 10:00:10 AM\n"
    )
    timing = parse_log_text(text)
    assert any("no closing" in n for n in timing.notes)


# ---------------------------------------------------------------------------
# Payload contract
# ---------------------------------------------------------------------------

def test_payload_distinguishes_none_from_zero():
    measured = parse_log_text(_log(_SOLVER)).to_dict()
    absent = parse_log_text(_log(_PRE)).to_dict()
    assert measured["solver_seconds"] == pytest.approx(7.0)
    assert absent["solver_seconds"] is None
    assert measured["measured"] is True
    assert absent["measured"] is False


def test_payload_declares_resolution_and_timezone():
    payload = parse_log_text(_log(_SOLVER)).to_dict()
    assert payload["resolution_s"] == LOG_RESOLUTION_S == 1.0
    assert "local" in payload["timezone"]


def test_sub_second_solver_reports_zero_point_zero_not_none():
    """0.0 is a real (if unresolvable) measurement; it must stay 0.0."""
    text = _log((
        "Begin Abaqus/Standard Analysis",
        "standard.exe",
        "10/21/2026 10:00:00 AM",
        "10/21/2026 10:00:00 AM",
        "End Abaqus/Standard Analysis",
    ))
    timing = parse_log_text(text)
    assert timing.status is SolverTimingStatus.MEASURED
    assert timing.solver_seconds == 0.0
    assert timing.measured is True


# ---------------------------------------------------------------------------
# Aggregation: T4a and T4b stay separate
# ---------------------------------------------------------------------------

def test_summary_keeps_wait_and_solver_apart():
    timing = parse_log_text(_log(_PRE, _SOLVER, _WRAP))
    summary = summarize_solver_timing(15.0, timing)
    assert summary["t4a_wait"]["seconds"] == pytest.approx(15.0)
    assert summary["t4a_wait"]["scope"] == "submit_to_completion"
    assert summary["t4b_solver"]["solver_seconds"] == pytest.approx(7.0)
    assert summary["solver_share_of_wait"] == pytest.approx(0.4667, abs=1e-4)
    assert summary["derivation"] == "none"


def test_summary_never_backfills_from_wait():
    """A missing T4b stays missing even when T4a is available."""
    timing = parse_log_text(_log(_PRE, _WRAP))
    summary = summarize_solver_timing(15.0, timing)
    assert summary["t4a_wait"]["measured"] is True
    assert summary["t4b_solver"]["solver_seconds"] is None
    assert summary["t4b_solver"]["measured"] is False
    assert summary["solver_share_of_wait"] is None


def test_summary_without_wait_still_reports_solver_time():
    timing = parse_log_text(_log(_SOLVER))
    summary = summarize_solver_timing(None, timing)
    assert summary["t4a_wait"]["measured"] is False
    assert summary["t4a_wait"]["seconds"] is None
    assert summary["t4b_solver"]["solver_seconds"] == pytest.approx(7.0)
    assert summary["solver_share_of_wait"] is None


def test_summary_zero_wait_does_not_divide_by_zero():
    timing = parse_log_text(_log(_SOLVER))
    summary = summarize_solver_timing(0.0, timing)
    assert summary["solver_share_of_wait"] is None
    assert "zero" in summary["solver_share_note"]


# ---------------------------------------------------------------------------
# Real Abaqus artifact (skipped when absent)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not REAL_LOG.is_file(),
    reason="real Abaqus .log not present (git-ignored); parser-vs-reality "
    "agreement is verified on the machine that produced it",
)
def test_real_abaqus_log_matches_hand_counted_timing():
    """The single-element job: 15s total wait, 7s in standard.exe.

    Hand-counted from the log body:
        09:27:46 -> 09:27:53   pre.exe          7s
        09:27:53 -> 09:28:00   standard.exe     7s
        09:28:00 -> 09:28:01   SMASimUtility    1s
    """
    timing = read_solver_timing(REAL_LOG)
    assert timing.status is SolverTimingStatus.MEASURED
    assert timing.solver_seconds == pytest.approx(7.0)
    assert len(timing.segments) == 3
    assert len(timing.solver_segments) == 1
    assert os.path.basename(timing.solver_segments[0].executable) == "standard.exe"
    # The non-solver blocks must not leak into the solver total.
    assert timing.solver_seconds < sum(s.duration_s for s in timing.segments)


@pytest.mark.skipif(
    not REAL_LOG.is_file(),
    reason="real Abaqus .log not present",
)
def test_real_abaqus_log_dat_wallclock_is_coarse_but_present():
    """Documents why .dat alone is unusable at this scale.

    The real ``.dat`` records ``WALLCLOCK TIME (SEC) = 0`` for a job that ran
    ~7s, so second-scale work cannot be timed from it.
    """
    dat = REAL_LOG.with_suffix(".dat")
    if not dat.is_file():
        pytest.skip("matching .dat not present")
    text = dat.read_text(encoding="latin-1", errors="ignore")
    assert "WALLCLOCK TIME (SEC)" in text
    assert "       WALLCLOCK TIME (SEC) =            0" in text
