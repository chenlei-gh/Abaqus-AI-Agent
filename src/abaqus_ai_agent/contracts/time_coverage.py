"""Traceable time-coverage evidence for an analysis report (T-P7).

The contract deliberately separates the *target* duration declared by the step
contract from the *reached* duration measured in solver-authored artifacts. A
solve can complete normally while the ODB stops before the requested end time;
such a run must never be described as a complete process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, Optional, Tuple


class TimeCoverageStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _fmt(value: Optional[float]) -> str:
    if value is None:
        return "unavailable"
    return f"{float(value):.6g}"


def _same_time(left: float, right: float) -> bool:
    """Treat only floating-point noise as agreement, not a material gap."""
    tolerance = max(1e-9, 1e-6 * max(abs(left), abs(right), 1.0))
    return abs(float(left) - float(right)) <= tolerance


@dataclass(frozen=True)
class TimeCoverage:
    """A reportable verdict about whether the solved interval reached its target."""

    status: TimeCoverageStatus
    target_time: Optional[float] = None
    reached_time: Optional[float] = None
    unit: str = "model time unit"
    target_source: str = "unavailable"
    reached_source: str = "unavailable"
    odb_time: Optional[float] = None
    sta_time: Optional[float] = None
    odb_source: str = "unavailable"
    sta_source: str = "unavailable"
    reasons: Tuple[str, ...] = field(default_factory=tuple)
    start_time: Optional[float] = None
    start_source: str = "unavailable"

    @property
    def unit_label(self) -> str:
        return self.unit or "model time unit"

    def ratio(self) -> Optional[float]:
        """Return reached/target only when the evidence supports a ratio.

        Missing or conflicting evidence must not be converted into a plausible
        percentage. That is the core disclosure rule for this contract.
        """
        if self.status not in (TimeCoverageStatus.COMPLETE, TimeCoverageStatus.PARTIAL):
            return None
        if not _is_finite_number(self.target_time) or float(self.target_time) <= 0:
            return None
        if not _is_finite_number(self.reached_time) or float(self.reached_time) < 0:
            return None
        return float(self.reached_time) / float(self.target_time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "target_time": self.target_time,
            "reached_time": self.reached_time,
            "start_time": self.start_time,
            "ratio": self.ratio(),
            "unit": self.unit_label,
            "target_source": self.target_source,
            "reached_source": self.reached_source,
            "start_source": self.start_source,
            "odb_time": self.odb_time,
            "sta_time": self.sta_time,
            "odb_source": self.odb_source,
            "sta_source": self.sta_source,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["TimeCoverage"]:
        if not isinstance(data, dict):
            return None
        try:
            status = TimeCoverageStatus(str(data.get("status", "UNKNOWN")).upper())
        except ValueError:
            status = TimeCoverageStatus.UNKNOWN

        def _number(key):
            value = data.get(key)
            return float(value) if _is_finite_number(value) else None

        return cls(
            status=status,
            target_time=_number("target_time"),
            reached_time=_number("reached_time"),
            start_time=_number("start_time"),
            unit=str(data.get("unit") or "model time unit"),
            target_source=str(data.get("target_source") or "unavailable"),
            reached_source=str(data.get("reached_source") or "unavailable"),
            start_source=str(data.get("start_source") or "unavailable"),
            odb_time=_number("odb_time"),
            sta_time=_number("sta_time"),
            odb_source=str(data.get("odb_source") or "unavailable"),
            sta_source=str(data.get("sta_source") or "unavailable"),
            reasons=tuple(str(reason) for reason in (data.get("reasons") or ())),
        )

    def evidence_statement(self) -> str:
        """Compact source-bound statement suitable for diagnostics and metadata."""
        return (
            f"{self.status.value}: target={_fmt(self.target_time)} {self.unit_label} "
            f"({self.target_source}); reached={_fmt(self.reached_time)} {self.unit_label} "
            f"({self.reached_source}); start={_fmt(self.start_time)} "
            f"({self.start_source}); odb={_fmt(self.odb_time)}; sta={_fmt(self.sta_time)}"
        )

    def limitation_statement(self) -> Optional[str]:
        """Return a mandatory report limitation, or None for proven completion."""
        if self.status is TimeCoverageStatus.COMPLETE:
            return None
        if self.status is TimeCoverageStatus.PARTIAL:
            ratio = self.ratio()
            pct = f"{ratio * 100.0:.1f}%" if ratio is not None else "unavailable"
            interval_note = ""
            if self.start_time is not None:
                interval_note = (
                    f" The recorded interval starts at {_fmt(self.start_time)} "
                    f"{self.unit_label} according to {self.start_source}."
                )
            return (
                "Time-coverage limitation: the solver reached "
                f"{_fmt(self.reached_time)} of the {_fmt(self.target_time)} target "
                f"{self.unit_label} ({pct}) according to {self.reached_source}. "
                f"The reported result covers only that interval.{interval_note} "
                "It must not be described as the complete target-duration process."
            )
        if self.status is TimeCoverageStatus.CONFLICT:
            return (
                "Time-coverage limitation: ODB and .sta evidence disagree "
                f"(ODB={_fmt(self.odb_time)} {self.unit_label} via {self.odb_source}; "
                f".sta={_fmt(self.sta_time)} {self.unit_label} via {self.sta_source}). "
                "The covered interval is unresolved and no coverage ratio is claimed."
            )
        reasons = ", ".join(self.reasons) if self.reasons else "insufficient evidence"
        return (
            "Time-coverage limitation: the covered interval could not be established "
            f"({reasons}). Completeness of the target-duration process is not claimed."
        )

    def animation_caption(self, is_zh: bool = False) -> str:
        """Caption text bound to the same evidence as the report limitation."""
        if self.status is TimeCoverageStatus.COMPLETE:
            if self.start_time is not None:
                en = (
                    "Time coverage: complete target duration "
                    f"({_fmt(self.start_time)} to {_fmt(self.target_time)} {self.unit_label})."
                )
                zh = (
                    "时间覆盖：完整覆盖目标时长"
                    f"（{_fmt(self.start_time)} 至 {_fmt(self.target_time)} {self.unit_label}）。"
                )
            else:
                en = (
                    "Time coverage: complete target duration "
                    f"(ends at {_fmt(self.target_time)} {self.unit_label})."
                )
                zh = (
                    "时间覆盖：完整覆盖目标时长"
                    f"（截至 {_fmt(self.target_time)} {self.unit_label}）。"
                )
        elif self.status is TimeCoverageStatus.PARTIAL:
            ratio = self.ratio()
            pct = f"{ratio * 100.0:.1f}%" if ratio is not None else "不可用"
            if self.start_time is not None:
                range_en = f"{_fmt(self.start_time)} to {_fmt(self.reached_time)}"
                range_zh = f"{_fmt(self.start_time)} 至 {_fmt(self.reached_time)}"
            else:
                range_en = f"reached {_fmt(self.reached_time)}"
                range_zh = f"已达 {_fmt(self.reached_time)}"
            en = (
                f"Time coverage: {range_en} of {_fmt(self.target_time)} "
                f"{self.unit_label} ({pct}). "
                "The animation does not show the full target duration."
            )
            zh = (
                f"时间覆盖：{range_zh} / 目标 {_fmt(self.target_time)} "
                f"{self.unit_label}（{pct}）；动画未覆盖完整目标时长。"
            )
        elif self.status is TimeCoverageStatus.CONFLICT:
            en = (
                "Time coverage unresolved: ODB and .sta disagree "
                f"(ODB {_fmt(self.odb_time)}; .sta {_fmt(self.sta_time)} "
                f"{self.unit_label}). Completeness is not claimed."
            )
            zh = (
                "时间覆盖未解决：ODB 与 .sta 证据冲突"
                f"（ODB {_fmt(self.odb_time)}；.sta {_fmt(self.sta_time)} "
                f"{self.unit_label}）。不宣称过程完整。"
            )
        else:
            reason_en = ", ".join(self.reasons) if self.reasons else "insufficient evidence"
            reason_zh = "、".join(self.reasons) if self.reasons else "证据不足"
            en = f"Time coverage unavailable ({reason_en}); completeness is not claimed."
            zh = f"时间覆盖不可用（{reason_zh}）；不宣称过程完整。"
        return f"{zh} / {en}" if is_zh else en

def build_time_coverage(
    *,
    target_time: Optional[float],
    target_source: str = "unavailable",
    odb_time: Optional[float] = None,
    odb_source: str = "unavailable",
    sta_time: Optional[float] = None,
    sta_source: str = "unavailable",
    sta_ambiguous: bool = False,
    unit: str = "model time unit",
    start_time: Optional[float] = None,
    start_source: str = "unavailable",
) -> TimeCoverage:
    """Classify target/reached time without inventing missing evidence.

    ODB frame time is the primary evidence. .sta is a controlled fallback only
    when the ODB value is unavailable, and it must agree with the ODB when both
    exist. A frame count is never used as a proxy for elapsed time.
    """
    reasons = []
    target_ok = _is_finite_number(target_time) and float(target_time) > 0
    if not target_ok:
        reasons.append("target_time_unavailable")

    start_ok = _is_finite_number(start_time) and float(start_time) >= 0
    if not start_ok:
        reasons.append("start_time_unavailable")
    odb_ok = _is_finite_number(odb_time) and float(odb_time) >= 0
    sta_ok = _is_finite_number(sta_time) and float(sta_time) >= 0
    if sta_ambiguous:
        reasons.append("sta_time_ambiguous")
        sta_ok = False
    if not odb_ok:
        reasons.append("odb_time_unavailable")
    if not sta_ok:
        reasons.append("sta_time_unavailable")

    if not target_ok:
        return TimeCoverage(
            status=TimeCoverageStatus.UNKNOWN,
            target_time=None,
            reached_time=None,
            unit=unit,
            target_source=target_source or "unavailable",
            reached_source="unavailable",
            start_time=float(start_time) if start_ok else None,
            start_source=start_source or "unavailable",
            odb_time=float(odb_time) if odb_ok else None,
            sta_time=float(sta_time) if sta_ok else None,
            odb_source=odb_source or "unavailable",
            sta_source=sta_source or "unavailable",
            reasons=tuple(dict.fromkeys(reasons)),
        )

    target = float(target_time)
    odb_value = float(odb_time) if odb_ok else None
    sta_value = float(sta_time) if sta_ok else None

    if odb_value is not None and sta_value is not None and not _same_time(odb_value, sta_value):
        return TimeCoverage(
            status=TimeCoverageStatus.CONFLICT,
            target_time=target,
            reached_time=None,
            unit=unit,
            target_source=target_source or "unavailable",
            reached_source="conflict",
            start_time=float(start_time) if start_ok else None,
            start_source=start_source or "unavailable",
            odb_time=odb_value,
            sta_time=sta_value,
            odb_source=odb_source or "unavailable",
            sta_source=sta_source or "unavailable",
            reasons=tuple(dict.fromkeys(reasons + ["odb_sta_time_conflict"])),
        )

    if odb_value is not None:
        reached, reached_source = odb_value, odb_source or "odb"
    elif sta_value is not None:
        reached, reached_source = sta_value, sta_source or ".sta"
    else:
        return TimeCoverage(
            status=TimeCoverageStatus.UNKNOWN,
            target_time=target,
            reached_time=None,
            unit=unit,
            target_source=target_source or "unavailable",
            reached_source="unavailable",
            start_time=float(start_time) if start_ok else None,
            start_source=start_source or "unavailable",
            odb_time=None,
            sta_time=None,
            odb_source=odb_source or "unavailable",
            sta_source=sta_source or "unavailable",
            reasons=tuple(dict.fromkeys(reasons)),
        )

    tolerance = max(1e-9, 1e-6 * max(abs(target), abs(reached), 1.0))
    start_value = float(start_time) if start_ok else None
    if start_value is not None and start_value > reached + tolerance:
        start_value = None
        reasons.append("start_time_exceeds_reached")
    status = (
        TimeCoverageStatus.COMPLETE
        if reached >= target - tolerance
        else TimeCoverageStatus.PARTIAL
    )
    return TimeCoverage(
        status=status,
        target_time=target,
        reached_time=reached,
        unit=unit,
        target_source=target_source or "unavailable",
        reached_source=reached_source,
        odb_time=odb_value,
        sta_time=sta_value,
        odb_source=odb_source or "unavailable",
        sta_source=sta_source or "unavailable",
        reasons=tuple(dict.fromkeys(reasons)),
        start_time=start_value,
        start_source=start_source or "unavailable",
    )
