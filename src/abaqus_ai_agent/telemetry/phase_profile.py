"""Full-lifecycle phase profiling for CAE runs.

Governance Plan 阶段 3 第 1 项:

    接入 T1 ~ T6 细分阶段打点（CAD 解析、网格编译、License 排队、物理求解、
    数据提取、报告生成）

Scope of this module: it *observes* time. It never decides whether a run succeeded,
never changes solver parameters, and never alters task lifecycle semantics. A run
that fails still fails the same way, with the same exception, whether or not it is
profiled.

Contract
--------
1. **Explicit phase set.** ``PipelinePhase`` is the closed set of six phases. A
   profile always reports all six, so a reader can see what was *not* measured
   instead of inferring zero from an absent key.
2. **Durations use a monotonic clock.** ``time.monotonic()`` is immune to wall-clock
   adjustments; the wall-clock start/end are recorded alongside for auditability.
3. **Failure is a recorded outcome, not a lost measurement.** A phase that raises
   keeps its duration up to the failure plus the exception type, and is marked
   ``FAILED``. The exception is re-raised unchanged.
4. **Not measuring is distinct from measuring zero.** A phase never entered is
   ``NOT_RUN`` with ``duration_s = None``. Zero always means "measured, took no
   time".
5. **Phases do not overlap.** Concurrent phases would double-count and make the
   breakdown sum meaningless, so entering a phase while another is active is a
   contract violation and raises ``PhaseProfileError``.
6. **The breakdown must reconcile with the wall clock.** On finalize, the residual
   between measured wall clock and the sum of phases is reported as
   ``unattributed_s``. It is never silently folded into a phase.
"""

from __future__ import annotations

import datetime
import json
import math
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Tuple

#: Tolerance for float reconciliation between summed phases and wall clock.
RECONCILIATION_TOLERANCE_S = 1e-6

#: Detail key owned by the profiler. Callers may not set it.
_ATTEMPTS_KEY = "attempts"


class PhaseProfileError(RuntimeError):
    """Raised when the profiling contract itself is violated (not a run failure)."""


class PipelinePhase(str, Enum):
    """The six lifecycle phases required by 阶段 3 第 1 项.

    Ordering mirrors the governance plan (T1 -> T6). Labels are what appear in
    reports; the enum values stay stable so persisted profiles remain readable.
    """

    CAD_PARSING = "T1_cad_parsing"
    MESH_COMPILATION = "T2_mesh_compilation"
    LICENSE_QUEUE = "T3_license_queue"
    SOLVER = "T4_solver"
    DATA_EXTRACTION = "T5_data_extraction"
    REPORT_GENERATION = "T6_report_generation"

    @property
    def order(self) -> int:
        return _PHASE_ORDER[self]

    @property
    def label(self) -> str:
        return _PHASE_LABEL[self]


_PHASE_ORDER: Dict["PipelinePhase", int] = {
    PipelinePhase.CAD_PARSING: 1,
    PipelinePhase.MESH_COMPILATION: 2,
    PipelinePhase.LICENSE_QUEUE: 3,
    PipelinePhase.SOLVER: 4,
    PipelinePhase.DATA_EXTRACTION: 5,
    PipelinePhase.REPORT_GENERATION: 6,
}

_PHASE_LABEL: Dict["PipelinePhase", str] = {
    PipelinePhase.CAD_PARSING: "CAD parsing",
    PipelinePhase.MESH_COMPILATION: "Mesh compilation",
    PipelinePhase.LICENSE_QUEUE: "License queue",
    PipelinePhase.SOLVER: "Physics solve",
    PipelinePhase.DATA_EXTRACTION: "Data extraction",
    PipelinePhase.REPORT_GENERATION: "Report generation",
}


class PhaseStatus(str, Enum):
    """Outcome of one phase measurement."""

    MEASURED = "measured"   # entered and returned normally
    FAILED = "failed"       # entered and raised; duration covers the attempt
    NOT_RUN = "not_run"     # never entered; duration is None, never 0.0


