"""Time-to-gate telemetry for the pre-solve approval gate (Phase A).

The pre-solve approval gate stops a run before any submission and hands the
candidate to a human. Until now nothing recorded how long Phase A took, so the
cost of reaching the gate could not be compared against the solve itself.

Scope of this module: it *observes* elapsed time. It never decides whether a
run may proceed, never changes approval semantics, and never raises on behalf
of the run. A missing measurement is reported as ``None`` -- it is never
collapsed into ``0``, because zero would read as "reached the gate instantly".

Contract
--------
1. Durations come from ``time.monotonic()`` so wall-clock adjustments cannot
   produce a negative or inflated elapsed time; the wall-clock start is kept
   alongside for auditability.
2. ``stop()`` may be called at most once per outcome. Calling it again returns
   a fresh record for that outcome; it does not accumulate.
3. A timer that was never started yields ``elapsed_s = None`` rather than an
   exception: telemetry must not be able to fail the run it observes.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class GateTiming:
    """One time-to-gate measurement.

    ``elapsed_s`` is ``None`` when the timer was never started. ``outcome`` is
    the terminal label supplied by the caller (for example
    ``"AWAITING_APPROVAL"``); this module does not enumerate outcomes because
    it does not own the lifecycle.
    """

    outcome: str
    elapsed_s: Optional[float]
    started_at: Optional[str]
    stopped_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome,
            "elapsed_s": self.elapsed_s,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            # Stating the clock source matters when this record is compared
            # against solver logs, whose timestamps are wall-clock and can be
            # quantised to whole seconds.
            "clock": "monotonic",
        }


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class GateTimer:
    """Measure elapsed time from run start to a named terminal outcome."""

    def __init__(self) -> None:
        self._start_monotonic: Optional[float] = None
        self._started_at: Optional[str] = None

    @property
    def started(self) -> bool:
        return self._start_monotonic is not None

    def start(self) -> None:
        """Mark the beginning of Phase A. Restarting resets the measurement."""
        self._start_monotonic = time.monotonic()
        self._started_at = _utc_now_iso()

    def stop(self, outcome: str) -> GateTiming:
        """Return the measurement for ``outcome`` without raising."""
        stopped_at = _utc_now_iso()
        if self._start_monotonic is None:
            return GateTiming(
                outcome=outcome, elapsed_s=None,
                started_at=None, stopped_at=stopped_at,
            )
        elapsed = time.monotonic() - self._start_monotonic
        # A monotonic clock cannot go backwards, but clamp anyway so a
        # pathological platform value can never publish a negative duration.
        return GateTiming(
            outcome=outcome,
            elapsed_s=max(0.0, float(elapsed)),
            started_at=self._started_at,
            stopped_at=stopped_at,
        )
