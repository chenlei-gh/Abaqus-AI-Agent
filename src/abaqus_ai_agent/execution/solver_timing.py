"""Parse solver run time out of an Abaqus job ``.log``.

Why this module exists
----------------------
``jobs.submit(wait=True)`` measures "submitted until finished", which is not the
same thing as "the solver ran". A real single-element job shows the gap:

    Begin Analysis Input File Processor   09:27:46
    Run pre.exe                           09:27:53
    Begin Abaqus/Standard Analysis        09:27:53
    Run standard.exe                      09:28:00
    Begin SIM Wrap-up                     09:28:00
    Run SMASimUtility.exe                 09:28:01

15 seconds of waiting, 7 of which were ``standard.exe``. Recording 15 as "solve
time" overstates it by more than 2x, so the two numbers are kept apart: T4a is
the wait, T4b is this module's output.

What this module refuses to do
------------------------------
* It never derives T4b by subtracting estimates from T4a. Subtraction compounds
  two uncertainties and can go negative while still looking like a number.
* It never reports ``0.0`` for "could not measure". ``solver_seconds`` is
  ``None`` whenever the value is not backed by a complete segment, and the
  accompanying status says why.
* It never treats a truncated or out-of-order log as a short solve.

Known limits (do not quietly upgrade these later)
-------------------------------------------------
* Timestamps carry **no timezone** and are local time, so this returns a
  duration, not an absolute instant. A DST transition during the solve would
  distort it.
* Timestamps have **1 second** resolution. A 7 second solve and a 7.4 second
  solve are indistinguishable, and a sub-second solver segment reports ``0.0``.
  Second-scale jobs therefore cannot support performance claims.
* The reported duration is that phase's wall clock. It is not CPU time, and it
  is not "the part of the solve that ``numCpus`` could speed up".
"""

from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..telemetry.phase_profile import PipelinePhase

#: .log files only contain phase markers, so they stay small even for large
#: analyses. The cap exists to keep a pathological file from being slurped, not
#: because normal logs approach it.
MAX_LOG_BYTES = 8 * 1024 * 1024

#: Resolution of the timestamps Abaqus writes into ``.log``.
LOG_RESOLUTION_S = 1.0

#: Blocks whose name marks a solver run. Matched case-insensitively.
_SOLVER_BLOCK_PATTERNS = (
    re.compile(r"abaqus/standard analysis", re.IGNORECASE),
    re.compile(r"abaqus/explicit analysis", re.IGNORECASE),
)

#: Executable basenames that indicate the solver, used only as a fallback when
#: the block name is unfamiliar. Standard and Explicit solvers (including double
#: precision binaries like ``standard_dp.exe`` and ``explicit_dp.exe``) are included.
#: Ancillary binaries such as ``pre.exe`` (input processing), ``package.exe``
#: (Explicit packager), and ``SMASimUtility.exe`` (wrap-up) are deliberately absent.
_SOLVER_EXECUTABLES = frozenset({
    "standard.exe",
    "standard_dp.exe",
    "explicit.exe",
    "explicit_dp.exe",
})

_BEGIN_RE = re.compile(r"^\s*Begin\s+(.+?)\s*$", re.IGNORECASE)
_END_RE = re.compile(r"^\s*End\s+(.+?)\s*$", re.IGNORECASE)
_RUN_RE = re.compile(r"^\s*Run\s+(\S+)\s*$", re.IGNORECASE)

#: ``10/21/2026 9:27:46 AM`` -- month/day/year, 12-hour clock, hour not
#: zero-padded. Abaqus writes local time with no zone, so this parses to a naive
#: datetime on purpose.
_TIMESTAMP_RE = re.compile(
    r"^\s*(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s*[AP]M)\s*$",
    re.IGNORECASE,
)

_TIMESTAMP_FORMAT = "%m/%d/%Y %I:%M:%S %p"

#: A job header is ``Abaqus JOB <name>`` exactly; ``Abaqus JOB <name> COMPLETED``
#: carries an extra token and must not be counted as a second run.
_JOB_HEADER_RE = re.compile(r"^\s*Abaqus\s+JOB\s+\S+\s*$", re.IGNORECASE)


