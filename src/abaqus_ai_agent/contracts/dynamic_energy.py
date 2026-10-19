"""Dynamic energy balance acceptance contract for transient dynamic analyses.

Scope and deliberate limits
---------------------------
This module answers exactly one engineering question: over a transient dynamic
history, is the solver's own total-energy residual small compared with the energy
scale the analysis actually dissipated or stored?

It is an **independent sibling** of ``stabilization_energy``, not a variant of it.
The static contract bounds artificial damping (``ALLSD / ALLSE``) inside a static
step; it says nothing about whether a transient integration conserved energy, and
sharing a threshold between the two would assert a relationship the evidence does
not support.

Metric definition (fixed by an explicit decision, not inferred at runtime)::

    E_ref = max over frames of max(|ALLIE|, |ALLKE|, |ALLWK|)
    r     = max over frames of (|ETOTAL[t]| / E_ref)

``ETOTAL`` is the solver's own balance residual, so its absolute value is the
meaningful quantity and its zero is physical. A range metric such as
``max(ETOTAL) - min(ETOTAL)`` can be small while a large residual stays nearly
constant, which would misreport a persistent imbalance as conservation.

``E_ref`` takes the largest of internal, kinetic and external-work energy rather
than one of them alone. A frame that happens to be quiet in kinetic energy cannot
then shrink the denominator and manufacture a failure, and the reference is a
property of the whole analysed event instead of a single sample.

Identity check
--------------
Abaqus defines ``ETOTAL = ALLIE + ALLKE - ALLWK``. The contract verifies that
identity on the extracted histories with a relative tolerance and blocks when it
fails, instead of trusting a single number whose provenance is unverified. This is
what catches unit mismatches, mixed-up history regions, or histories drawn from
different analysis steps.

Solver products
---------------
Implicit and explicit integration do not dissipate or accumulate energy the same
way, so the same numeric threshold must not be applied to both by default. The
caller must name the solver product; the verdict echoes it with the threshold so a
reader can see which policy was applied. This module ships no universal threshold.

Verdicts
--------
``PASS``       computed ratio is at or below the configured threshold.
``FAIL``       computed ratio exceeds the configured threshold.
``BLOCKED``    evidence is absent, non-finite, misaligned in time, violates the
               ETOTAL identity, or every energy component is exactly zero so no
               reference scale exists. No ratio is invented.
``INCOMPLETE`` evidence is present and consistent but fewer than two frames carry
               a measurable residual, so it cannot evidence a drift trend. This is
               deliberately distinct from ``BLOCKED``: something was measured.
``SKIPPED``    the analysis is not dynamic, so the contract does not apply.

Frames whose residual is below ``neglectable_fraction * E_ref`` (in practice
``t = 0``) are consistent but carry no drift information. They are counted in
``frame_count`` and never in ``informative_frame_count``, because two empty
frames agreeing with each other is not a conservation measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

# Frames whose energy scale is this fraction of the global reference are treated
# as numerically empty. Unit-agnostic because it is relative to E_ref.
DEFAULT_NEGLECTABLE_FRACTION = 1e-12

# Relative tolerance for matching history sample times across ETOTAL and the
# energy components.
DEFAULT_TIME_TOLERANCE = 1e-9

# Relative tolerance for the ETOTAL = ALLIE + ALLKE - ALLWK identity. Real Abaqus
# output is single precision, so the observed deviation in the validated implicit
# dynamic case is ~2.4e-8; 1e-3 leaves room for that rounding while still
# catching a genuinely wrong history set.
DEFAULT_IDENTITY_TOLERANCE = 1e-3

# Number of informative frames required before a drift trend is claimed.
MINIMUM_INFORMATIVE_FRAMES = 2

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_SKIPPED = "SKIPPED"

REASON_NOT_DYNAMIC = "analysis_not_dynamic"
REASON_THRESHOLD_MISSING = "dynamic_energy_threshold_not_configured"
REASON_SOLVER_PRODUCT_MISSING = "dynamic_energy_solver_product_not_declared"
REASON_ETOTAL_MISSING = "missing_total_energy_history"
REASON_COMPONENT_MISSING = "missing_energy_component_history"
REASON_NON_FINITE = "non_finite_total_energy"
REASON_UNALIGNED = "unaligned_total_energy_history"
REASON_IDENTITY_VIOLATED = "total_energy_identity_violated"
REASON_ZERO_REFERENCE = "dynamic_energy_zero_reference"
REASON_RATIO_EXCEEDED = "dynamic_energy_drift_exceeded"
REASON_TOO_FEW_FRAMES = "insufficient_informative_frames"
REASON_NO_MEASURABLE_ENERGY = "no_measurable_energy_in_history"
REASON_NO_MEASURABLE_ENERGY = "no_measurable_energy_in_history"

SOLVER_PRODUCTS = ("standard", "explicit")


@dataclass(frozen=True)
class DynamicEnergyVerdict:
    """Outcome of the dynamic energy balance contract.

    ``ratio`` is ``None`` whenever no ratio could be computed; it is never
    substituted with ``0.0`` because that would impersonate a valid measurement.
    """

    status: str
    ratio: Optional[float] = None
    threshold: Optional[float] = None
    threshold_source: Optional[str] = None
    solver_product: Optional[str] = None
    reference_energy: Optional[float] = None
    frame_count: int = 0
    informative_frame_count: int = 0
    max_identity_deviation: Optional[float] = None
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
            "solver_product": self.solver_product,
            "reference_energy": self.reference_energy,
            "frame_count": self.frame_count,
            "informative_frame_count": self.informative_frame_count,
            "max_identity_deviation": self.max_identity_deviation,
            "reason": self.reason,
            "details": dict(self.details),
        }


def _as_pairs(series: Any) -> Optional[Tuple[Tuple[float, float], ...]]:
    """Normalize a history series into ``((time, value), ...)``.

    Returns ``None`` when the series is absent so "no history" stays
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
    """Accept the ``extract_energy_evidence`` envelope or a raw history mapping."""
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


