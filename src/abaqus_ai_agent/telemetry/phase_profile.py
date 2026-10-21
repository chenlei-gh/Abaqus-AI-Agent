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

    def __init__(self, run_id: str = "") -> None:
        self.run_id = run_id
        self._measured: Dict[PipelinePhase, PhaseRecord] = {}
        self._active: Optional[PipelinePhase] = None
        # The wall clock starts at construction, not at the first phase. Otherwise
        # work done before the first measurement would vanish from the total and
        # ``unattributed_s`` would understate the real overhead.
        self._started_monotonic: float = time.monotonic()
        self._finalized = False

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
        """Time one phase. Exceptions propagate unchanged after being recorded."""
        if self._finalized:
            raise PhaseProfileError("Cannot measure a phase after finalize().")
        if self._active is not None:
            raise PhaseProfileError(
                f"Phase {phase.value} entered while {self._active.value} is still active. "
                "Phases must not overlap; concurrent phases make the breakdown sum "
                "meaningless."
            )

        self._active = phase
        started = self._now()
        started_utc = _utc_now_iso()
        try:
            yield
        except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised verbatim
            finished = time.monotonic()
            self._store(PhaseRecord(
                phase=phase,
                status=PhaseStatus.FAILED,
                duration_s=round(finished - started, 6),
                started_at_utc=started_utc,
                finished_at_utc=_utc_now_iso(),
                exception_type=type(exc).__name__,
                exception_message=str(exc),
                detail=dict(detail),
            ))
            raise
        else:
            finished = time.monotonic()
            self._store(PhaseRecord(
                phase=phase,
                status=PhaseStatus.MEASURED,
                duration_s=round(finished - started, 6),
                started_at_utc=started_utc,
                finished_at_utc=_utc_now_iso(),
                detail=dict(detail),
            ))
        finally:
            self._active = None

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
            raise PhaseProfileError("Cannot record a phase after finalize().")
        if self._active is not None:
            raise PhaseProfileError(
                f"Cannot record {phase.value} while {self._active.value} is active."
            )
        if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)):
            raise PhaseProfileError(
                f"duration_s must be a number, got {type(duration_s).__name__}."
            )
        if duration_s < 0:
            raise PhaseProfileError(f"duration_s must be non-negative, got {duration_s}.")
        record = PhaseRecord(
            phase=phase,
            status=PhaseStatus.MEASURED,
            duration_s=round(float(duration_s), 6),
            started_at_utc="",
            finished_at_utc="",
            detail=dict(detail),
        )
        return self._store(record)

    def mark_not_run(self, phase: PipelinePhase, reason: str = "") -> PhaseRecord:
        """Record that a phase was deliberately skipped, without inventing a 0.0."""
        if self._finalized:
            raise PhaseProfileError("Cannot mark a phase after finalize().")
        if phase in self._measured and self._measured[phase].is_measured:
            raise PhaseProfileError(
                f"Phase {phase.value} already has a measurement; refusing to overwrite "
                "it with NOT_RUN."
            )
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
            raise PhaseProfileError("finalize() already called.")
        if self._active is not None:
            raise PhaseProfileError(
                f"Cannot finalize while {self._active.value} is still active."
            )
        self._finalized = True

        total_wall = time.monotonic() - self._started_monotonic

        return PhaseProfile(
            run_id=self.run_id,
            records=tuple(
                self._measured.get(p) or PhaseRecord(phase=p, status=PhaseStatus.NOT_RUN)
                for p in sorted(PipelinePhase, key=lambda p: p.order)
            ),
            total_wall_clock_s=round(total_wall, 6),
        )


@dataclass(frozen=True)
class PhaseProfile:
    """Immutable, reconciled view of a run's phase timings."""

    run_id: str
    records: Tuple[PhaseRecord, ...]
    total_wall_clock_s: float
    schema: str = "phase_profile_v1"

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
        }

    def to_llm_summary(self, max_chars: int = 600) -> str:
        """Bounded scalar view for model context; full profile stays on disk."""
        import json

        payload = {
            "run_id": self.run_id,
            "wall_s": self.total_wall_clock_s,
            "unattributed_s": self.unattributed_s,
            "phases": {
                r.phase.value: (
                    r.duration_s if r.is_measured else "not_run"
                )
                for r in self.records
            },
        }
        if self.reconciliation_error:
            payload["reconciliation_error"] = self.reconciliation_error
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return text if len(text) < max_chars else text[: max_chars - 4] + "..."