class SolverTimingStatus(str, Enum):
    """Why ``solver_seconds`` has (or lacks) a value."""

    #: At least one complete solver segment, all consistent. ``solver_seconds`` set.
    MEASURED = "measured"
    #: A solver segment started but never recorded an end time (truncated run,
    #: killed job, or partially written log). Any number here would be invented.
    INCOMPLETE = "incomplete"
    #: Structurally inconsistent: overlapping or out-of-order segments, duplicate
    #: segments, or multiple job headers suggesting concatenated logs. Summing
    #: would double-count or mix runs.
    AMBIGUOUS = "ambiguous"
    #: The log parsed, but contains no solver segment at all (the job never
    #: reached the solver, or this is an input-processing-only log).
    NO_SOLVER_SEGMENT = "no_solver_segment"
    #: The file is absent or unreadable.
    FILE_MISSING = "file_missing"
    #: Nothing in the file looked like an Abaqus phase record.
    UNPARSEABLE = "unparseable"


#: Statuses that carry a usable duration.
MEASURED_STATUSES = frozenset({SolverTimingStatus.MEASURED})


@dataclass(frozen=True)
class LogSegment:
    """One ``Begin ... End`` block from the job log."""

    name: str
    executable: str = ""
    started_local: Optional[datetime.datetime] = None
    finished_local: Optional[datetime.datetime] = None
    #: ``None`` when the block is incomplete; never ``0.0`` as a stand-in.
    duration_s: Optional[float] = None
    complete: bool = False
    is_solver: bool = False
    #: How the segment was classified as a solver run: ``"block_name"``,
    #: ``"executable"``, or empty when it is not a solver segment.
    solver_match: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "executable": self.executable,
            "started_local": self.started_local.isoformat() if self.started_local else None,
            "finished_local": self.finished_local.isoformat() if self.finished_local else None,
            "duration_s": self.duration_s,
            "complete": self.complete,
            "is_solver": self.is_solver,
            "solver_match": self.solver_match,
        }


@dataclass(frozen=True)
class SolverTiming:
    """T4b: solver runtime as reported by the job log.

    Deliberately not a ``PipelinePhase``: the six-phase set is closed, and T4b is
    a sub-measurement of T4 rather than a seventh phase. Storing it as its own
    record keeps T4a (wait) and T4b (solver) from overwriting each other.
    """

    status: SolverTimingStatus
    #: Sum of complete solver segments, or ``None`` when not measured.
    solver_seconds: Optional[float] = None
    segments: Tuple[LogSegment, ...] = ()
    source: str = ""
    notes: Tuple[str, ...] = ()
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def measured(self) -> bool:
        return self.status in MEASURED_STATUSES and self.solver_seconds is not None

    @property
    def solver_segments(self) -> Tuple[LogSegment, ...]:
        return tuple(s for s in self.segments if s.is_solver)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "measured": self.measured,
            #: Present so a consumer can never mistake a missing measurement for
            #: a fast one: ``None`` means "unknown", ``0.0`` means "sub-second".
            "solver_seconds": self.solver_seconds,
            "resolution_s": LOG_RESOLUTION_S,
            "timezone": "local (no zone recorded in .log)",
            "segments_count": len(self.segments),
            "solver_segments_count": len(self.solver_segments),
            "segments": [s.to_dict() for s in self.segments],
            "source": self.source,
            "notes": list(self.notes),
            "detail": dict(self.detail),
        }


@dataclass
class _RawSegment:
    name: str
    executable: str = ""
    timestamps: List[datetime.datetime] = field(default_factory=list)
    closed: bool = False


def _parse_timestamp(line: str) -> Optional[datetime.datetime]:
    match = _TIMESTAMP_RE.match(line)
    if match is None:
        return None
    try:
        return datetime.datetime.strptime(match.group(1), _TIMESTAMP_FORMAT)
    except ValueError:
        # A 12-hour clock with AM/PM parses strictly; a malformed stamp is
        # treated as "not a timestamp" rather than aborting the whole log.
        return None