@dataclass(frozen=True)
class PhaseRecord:
    """Immutable record of a single phase attempt."""

    phase: PipelinePhase
    status: PhaseStatus
    duration_s: Optional[float] = None
    started_at_utc: str = ""
    finished_at_utc: str = ""
    exception_type: str = ""
    exception_message: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_measured(self) -> bool:
        return self.status is not PhaseStatus.NOT_RUN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase.value,
            "order": self.phase.order,
            "label": self.phase.label,
            "status": self.status.value,
            "duration_s": self.duration_s,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "detail": dict(self.detail),
        }


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class PhaseProfiler:
    """Sequential, non-overlapping phase timer for one run.

    Usage::

        profiler = PhaseProfiler(run_id="...")
        with profiler.measure(PipelinePhase.CAD_PARSING):
            ...
        profile = profiler.finalize()

    The profiler holds no global state and is not thread-safe by design: a run's
    phases are sequential, and pretending otherwise would hide a real overlap.
    """

    def __init__(self, run_id: str = "", strict: bool = True) -> None:
        self.run_id = run_id
        # ``strict`` decides what happens when the *profiling contract* is violated
        # (phase overlap, double finalize, reserved detail keys). It never decides
        # what happens to the measured code's own exception, which always propagates.
        #
        # strict=True  -> contract violations raise PhaseProfileError. Correct for
        #                 tests and for callers who want the bug surfaced loudly.
        # strict=False -> violations are recorded in ``internal_errors`` and the
        #                 profiler degrades to "no data for that phase". This is the
        #                 mode for wiring into a production run: observation must not
        #                 become a new failure source.
        self.strict = strict
        self.internal_errors: List[str] = []
        self._measured: Dict[PipelinePhase, PhaseRecord] = {}
        self._active: Optional[PipelinePhase] = None
        # The wall clock starts at construction, not at the first phase. Otherwise
        # work done before the first measurement would vanish from the total and
        # ``unattributed_s`` would understate the real overhead.
        self._started_monotonic: float = time.monotonic()
        self._finalized = False

    def _violation(self, message: str) -> None:
        """Report a contract violation: raise in strict mode, record otherwise."""
        if self.strict:
            raise PhaseProfileError(message)
        self.internal_errors.append(message)

    # -- measurement ------------------------------------------------------

    def _now(self) -> float:
        return time.monotonic()

    def _store(self, record: PhaseRecord) -> PhaseRecord:
        # ``attempts`` is profiler bookkeeping; a caller-provided value would corrupt
        # the retry counter and is rejected rather than silently overwritten.
        if _ATTEMPTS_KEY in record.detail:
            raise PhaseProfileError(
                f"'{_ATTEMPTS_KEY}' is reserved for profiler bookkeeping."
            )
        # A phase is expected to run once. If it runs twice, the later attempt wins:
        # it reflects the run's final state, and keeping both would double-count in
        # ``sum_phase_s``. Overwrites are observable through ``detail["attempts"]``.
        previous = self._measured.get(record.phase)
        attempts = 1
        if previous is not None:
            attempts = int(previous.detail.get(_ATTEMPTS_KEY, 1)) + 1
            if attempts > 2:
                raise PhaseProfileError(
                    f"Phase {record.phase.value} measured more than twice; the run is "
                    "looping through the same phase."
                )
            record = replace(record, detail={**record.detail, _ATTEMPTS_KEY: attempts})
        self._measured[record.phase] = record
        return record

    @contextmanager
    def measure(self, phase: PipelinePhase, **detail: Any) -> Iterator[None]:
        """Time one phase. Exceptions from the body propagate unchanged, always.

        Isolation guarantee (independent of ``strict``): if the profiler itself fails
        while recording -- a clock error, a full disk on UTC formatting, a reserved
        detail key -- the body's own exception is re-raised and the profiling fault is
        demoted to ``internal_errors``. Turning a successful phase into a failure, or
        masking a real exception with a bookkeeping one, would make the observer more
        dangerous than the thing it observes.
        """
        if self._finalized:
            self._violation("Cannot measure a phase after finalize().")
            yield
            return
        if self._active is not None:
            self._violation(
                f"Phase {phase.value} entered while {self._active.value} is still active. "
                "Phases must not overlap; concurrent phases make the breakdown sum "
                "meaningless."
            )
            yield
            return

        self._active = phase
        try:
            started = self._now()
            started_utc = _utc_now_iso()
        except Exception as exc:  # pragma: no cover - clock/format failure is exotic
            self._active = None
            self._note_internal(f"could not start timing {phase.value}: {exc!r}")
            yield
            return

        try:
            yield
        except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised verbatim
            self._safe_store(phase, PhaseStatus.FAILED, started, started_utc, detail, exc)
            raise
        else:
            self._safe_store(phase, PhaseStatus.MEASURED, started, started_utc, detail, None)
        finally:
            self._active = None

    def _note_internal(self, message: str) -> None:
        self.internal_errors.append(message)

    def _safe_store(
        self,
        phase: PipelinePhase,
        status: PhaseStatus,
        started: float,
        started_utc: str,
        detail: Dict[str, Any],
        exc: Optional[BaseException],
    ) -> None:
        """Record a finished phase without ever replacing the body's outcome."""
        try:
            finished = time.monotonic()
            self._store(PhaseRecord(
                phase=phase,
                status=status,
                duration_s=round(finished - started, 6),
                started_at_utc=started_utc,
                finished_at_utc=_utc_now_iso(),
                exception_type=type(exc).__name__ if exc is not None else "",
                exception_message=str(exc) if exc is not None else "",
                detail=dict(detail),
            ))
        except Exception as store_exc:
            message = f"could not record {phase.value} as {status.value}: {store_exc!r}"
            self._note_internal(message)
            # Precedence rule: an exception already in flight from the measured body
            # always wins. Masking a real failure with a bookkeeping one would send
            # the caller chasing the profiler instead of the actual defect.
            if exc is None and self.strict:
                raise PhaseProfileError(message) from store_exc

    def record_external(
        self,
        phase: PipelinePhase,
        duration_s: float,
        **detail: Any,
    ) -> PhaseRecord:
        """Record a duration measured elsewhere (watchdog, lmstat poll, subprocess).

        Some components already measure themselves but must not be refactored to
        return that number (``WatchedProcessResult.duration`` sits on the solver
        hot path). This adapter lets such a measurement enter the profile without
        changing those modules' semantics or return shapes.
        """
        if self._finalized:
            self._violation("Cannot record a phase after finalize().")
            return PhaseRecord(phase=phase, status=PhaseStatus.NOT_RUN)
        if self._active is not None:
            self._violation(
                f"Cannot record {phase.value} while {self._active.value} is active."
            )
            return PhaseRecord(phase=phase, status=PhaseStatus.NOT_RUN)
        problem = self._duration_problem(duration_s)
        if problem is not None:
            self._violation(problem)
            return PhaseRecord(phase=phase, status=PhaseStatus.NOT_RUN)
        record = PhaseRecord(
            phase=phase,
            status=PhaseStatus.MEASURED,
            duration_s=round(float(duration_s), 6),
            started_at_utc="",
            finished_at_utc="",
            detail=dict(detail),
        )
        try:
            return self._store(record)
        except Exception as store_exc:
            self._note_internal(f"could not record {phase.value}: {store_exc!r}")
            return PhaseRecord(phase=phase, status=PhaseStatus.NOT_RUN)

    @staticmethod
    def _duration_problem(duration_s: Any) -> Optional[str]:
        """Return a reason string when ``duration_s`` is not acceptable.

        Separate from the raising path so both ``strict`` modes can share one rule;
        duplicating the checks is how validation quietly drifts apart.
        """
        if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)):
            return f"duration_s must be a number, got {type(duration_s).__name__}."
        # Non-finite values pass a ``< 0`` check (nan and inf both compare False),
        # and would poison sum_phase_s / unattributed_s while still looking measured.
        if not math.isfinite(duration_s):
            return f"duration_s must be finite, got {duration_s!r}."
        if duration_s < 0:
            return f"duration_s must be non-negative, got {duration_s}."
        return None

    def mark_not_run(self, phase: PipelinePhase, reason: str = "") -> PhaseRecord:
        """Record that a phase was deliberately skipped, without inventing a 0.0."""
        if self._finalized:
            self._violation("Cannot mark a phase after finalize().")
            return PhaseRecord(phase=phase, status=PhaseStatus.NOT_RUN)
        # Same conflict rule as record_external(): marking a phase while another
        # measurement is open would let a later close overwrite this NOT_RUN and
        # inflate the retry counter with contradictory states.
        if self._active is not None:
            self._violation(
                f"Cannot mark {phase.value} while {self._active.value} is active."
            )
            return PhaseRecord(phase=phase, status=PhaseStatus.NOT_RUN)
        if phase in self._measured and self._measured[phase].is_measured:
            self._violation(
                f"Phase {phase.value} already has a measurement; refusing to overwrite "
                "it with NOT_RUN."
            )
            return self._measured[phase]
        record = PhaseRecord(
            phase=phase,
            status=PhaseStatus.NOT_RUN,
            duration_s=None,
            detail={"reason": reason} if reason else {},
        )
        self._measured[phase] = record
        return record

    # -- reporting --------------------------------------------------------

    def finalize(self) -> "PhaseProfile":
        """Close the profile and reconcile phase durations against the wall clock."""
        if self._finalized:
            note = "finalize() already called."
            if self.strict:
                raise PhaseProfileError(note)
            self._note_internal(note)
        if self._active is not None:
            note = f"Cannot finalize while {self._active.value} is still active."
            if self.strict:
                raise PhaseProfileError(note)
            self._note_internal(note)
            # The stale active phase would otherwise make every later call a
            # violation; the profile is being closed, so the window is over.
            self._active = None
        self._finalized = True

        total_wall = time.monotonic() - self._started_monotonic

        return PhaseProfile(
            run_id=self.run_id,
            records=tuple(
                self._measured.get(p) or PhaseRecord(phase=p, status=PhaseStatus.NOT_RUN)
                for p in sorted(PipelinePhase, key=lambda p: p.order)
            ),
            total_wall_clock_s=round(total_wall, 6),
            internal_errors=tuple(self.internal_errors),
        )