def _match_value(
    reference_time: float,
    pairs: Sequence[Tuple[float, float]],
    tolerance: float,
) -> Optional[float]:
    for time_value, value in pairs:
        scale = max(1.0, abs(reference_time), abs(time_value))
        if abs(time_value - reference_time) <= tolerance * scale:
            return value
    return None


def _positive_threshold(
    threshold: Optional[float], threshold_source: Optional[str]
) -> Optional[float]:
    if threshold is None:
        return None
    try:
        value = float(threshold)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0.0:
        return None
    return value


def evaluate_dynamic_energy_balance(
    energy_evidence: Any,
    threshold: Optional[float],
    *,
    solver_product: Optional[str],
    analysis_is_dynamic: bool = True,
    threshold_source: Optional[str] = None,
    neglectable_fraction: float = DEFAULT_NEGLECTABLE_FRACTION,
    time_tolerance: float = DEFAULT_TIME_TOLERANCE,
    identity_tolerance: float = DEFAULT_IDENTITY_TOLERANCE,
    minimum_frames: int = MINIMUM_INFORMATIVE_FRAMES,
) -> DynamicEnergyVerdict:
    """Evaluate the dynamic energy balance contract on extracted ODB history.

    ``energy_evidence`` may be the dict returned by
    :func:`abaqus_ai_agent.execution.odb.extract_energy_evidence` or an already
    unwrapped history mapping keyed by variable name. ``ALLIE``, ``ALLKE``,
    ``ALLWK`` and ``ETOTAL`` are all required: the balance uses ``ETOTAL`` and the
    identity check uses the other three.
    """
    product = (solver_product or "").strip().lower() or None
    base_details: Dict[str, Any] = {
        "metric": "max_over_frames(|ETOTAL| / E_ref)",
        "reference": "max_over_frames(max(|ALLIE|, |ALLKE|, |ALLWK|))",
        "identity": "ETOTAL = ALLIE + ALLKE - ALLWK",
        "contract": "dynamic_energy_balance",
    }

    def verdict(status: str, *, reason: str, **kwargs: Any) -> DynamicEnergyVerdict:
        return DynamicEnergyVerdict(
            status=status,
            solver_product=product,
            threshold_source=threshold_source,
            reason=reason,
            details=dict(base_details, **kwargs.pop("extra", {})),
            **kwargs,
        )

    if not analysis_is_dynamic:
        return verdict(STATUS_SKIPPED, reason=REASON_NOT_DYNAMIC)

    if product not in SOLVER_PRODUCTS:
        return verdict(STATUS_BLOCKED, reason=REASON_SOLVER_PRODUCT_MISSING)

    threshold_value = _positive_threshold(threshold, threshold_source)
    if threshold_value is None:
        return verdict(STATUS_BLOCKED, reason=REASON_THRESHOLD_MISSING)

    variables = _series_from_payload(energy_evidence)
    if variables is None:
        return verdict(STATUS_BLOCKED, reason=REASON_ETOTAL_MISSING, threshold=threshold_value)

    total = _as_pairs(variables.get("ETOTAL"))
    if total is None or not total:
        return verdict(STATUS_BLOCKED, reason=REASON_ETOTAL_MISSING, threshold=threshold_value)

    components: Dict[str, Tuple[Tuple[float, float], ...]] = {}
    for name in ("ALLIE", "ALLKE", "ALLWK"):
        series = _as_pairs(variables.get(name))
        if series is None or not series:
            return verdict(
                STATUS_BLOCKED,
                reason="%s:%s" % (REASON_COMPONENT_MISSING, name),
                threshold=threshold_value,
                extra={"missing_component": name},
            )
        components[name] = series

    # The reference scale belongs to the whole event, so it is computed before
    # any per-frame judgement and from the three energy components only.
    # ETOTAL is deliberately excluded: it is the residual being judged, and a
    # large imbalance must not inflate the denominator that measures it.
    scale_values = []
    for series in components.values():
        scale_values.extend(abs(value) for _, value in series)
    if not all(math.isfinite(value) for value in scale_values):
        return verdict(STATUS_BLOCKED, reason=REASON_NON_FINITE, threshold=threshold_value)

    reference = max(scale_values) if scale_values else 0.0
    if reference <= 0.0:
        # Every component is exactly zero across the whole step. If the solver still
        # reports a nonzero residual, there is no scale against which to judge it and
        # no ratio may be invented. A history where both sides are zero is empty:
        # it is consistent, but it measures nothing, so it stays INCOMPLETE rather
        # than being narrated as conservation.
        if all(value == 0.0 for _, value in total):
            return verdict(
                STATUS_INCOMPLETE,
                reason=REASON_NO_MEASURABLE_ENERGY,
                threshold=threshold_value,
                reference_energy=0.0,
                frame_count=len(total),
                informative_frame_count=0,
                extra={"ratio_basis": "no_measurable_energy"},
            )
        return verdict(
            STATUS_BLOCKED,
            reason=REASON_ZERO_REFERENCE,
            threshold=threshold_value,
            reference_energy=0.0,
            frame_count=len(total),
            extra={"zero_reference": True},
        )
    neglectable = neglectable_fraction * reference

    # The identity tolerance is relative to the energy scale of the frame being
    # checked, never to an absolute floor. A floor expressed in the model's unit
    # system would differ in meaning between a 1 J model and a 1e6 J model: with
    # a floor of 1.0, a 1e-3 tolerance silently permits a 1e3 absolute error.
    # Zero-energy frames need no tolerance because their identity deviation is 0.
    max_identity_deviation = 0.0
    max_identity_limit = 0.0

    informative: list[Tuple[int, float, float, float]] = []
    empty_frames: list[int] = []
    blocked_reason: Optional[str] = None
    blocked_frame: Optional[int] = None

    for index, (time_value, etotal) in enumerate(total):
        if not math.isfinite(time_value) or not math.isfinite(etotal):
            blocked_reason = REASON_NON_FINITE
            blocked_frame = index
            break

        matched: Dict[str, float] = {}
        for name, series in components.items():
            value = _match_value(time_value, series, time_tolerance)
            if value is None:
                blocked_reason = REASON_UNALIGNED
                blocked_frame = index
                break
            if not math.isfinite(value):
                blocked_reason = REASON_NON_FINITE
                blocked_frame = index
                break
            matched[name] = value
        if blocked_reason is not None:
            break

        expected = matched["ALLIE"] + matched["ALLKE"] - matched["ALLWK"]
        deviation = abs(etotal - expected)
        frame_scale = max(abs(etotal), abs(matched["ALLIE"]),
                          abs(matched["ALLKE"]), abs(matched["ALLWK"]))
        identity_limit = identity_tolerance * frame_scale
        max_identity_deviation = max(max_identity_deviation, deviation)
        max_identity_limit = max(max_identity_limit, identity_limit)
        if deviation > identity_limit:
            blocked_reason = REASON_IDENTITY_VIOLATED
            blocked_frame = index
            break

        residual = abs(etotal)
        if residual <= neglectable:
            # Empty frame (in practice t=0). It is consistent and harmless, but it
            # carries no drift information, so it must not count towards the
            # informative-frame floor and must not raise the ratio.
            empty_frames.append(index)
        else:
            informative.append((index, time_value, residual, residual / reference))

    details_extra = {
        "reference_energy": reference,
        "neglectable_threshold": neglectable,
        "max_identity_limit": max_identity_limit,
        "identity_tolerance": identity_tolerance,
        "time_tolerance": time_tolerance,
        "frame_count": len(total),
        "informative_frame_count": len(informative),
        "empty_frame_count": len(empty_frames),
        "empty_frame_indices": tuple(empty_frames),
    }

    if blocked_reason is not None:
        return verdict(
            STATUS_BLOCKED,
            reason=blocked_reason,
            threshold=threshold_value,
            reference_energy=reference,
            frame_count=len(total),
            informative_frame_count=len(informative),
            max_identity_deviation=max_identity_deviation,
            extra=dict(details_extra, blocked_frame_index=blocked_frame),
        )

    if len(informative) < minimum_frames:
        return verdict(
            STATUS_INCOMPLETE,
            reason=REASON_TOO_FEW_FRAMES,
            threshold=threshold_value,
            reference_energy=reference,
            frame_count=len(total),
            informative_frame_count=len(informative),
            max_identity_deviation=max_identity_deviation,
            extra=dict(details_extra, minimum_informative_frames=minimum_frames),
        )

    worst = max(informative, key=lambda item: item[3])
    ratio = worst[3]
    details_extra.update(
        governing_frame_index=worst[0],
        governing_time=worst[1],
        governing_residual=worst[2],
    )

    if ratio > threshold_value:
        return verdict(
            STATUS_FAIL,
            reason=REASON_RATIO_EXCEEDED,
            threshold=threshold_value,
            reference_energy=reference,
            frame_count=len(total),
            informative_frame_count=len(informative),
            max_identity_deviation=max_identity_deviation,
            ratio=ratio,
            extra=details_extra,
        )

    # Every informative frame sits above the neglectable band, so a PASS means the
    # residual was measurably small relative to a real event -- not that the event
    # was empty.
    return verdict(
        STATUS_PASS,
        reason="dynamic_energy_balance_within_threshold",
        threshold=threshold_value,
        reference_energy=reference,
        frame_count=len(total),
        informative_frame_count=len(informative),
        max_identity_deviation=max_identity_deviation,
        ratio=ratio,
        extra=details_extra,
    )