def _read_lines(text: str) -> List[str]:
    # Universal newlines: real logs are CRLF on Windows, synthetic fixtures may
    # not be, and neither should change the result.
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _collect_raw_segments(lines: Sequence[str]) -> Tuple[List[_RawSegment], List[str]]:
    """Group lines into ``Begin ... End`` blocks, keeping timestamps in order."""
    segments: List[_RawSegment] = []
    problems: List[str] = []
    current: Optional[_RawSegment] = None

    for line in lines:
        begin = _BEGIN_RE.match(line)
        if begin is not None:
            if current is not None and not current.closed:
                problems.append(f"segment '{current.name}' reopened before it ended")
            current = _RawSegment(name=begin.group(1).strip())
            segments.append(current)
            continue

        end = _END_RE.match(line)
        if end is not None:
            if current is None:
                problems.append(f"unmatched 'End {end.group(1).strip()}'")
                continue
            current.closed = True
            current = None
            continue

        if current is None:
            continue

        run = _RUN_RE.match(line)
        if run is not None:
            if current.executable:
                problems.append(
                    f"segment '{current.name}' lists more than one executable"
                )
            current.executable = run.group(1).strip()
            continue

        stamp = _parse_timestamp(line)
        if stamp is not None:
            current.timestamps.append(stamp)

    if current is not None and not current.closed:
        problems.append(f"segment '{current.name}' has no closing 'End'")

    return segments, problems


def _classify_solver(raw: _RawSegment) -> Tuple[bool, str]:
    for pattern in _SOLVER_BLOCK_PATTERNS:
        if pattern.search(raw.name):
            return True, "block_name"
    executable = os.path.basename(raw.executable).lower()
    if executable in _SOLVER_EXECUTABLES:
        return True, "executable"
    return False, ""


def parse_log_text(text: str, source: str = "") -> SolverTiming:
    """Parse an Abaqus ``.log`` body into a :class:`SolverTiming`.

    Never raises for malformed content: a log we cannot read is reported as
    ``UNPARSEABLE``, not as a zero-second solve.
    """
    lines = _read_lines(text)
    job_headers = sum(1 for line in lines if _JOB_HEADER_RE.match(line))
    raw_segments, problems = _collect_raw_segments(lines)

    if not raw_segments:
        return SolverTiming(
            status=SolverTimingStatus.UNPARSEABLE,
            segments=(),
            source=source,
            notes=tuple(problems) + ("no 'Begin ... End' phase block found",),
            detail={"job_headers": job_headers},
        )

    resolved: List[LogSegment] = []
    for raw in raw_segments:
        is_solver, matched_by = _classify_solver(raw)
        started = raw.timestamps[0] if raw.timestamps else None
        finished = raw.timestamps[1] if len(raw.timestamps) > 1 else None
        complete = (
            raw.closed
            and started is not None
            and finished is not None
            and finished >= started
        )
        duration = None
        if complete:
            duration = round((finished - started).total_seconds(), 6)
        if len(raw.timestamps) > 2:
            problems.append(
                f"segment '{raw.name}' carries {len(raw.timestamps)} timestamps; "
                "expected at most 2"
            )
            complete = False
            duration = None
        resolved.append(
            LogSegment(
                name=raw.name,
                executable=raw.executable,
                started_local=started,
                finished_local=finished,
                duration_s=duration,
                complete=complete,
                is_solver=is_solver,
                solver_match=matched_by,
            )
        )

    solver_segments = [s for s in resolved if s.is_solver]
    detail: Dict[str, Any] = {
        "job_headers": job_headers,
        "segments_total": len(resolved),
        "solver_segments": len(solver_segments),
    }

    if not solver_segments:
        return SolverTiming(
            status=SolverTimingStatus.NO_SOLVER_SEGMENT,
            segments=tuple(resolved),
            source=source,
            notes=tuple(problems) + ("log parsed but contains no solver segment",),
            detail=detail,
        )

    incomplete = [s for s in solver_segments if not s.complete]
    if incomplete:
        # A started-but-unfinished solver segment means the solve we are trying
        # to measure has no known end. Reporting only the completed segments
        # would understate it, and this is precisely the number a performance
        # claim would lean on.
        return SolverTiming(
            status=SolverTimingStatus.INCOMPLETE,
            segments=tuple(resolved),
            source=source,
            notes=tuple(problems)
            + tuple(
                f"solver segment '{s.name}' is incomplete; duration unknown" for s in incomplete
            ),
            detail=detail,
        )

    # Overlap / ordering checks. Two solver segments that overlap cannot both be
    # separate runs, and a segment that starts before a previous one ends means
    # the file is not a single chronological record.
    ambiguous: List[str] = []
    previous_end: Optional[datetime.datetime] = None
    for seg in solver_segments:
        if previous_end is not None and seg.started_local is not None:
            if seg.started_local < previous_end:
                ambiguous.append(
                    f"solver segment '{seg.name}' starts before the previous one ends"
                )
        if seg.finished_local is not None:
            previous_end = seg.finished_local

    seen: set = set()
    for seg in solver_segments:
        key = (
            seg.name,
            seg.started_local.isoformat() if seg.started_local else "",
            seg.finished_local.isoformat() if seg.finished_local else "",
        )
        if key in seen:
            ambiguous.append(f"duplicate solver segment '{seg.name}' at the same timestamps")
        seen.add(key)

    if job_headers > 1 and len(solver_segments) > 1:
        # Multiple job headers with multiple solver runs looks like two logs
        # concatenated. Summing them would report another run's solve time.
        ambiguous.append(
            f"{job_headers} job headers with {len(solver_segments)} solver segments; "
            "the file may hold more than one run"
        )

    if ambiguous:
        return SolverTiming(
            status=SolverTimingStatus.AMBIGUOUS,
            segments=tuple(resolved),
            source=source,
            notes=tuple(problems) + tuple(ambiguous),
            detail=detail,
        )

    total = round(sum(s.duration_s or 0.0 for s in solver_segments), 6)
    notes = list(problems)
    if len(solver_segments) > 1:
        notes.append(
            f"{len(solver_segments)} solver segments summed; this assumes they are "
            "successive runs of the same job (e.g. restart), not repeated records"
        )
    detail["multi_segment"] = len(solver_segments) > 1

    return SolverTiming(
        status=SolverTimingStatus.MEASURED,
        solver_seconds=total,
        segments=tuple(resolved),
        source=source,
        notes=tuple(notes),
        detail=detail,
    )