@dataclass(frozen=True)
class PhaseProfile:
    """Immutable, reconciled view of a run's phase timings."""

    run_id: str
    records: Tuple[PhaseRecord, ...]
    total_wall_clock_s: float
    schema: str = "phase_profile_v1"
    #: Contract violations demoted by ``strict=False``. Empty means the profile is
    #: clean. Non-empty means the timing data may be incomplete, not that the run
    #: failed: this field exists so silent degradation is still visible.
    internal_errors: Tuple[str, ...] = ()

    @property
    def measured_phases(self) -> Tuple[PhaseRecord, ...]:
        return tuple(r for r in self.records if r.is_measured)

    @property
    def sum_phase_s(self) -> float:
        """Sum of measured phase durations. NOT_RUN phases contribute nothing."""
        return round(sum(r.duration_s or 0.0 for r in self.measured_phases), 6)

    @property
    def unattributed_s(self) -> float:
        """Wall clock not covered by any phase (init, teardown, bookkeeping).

        A negative value means the phases overlap or exceed the clock. It is reported
        as-is, never clamped to zero, so that ``reconciliation_error`` can surface the
        violation instead of a clean-looking residual hiding it.
        """
        return round(self.total_wall_clock_s - self.sum_phase_s, 6)

    @property
    def reconciliation_error(self) -> Optional[str]:
        """``None`` when consistent; otherwise a human-readable reason."""
        residual = self.total_wall_clock_s - self.sum_phase_s
        if residual < -RECONCILIATION_TOLERANCE_S:
            return (
                f"Phase durations ({self.sum_phase_s:.6f}s) exceed wall clock "
                f"({self.total_wall_clock_s:.6f}s) by {-residual:.6f}s; "
                "phases overlap or the clock is inconsistent."
            )
        return None

    @property
    def failed_phases(self) -> Tuple[PhaseRecord, ...]:
        return tuple(r for r in self.records if r.status is PhaseStatus.FAILED)

    @property
    def not_run_phases(self) -> Tuple[PipelinePhase, ...]:
        return tuple(r.phase for r in self.records if r.status is PhaseStatus.NOT_RUN)

    def get(self, phase: PipelinePhase) -> PhaseRecord:
        for record in self.records:
            if record.phase is phase:
                return record
        return PhaseRecord(phase=phase, status=PhaseStatus.NOT_RUN)

    def to_dict(self) -> Dict[str, Any]:
        """Always emits all six phases so absence is explicit, never inferred."""
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "total_wall_clock_s": self.total_wall_clock_s,
            "sum_phase_s": self.sum_phase_s,
            "unattributed_s": self.unattributed_s,
            "reconciliation_error": self.reconciliation_error,
            "phases": [r.to_dict() for r in self.records],
            "measured_count": len(self.measured_phases),
            "not_run": [p.value for p in self.not_run_phases],
            "failed": [r.phase.value for r in self.failed_phases],
            "profiling_errors": list(self.internal_errors),
        }

    def to_llm_summary(self, max_chars: int = 600) -> str:
        """Bounded scalar view for model context; full profile stays on disk.

        Every tier of the fallback chain emits complete JSON. The summary is never
        sliced by character count: a truncated JSON string is not a smaller summary,
        it is corrupt output. If no tier fits ``max_chars``, the call fails loudly
        instead of returning something a consumer cannot parse.
        """
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
            raise PhaseProfileError(
                f"max_chars must be a positive int, got {max_chars!r}."
            )

        for payload in self._summary_tiers():
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if len(text) <= max_chars:
                return text

        raise PhaseProfileError(
            f"Cannot render a summary within {max_chars} characters while staying valid "
            f"JSON; run_id alone is {len(self.run_id)} characters. Use to_dict() for the "
            "full profile or raise the limit."
        )

    def _summary_tiers(self) -> Iterator[Dict[str, Any]]:
        """Payloads from most to least detailed; each one is complete JSON.

        The tiers are not strictly monotonic in size: when no phase is ``NOT_RUN``,
        the shorter tiers carry a redundant empty list. That is harmless because the
        first fit wins -- if a tier fails to fit while a later one succeeds, the later
        one is necessarily shorter. What matters is that no tier is ever sliced.
        """
        measured = [(r.phase.value, r.duration_s) for r in self.records if r.is_measured]
        not_run = [r.phase.value for r in self.records if r.status is PhaseStatus.NOT_RUN]

        base: Dict[str, Any] = {
            "run_id": self.run_id,
            "wall_s": self.total_wall_clock_s,
            "unattributed_s": self.unattributed_s,
        }
        if self.reconciliation_error:
            base["reconciliation_error"] = self.reconciliation_error

        # 1. All six phases, discriminated by status.
        yield {
            **base,
            "phases": {
                r.phase.value: (r.duration_s if r.is_measured else "not_run")
                for r in self.records
            },
        }
        # 2. Measured durations plus an explicit list of what was skipped.
        yield {**base, "phases": dict(measured), "not_run": not_run}
        # 3. Counts only. ``not_run_count`` keeps absence visible without naming it.
        yield {
            **base,
            "phases": dict(measured),
            "not_run_count": len(not_run),
        }
