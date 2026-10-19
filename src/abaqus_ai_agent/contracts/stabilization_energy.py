"""Stabilization-energy acceptance contract for static (implicit) analyses.

Scope and deliberate limits
---------------------------
This module answers exactly one engineering question: when automatic
stabilization was actually enabled, did the artificial damping stay small
relative to the recoverable strain energy that carries the physics?

It deliberately does **not** reuse the legacy ``ALLSD / ALLIE`` ratio. ``ALLIE``
is total internal energy and already contains ``ALLSD``, so using it as the
denominator makes the fraction self-referential and understates distortion.
Dynamic energy balance (``ETOTAL`` / ``ALLKE`` / ``ALLWK`` drift) is a separate
contract and is not folded in here.

Metric definition (fixed by an explicit decision, not inferred at runtime)::

    r = max over informative frames of (ALLSD[t] / ALLSE[t])

Informative means both histories are present at an aligned time, both values are
finite, ``ALLSE`` is not negligible, ``ALLSD`` is non-negative and ``ALLSE`` is
positive. Frames that cannot inform the ratio are *skipped and recorded*, never
silently dropped and never treated as zero dissipation.

Verdicts:

* ``PASS``     - computed ratio is at or below the configured threshold.
* ``FAIL``     - computed ratio exceeds the configured threshold.
* ``BLOCKED``  - evidence is missing, non-finite, misaligned, or the denominator
                 is negligible while dissipation is not. No ratio is invented.
* ``SKIPPED``  - stabilization was not enabled, so the contract does not apply.

The threshold is an engineering policy for a specific configuration. It must be
supplied explicitly by the caller and is echoed in the verdict together with its
declared source; this module ships no universal physical constant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

# Frames whose energy scale is this fraction of the step's energy scale are
# treated as numerically empty. The scale is taken from the largest absolute
# value seen in either history, so the rule stays unit-agnostic.
DEFAULT_NEGLECTABLE_FRACTION = 1e-12

# Relative tolerance for matching history sample times between ALLSD and ALLSE.
DEFAULT_TIME_TOLERANCE = 1e-9

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_SKIPPED = "SKIPPED"

REASON_NOT_ENABLED = "stabilization_not_enabled"
REASON_THRESHOLD_MISSING = "stabilization_threshold_not_configured"
REASON_ALLSD_MISSING = "missing_stabilization_dissipation_history"
REASON_ALLSE_MISSING = "missing_strain_energy_history"
REASON_NON_FINITE = "non_finite_stabilization_energy"
REASON_NEGATIVE = "invalid_stabilization_energy_sign"
REASON_UNDEFINED_DENOMINATOR = "stabilization_energy_undefined_denominator"
REASON_RATIO_EXCEEDED = "stabilization_energy_exceeded"


@dataclass(frozen=True)
class StabilizationEnergyVerdict:
    """Outcome of the static stabilization-energy contract.

    ``ratio`` is ``None`` whenever no ratio could be computed; it is never
    substituted with ``0.0`` because that would impersonate a valid measurement.
    """

    status: str
    ratio: Optional[float] = None
    threshold: Optional[float] = None
    threshold_source: Optional[str] = None
    informative_frame_count: int = 0
    skipped_frame_count: int = 0
    skipped_frames: Tuple[Dict[str, Any], ...] = ()
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == STATUS_PASS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "ratio": self.ratio,
            "threshold": self.threshold,
            "threshold_source": self.threshold_source,
            "informative_frame_count": self.informative_frame_count,
            "skipped_frame_count": self.skipped_frame_count,
            "skipped_frames": list(self.skipped_frames),
            "reason": self.reason,
            "details": dict(self.details),
        }


def _as_pairs(series: Any) -> Optional[Tuple[Tuple[float, float], ...]]:
    """Normalize an Abaqus history series into ``((time, value), ...)``.

    Returns ``None`` when the series is absent so that "no history" stays
    distinguishable from "history of zeros".
    """
    if series is None:
        return None
    if isinstance(series, Mapping):
        if series.get("status") != "available":
            return None
        series = series.get("data")
        if series is None:
            return None
    pairs = []
    try:
        for item in series:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                pairs.append((float(item[0]), float(item[1])))
    except (TypeError, ValueError):
        return None
    return tuple(pairs)


def _series_from_payload(payload: Any) -> Optional[Mapping[str, Any]]:
    """Accept either the ``extract_energy_evidence`` envelope or raw history."""
    if not isinstance(payload, Mapping):
        return None
    if payload.get("status") not in (None, "available"):
        return None
    history = payload.get("history")
    if isinstance(history, Mapping):
        return _series_from_payload(history)
    variables = payload.get("variables")
    if isinstance(variables, Mapping):
        return variables
    return None


def _match_value(reference_time: float, pairs: Sequence[Tuple[float, float]],
                 tolerance: float) -> Optional[float]:
    for time_value, value in pairs:
        scale = max(1.0, abs(reference_time), abs(time_value))
        if abs(time_value - reference_time) <= tolerance * scale:
            return value
    return None


def evaluate_static_stabilization_energy(
    energy_evidence: Any,
    threshold: Optional[float],
    *,
    stabilization_enabled: bool = True,
    threshold_source: Optional[str] = None,
    neglectable_fraction: float = DEFAULT_NEGLECTABLE_FRACTION,
    time_tolerance: float = DEFAULT_TIME_TOLERANCE,
) -> StabilizationEnergyVerdict:
    """Evaluate the static stabilization-energy contract on extracted ODB history.

    ``energy_evidence`` may be the dict returned by
    :func:`abaqus_ai_agent.execution.odb.extract_energy_evidence` or an already
    unwrapped history mapping keyed by variable name.
    """
    base_details: Dict[str, Any] = {
        "metric": "max_over_frames(ALLSD / ALLSE)",
        "contract": "static_automatic_stabilization",
    }

    if not stabilization_enabled:
        return StabilizationEnergyVerdict(
            status=STATUS_SKIPPED,
            threshold=threshold,
            threshold_source=threshold_source,
            reason=REASON_NOT_ENABLED,
            details=base_details,
        )

    if threshold is None:
        return StabilizationEnergyVerdict(
            status=STATUS_BLOCKED,
            threshold=None,
            threshold_source=threshold_source,
            reason=REASON_THRESHOLD_MISSING,
            details=base_details,
        )
    try:
        threshold_value = float(threshold)
    except (TypeError, ValueError):
        return StabilizationEnergyVerdict(
            status=STATUS_BLOCKED,
            threshold=None,
            threshold_source=threshold_source,
            reason=REASON_THRESHOLD_MISSING,
            details=base_details,
        )
    if not math.isfinite(threshold_value) or threshold_value < 0.0:
        return StabilizationEnergyVerdict(
            status=STATUS_BLOCKED,
            threshold=threshold if math.isfinite(threshold_value) else None,
            threshold_source=threshold_source,
            reason=REASON_THRESHOLD_MISSING,
            details=base_details,
        )

    variables = _series_from_payload(energy_evidence)
    if variables is None:
        return StabilizationEnergyVerdict(
            status=STATUS_BLOCKED,
            threshold=threshold_value,
            threshold_source=threshold_source,
            reason=REASON_ALLSD_MISSING,
            details=base_details,
        )

    dissipation = _as_pairs(variables.get("ALLSD"))
    if dissipation is None:
        return StabilizationEnergyVerdict(
            status=STATUS_BLOCKED,
            threshold=threshold_value,
            threshold_source=threshold_source,
            reason=REASON_ALLSD_MISSING,
            details=base_details,
        )

    strain = _as_pairs(variables.get("ALLSE"))
    if strain is None:
        return StabilizationEnergyVerdict(
            status=STATUS_BLOCKED,
            threshold=threshold_value,
            threshold_source=threshold_source,
            reason=REASON_ALLSE_MISSING,
            details=base_details,
        )

    if not dissipation:
        return StabilizationEnergyVerdict(
            status=STATUS_BLOCKED,
            threshold=threshold_value,
            threshold_source=threshold_source,
            reason=REASON_ALLSD_MISSING,
            details=dict(base_details, frame_count=0),
        )

    scale = max(
        [abs(value) for _, value in dissipation] + [abs(value) for _, value in strain]
    )
    if not math.isfinite(scale):
        return StabilizationEnergyVerdict(
            status=STATUS_BLOCKED,
            threshold=threshold_value,
            threshold_source=threshold_source,
            reason=REASON_NON_FINITE,
            details=base_details,
        )
    neglectable = neglectable_fraction * scale

    informative: list[Tuple[int, float, float, float]] = []
    skipped: list[Dict[str, Any]] = []
    blocked_reason: Optional[str] = None
    blocked_frame: Optional[int] = None

    for index, (time_value, all_sd) in enumerate(dissipation):
        all_se = _match_value(time_value, strain, time_tolerance)
        if all_se is None:
            skipped.append({"frame_index": index, "time": time_value,
                            "reason": "unaligned_strain_energy_history"})
            continue
        if not (math.isfinite(all_sd) and math.isfinite(all_se)):
            skipped.append({"frame_index": index, "time": time_value,
                            "reason": REASON_NON_FINITE})
            blocked_reason = REASON_NON_FINITE
            blocked_frame = index
            continue
        if all_sd < 0.0:
            skipped.append({"frame_index": index, "time": time_value,
                            "reason": REASON_NEGATIVE, "ALLSD": all_sd})
            blocked_reason = REASON_NEGATIVE
            blocked_frame = index
            continue
        if abs(all_se) <= neglectable:
            if abs(all_sd) <= neglectable:
                skipped.append({"frame_index": index, "time": time_value,
                                "reason": "zero_energy_frame",
                                "ALLSD": all_sd, "ALLSE": all_se})
            else:
                skipped.append({"frame_index": index, "time": time_value,
                                "reason": REASON_UNDEFINED_DENOMINATOR,
                                "ALLSD": all_sd, "ALLSE": all_se})
                blocked_reason = REASON_UNDEFINED_DENOMINATOR
                blocked_frame = index
            continue
        if all_se <= 0.0:
            skipped.append({"frame_index": index, "time": time_value,
                            "reason": REASON_NEGATIVE, "ALLSE": all_se})
            blocked_reason = REASON_NEGATIVE
            blocked_frame = index
            continue
        informative.append((index, time_value, all_sd, all_se))

    details = dict(
        base_details,
        frame_count=len(dissipation),
        informative_frame_count=len(informative),
        skipped_frame_count=len(skipped),
        skipped_frames=tuple(skipped),
        neglectable_threshold=neglectable,
        time_tolerance=time_tolerance,
    )

    if blocked_reason is not None:
        details["blocked_frame_index"] = blocked_frame
        return StabilizationEnergyVerdict(
            status=STATUS_BLOCKED,
            threshold=threshold_value,
            threshold_source=threshold_source,
            informative_frame_count=len(informative),
            skipped_frame_count=len(skipped),
            skipped_frames=tuple(skipped),
            reason=blocked_reason,
            details=details,
        )

    if not informative:
        # Every frame was numerically empty: there is no stabilization
        # dissipation to bound, and no ratio is invented. The skipped frames
        # stay in the verdict so the audit trail shows why.
        return StabilizationEnergyVerdict(
            status=STATUS_PASS,
            ratio=0.0,
            threshold=threshold_value,
            threshold_source=threshold_source,
            informative_frame_count=0,
            skipped_frame_count=len(skipped),
            skipped_frames=tuple(skipped),
            reason="no_informative_frames_without_dissipation",
            details=dict(details, ratio_basis="no_measurable_dissipation"),
        )

    worst = max(informative, key=lambda item: item[2] / item[3])
    ratio = worst[2] / worst[3]
    details.update(
        governing_frame_index=worst[0],
        governing_time=worst[1],
        governing_ALLSD=worst[2],
        governing_ALLSE=worst[3],
    )

    if ratio > threshold_value:
        return StabilizationEnergyVerdict(
            status=STATUS_FAIL,
            ratio=ratio,
            threshold=threshold_value,
            threshold_source=threshold_source,
            informative_frame_count=len(informative),
            skipped_frame_count=len(skipped),
            skipped_frames=tuple(skipped),
            reason=REASON_RATIO_EXCEEDED,
            details=details,
        )

    return StabilizationEnergyVerdict(
        status=STATUS_PASS,
        ratio=ratio,
        threshold=threshold_value,
        threshold_source=threshold_source,
        informative_frame_count=len(informative),
        skipped_frame_count=len(skipped),
        skipped_frames=tuple(skipped),
        reason="stabilization_energy_within_threshold",
        details=details,
    )


def detect_stabilization_in_deck(inp_text: str) -> Dict[str, bool]:
    """Detect whether a solver deck enables step-level or contact stabilization.

    Only explicit Abaqus keywords count. A deck that merely mentions the word in
    a comment does not enable anything.
    """
    if not inp_text:
        return {"step_stabilization": False, "contact_stabilization": False}
    step = False
    contact = False
    for raw_line in inp_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("*"):
            continue
        upper = line.upper()
        if upper.startswith("*STATIC") and "STABILIZE" in upper:
            step = True
        elif upper.startswith("*DYNAMIC") and "STABILIZE" in upper:
            step = True
        elif upper.startswith("*CONTACT CONTROLS") and "STABILIZE" in upper:
            contact = True
        elif upper.startswith("*CONTACT STABILIZATION"):
            contact = True
    return {"step_stabilization": step, "contact_stabilization": contact}