def read_solver_timing(log_path: Union[str, os.PathLike]) -> SolverTiming:
    """Read and parse ``log_path`` (an Abaqus ``<job>.log``)."""
    path = os.fspath(log_path)
    if not os.path.isfile(path):
        return SolverTiming(
            status=SolverTimingStatus.FILE_MISSING,
            source=path,
            notes=(f"log file not found: {path}",),
        )
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_LOG_BYTES + 1)
    except OSError as exc:
        return SolverTiming(
            status=SolverTimingStatus.FILE_MISSING,
            source=path,
            notes=(f"log file unreadable: {exc}",),
        )

    notes: List[str] = []
    if len(raw) > MAX_LOG_BYTES:
        # Keep the head: the phase blocks start at the top of the file, and the
        # tail of an oversized log holds no timing information.
        raw = raw[:MAX_LOG_BYTES]
        notes.append(f"log truncated to first {MAX_LOG_BYTES} bytes")

    # latin-1 round-trips any byte, so a stray non-UTF-8 character cannot turn a
    # readable log into "unparseable".
    timing = parse_log_text(raw.decode("latin-1"), source=path)
    if notes:
        return SolverTiming(
            status=timing.status,
            solver_seconds=timing.solver_seconds,
            segments=timing.segments,
            source=timing.source,
            notes=tuple(notes) + timing.notes,
            detail=timing.detail,
        )
    return timing


#: Below this, 1 s quantization makes T4b usable only for order-of-magnitude
#: judgement, not for comparing runs. Mirrors contract clause A2-7.
PRECISION_LIMITED_BELOW_S = 10.0

#: ``detail`` keys owned by the profiler; passing one of these makes
#: ``record_external`` raise, which would drop the whole measurement.
_PROFILER_RESERVED_DETAIL_KEYS = frozenset({"attempts"})


def attach_solver_timing(
    profiler: Any,
    wait_seconds: Optional[float],
    timing: SolverTiming,
    *,
    wait_status: str = "",
) -> Dict[str, Any]:
    """Record T4a and T4b into a ``PhaseProfiler`` without one overwriting the other.

    The profiler keeps exactly one record per phase (``_measured`` is keyed by
    ``PipelinePhase``), and a second write to ``SOLVER`` replaces the first while
    bumping ``attempts``. So T4b cannot be a second ``record_external(SOLVER)``
    call: it would erase T4a, or be erased by it. It is stored as
    ``detail["t4b"]`` on the single ``SOLVER`` record instead.

    This is a deliberate deviation from contract clauses A2-3 and A2-4, which ask
    for T4b to be its own ``record_external`` record and for a missing T4b to be
    ``NOT_RUN``. Those two cannot coexist with the one-record-per-phase rule
    without losing one of the two numbers. The deviation is recorded in
    ``detail["t4b"]["contract_note"]`` rather than silently reinterpreting the
    clause. See ``docs/a2-solver-timing-contract.md``.

    What this function guarantees instead:

    * T4a and T4b are both present in the serialized profile, under different keys.
    * A missing or failed T4b is ``"not_measured"`` with ``solver_seconds=None``,
      never ``0.0`` and never back-filled from the wait.
    * T4b is never computed by subtracting anything from T4a.

    Returns the same dict as ``summarize_solver_timing`` so callers can persist the
    aggregate without a second pass. ``profiler`` is typed loosely to avoid an
    import cycle between ``execution`` and ``telemetry``.
    """
    summary = summarize_solver_timing(wait_seconds, timing, wait_status=wait_status)

    t4b_detail = timing.to_dict()
    t4b_detail["scope"] = "solver_only"
    t4b_detail["precision_limited"] = bool(
        timing.measured and timing.solver_seconds < PRECISION_LIMITED_BELOW_S
    )
    t4b_detail["contract_note"] = (
        "stored as detail of the SOLVER record, not as its own record_external "
        "call: the profiler keeps one record per phase, so a second SOLVER write "
        "would overwrite T4a. Deviates from contract clauses A2-3 and A2-4."
    )

    reserved = _PROFILER_RESERVED_DETAIL_KEYS & set(t4b_detail)
    if reserved:  # pragma: no cover - defensive; to_dict() never emits these
        raise ValueError(
            f"T4b detail collides with profiler-reserved keys: {sorted(reserved)}"
        )

    if wait_seconds is None:
        # No wait measurement exists. Recording SOLVER as measured with a made-up
        # duration would be exactly the failure mode this split exists to prevent,
        # so the phase stays explicitly not-run and T4b rides along in its detail.
        profiler.mark_not_run(
            PipelinePhase.SOLVER,
            reason="T4a wait duration not measured",
        )
        # mark_not_run only carries a reason string, so attach T4b by recording it
        # on the aggregate the caller persists. The phase record itself says why
        # it is empty.
        summary["recorded_as"] = "not_run"
        summary["t4b_attached"] = False
        summary["t4b_attachment_note"] = (
            "no T4a measurement to attach T4b to; phase marked NOT_RUN and T4b is "
            "only in this summary, not in the phase record"
        )
        return summary

    record = profiler.record_external(
        PipelinePhase.SOLVER,
        wait_seconds,
        scope="wait",
        t4b=t4b_detail,
    )
    # record_external degrades to NOT_RUN on a rejected duration instead of
    # raising. Surface that, because a caller who only checks the return value of
    # this function would otherwise believe T4a was stored.
    summary["recorded_as"] = record.status.value
    summary["t4b_attached"] = "t4b" in record.detail
    return summary


def summarize_solver_timing(
    wait_seconds: Optional[float],
    timing: SolverTiming,
    *,
    wait_status: str = "",
) -> Dict[str, Any]:
    """Aggregate T4a and T4b **without** deriving either from the other.

    The two values answer different questions and are never combined into a
    single "solve time". ``solver_share_of_wait`` is offered only when both are
    measured and the wait is positive, because it is the one derived number that
    stays meaningful (it is a ratio, not a subtraction).
    """
    wait_measured = wait_seconds is not None
    summary: Dict[str, Any] = {
        "t4a_wait": {
            "seconds": wait_seconds,
            "measured": wait_measured,
            "status": wait_status or ("measured" if wait_measured else "not_measured"),
            "scope": "submit_to_completion",
        },
        "t4b_solver": timing.to_dict(),
        # Explicitly absent fields, documented so nobody reinvents them:
        "derivation": "none",
    }
    if not wait_measured or not timing.measured or not wait_seconds:
        summary["solver_share_of_wait"] = None
        summary["solver_share_note"] = (
            "undefined without both a measured wait and a measured solver duration"
            if not (wait_measured and timing.measured)
            else "wait duration is zero; ratio undefined"
        )
    else:
        summary["solver_share_of_wait"] = round(timing.solver_seconds / wait_seconds, 4)
        summary["solver_share_note"] = (
            "ratio only; the remainder is pre-processing, wrap-up and queueing, "
            "not an estimate of anything"
        )
    return summary
