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

A frame whose ``ALLSD`` time has no aligned ``ALLSE`` sample is not merely
skipped: the histories disagree about the step's timeline, so the remaining
frames cannot be trusted to bound the ratio on their own. Misalignment therefore
blocks the verdict instead of letting the aligned subset decide it.

Verdicts:

* ``PASS``     - computed ratio is at or below the configured threshold.
* ``FAIL``     - computed ratio exceeds the configured threshold.
* ``BLOCKED``  - evidence is missing, non-finite, misaligned, or the denominator
                 is negligible while dissipation is not. No ratio is invented.
* ``SKIPPED``  - stabilization was not enabled, so the contract does not apply.

The threshold is an engineering policy for a specific configuration. It must be
supplied explicitly by the caller and is echoed in the verdict together with its
declared source; this module ships no universal physical constant.

Step binding
------------
A multi-step deck may enable stabilization in one step only. Energies from a
different step are not evidence for that repair, so :func:`resolve_stabilized_step`
maps the deck keywords onto the ODB step list and returns ``UNRESOLVED`` whenever
the mapping is not unique (several stabilized steps, keywords outside any step
block, or a stabilized step absent from the ODB). ``INCLUDE`` files are not
expanded here; the deck handed to this module is expected to be the flattened
deck that was actually solved.
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
REASON_UNALIGNED_HISTORY = "unaligned_strain_energy_history"

# Stabilized-step resolution outcomes.
SELECTION_RESOLVED = "RESOLVED"
SELECTION_NOT_ENABLED = "NOT_ENABLED"
SELECTION_UNRESOLVED = "UNRESOLVED"

REASON_STABILIZATION_STEP_UNATTRIBUTED = "stabilization_step_unattributed"
REASON_STABILIZATION_STEP_AMBIGUOUS = "stabilization_step_ambiguous"
REASON_STABILIZED_STEP_MISSING_IN_ODB = "stabilized_step_missing_in_odb"


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
            # The two histories disagree about the step timeline. Skipping the
            # frame and letting the aligned subset decide would turn a broken
            # evidence pair into a PASS, so this blocks the verdict.
            skipped.append({"frame_index": index, "time": time_value,
                            "reason": REASON_UNALIGNED_HISTORY})
            if blocked_reason is None:
                blocked_reason = REASON_UNALIGNED_HISTORY
                blocked_frame = index
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


def _iter_deck_keywords(inp_text: str):
    """Yield keyword lines, dropping comments, data lines and blank lines."""
    for raw_line in (inp_text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("**") or not line.startswith("*"):
            continue
        yield line


def _normalize_token(value: str) -> str:
    return " ".join(str(value).upper().split())


def _parse_deck_keyword(line: str) -> Tuple[str, Dict[str, str], frozenset]:
    """Split ``*Keyword, p=1, FLAG`` into (name, parameters, flags)."""
    tokens = [token.strip() for token in line[1:].split(",")]
    name = _normalize_token(tokens[0]) if tokens else ""
    parameters: Dict[str, str] = {}
    flags = set()
    for token in tokens[1:]:
        if not token:
            continue
        if "=" in token:
            key, _, value = token.partition("=")
            parameters[_normalize_token(key)] = value.strip().strip('"').strip("'")
        else:
            flags.add(_normalize_token(token))
    return name, parameters, frozenset(flags)


def _classify_stabilization(name: str, parameters: Mapping[str, str],
                            flags: Iterable[str]) -> Tuple[bool, bool]:
    """Return (step_level, contact_level) for one keyword card."""
    has_stabilize = "STABILIZE" in flags or "STABILIZE" in parameters
    is_step_procedure = name == "STATIC" or name.startswith("DYNAMIC")
    is_contact_control = name in ("CONTACT CONTROLS", "CONTACT STABILIZATION")
    if name == "CONTACT STABILIZATION":
        # The keyword itself *is* the stabilization request.
        return False, True
    return (has_stabilize and is_step_procedure), (has_stabilize and is_contact_control)


def detect_stabilization_in_deck(inp_text: str) -> Dict[str, Any]:
    """Detect stabilization keywords and the analysis step each one belongs to.

    Only explicit Abaqus keywords count. A deck that merely mentions the word in
    a comment does not enable anything.

    Returns a mapping with:

    * ``step_stabilization`` / ``contact_stabilization``: whether either control
      path is enabled anywhere in the deck.
    * ``steps``: ``[{"name", "step_stabilization", "contact_stabilization"}]``
      in deck order, one entry per ``*STEP`` ... ``*END STEP`` block.
    * ``unattributed_step_stabilization`` / ``unattributed_contact_stabilization``:
      keywords found outside every step block. Abaqus treats these keywords as
      step-scoped, so such a deck cannot be attributed to one ODB step.
    """
    marks: Dict[str, Any] = {
        "step_stabilization": False,
        "contact_stabilization": False,
        "steps": [],
        "unattributed_step_stabilization": False,
        "unattributed_contact_stabilization": False,
    }
    if not inp_text:
        return marks

    current: Optional[Dict[str, Any]] = None
    for line in _iter_deck_keywords(inp_text):
        name, parameters, flags = _parse_deck_keyword(line)
        if name == "STEP":
            if current is not None:
                # A step block that was never closed: keep its evidence rather
                # than dropping it silently.
                marks["steps"].append(current)
            current = {
                "name": parameters.get("NAME"),
                "step_stabilization": False,
                "contact_stabilization": False,
            }
            continue
        if name in ("END STEP", "ENDSTEP"):
            if current is not None:
                marks["steps"].append(current)
            current = None
            continue

        step_level, contact_level = _classify_stabilization(name, parameters, flags)
        if not (step_level or contact_level):
            continue
        if current is None:
            if step_level:
                marks["unattributed_step_stabilization"] = True
            if contact_level:
                marks["unattributed_contact_stabilization"] = True
            continue
        if step_level:
            current["step_stabilization"] = True
        if contact_level:
            current["contact_stabilization"] = True

    if current is not None:
        marks["steps"].append(current)

    marks["step_stabilization"] = bool(
        marks["unattributed_step_stabilization"]
        or any(entry["step_stabilization"] for entry in marks["steps"])
    )
    marks["contact_stabilization"] = bool(
        marks["unattributed_contact_stabilization"]
        or any(entry["contact_stabilization"] for entry in marks["steps"])
    )
    return marks


@dataclass(frozen=True)
class StabilizedStepSelection:
    """The single ODB step whose energy history the gate is allowed to use."""

    status: str
    step_name: Optional[str] = None
    reason: str = ""
    candidates: Tuple[str, ...] = ()
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return self.status == SELECTION_RESOLVED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "step_name": self.step_name,
            "reason": self.reason,
            "candidates": list(self.candidates),
            "details": dict(self.details),
        }


def resolve_stabilized_step(deck_marks: Any,
                            odb_step_names: Any) -> StabilizedStepSelection:
    """Bind deck stabilization keywords to exactly one ODB step.

    The gate verifies artificial damping for the step that requested it. If the
    deck enables stabilization in several steps, or the keyword lives outside a
    step block, or the named step is missing from the ODB, no single step is
    authoritative and the caller must block instead of borrowing another step's
    energy history.
    """
    if not isinstance(deck_marks, Mapping):
        return StabilizedStepSelection(
            status=SELECTION_UNRESOLVED,
            reason=REASON_STABILIZATION_STEP_UNATTRIBUTED,
            details={"deck_marks": "missing"},
        )

    candidates: list[str] = []
    unnamed: list[Dict[str, Any]] = []
    for entry in deck_marks.get("steps") or ():
        if not isinstance(entry, Mapping):
            continue
        if not (entry.get("step_stabilization") or entry.get("contact_stabilization")):
            continue
        name = entry.get("name")
        if not name:
            unnamed.append(dict(entry))
            continue
        candidates.append(str(name))

    unattributed = bool(
        deck_marks.get("unattributed_step_stabilization")
        or deck_marks.get("unattributed_contact_stabilization")
    )
    declared = list(deck_marks.get("steps") or ())
    details = {
        "declared_steps": [entry.get("name") for entry in declared
                           if isinstance(entry, Mapping)],
        "odb_steps": [str(name) for name in (odb_step_names or ())],
    }

    if unattributed or unnamed:
        return StabilizedStepSelection(
            status=SELECTION_UNRESOLVED,
            reason=REASON_STABILIZATION_STEP_UNATTRIBUTED,
            candidates=tuple(candidates),
            details=dict(details, unattributed_keywords=unattributed,
                         unnamed_stabilized_steps=len(unnamed)),
        )

    enabled = bool(
        deck_marks.get("step_stabilization")
        or deck_marks.get("contact_stabilization")
        or candidates
    )
    if not enabled:
        return StabilizedStepSelection(
            status=SELECTION_NOT_ENABLED,
            reason=REASON_NOT_ENABLED,
            details=details,
        )

    if not candidates:
        return StabilizedStepSelection(
            status=SELECTION_UNRESOLVED,
            reason=REASON_STABILIZATION_STEP_UNATTRIBUTED,
            details=dict(details, unnamed_stabilized_steps=0),
        )

    if len(candidates) > 1:
        return StabilizedStepSelection(
            status=SELECTION_UNRESOLVED,
            reason=REASON_STABILIZATION_STEP_AMBIGUOUS,
            candidates=tuple(candidates),
            details=details,
        )

    step_name = candidates[0]
    available = [str(name) for name in (odb_step_names or ())]
    if not available:
        return StabilizedStepSelection(
            status=SELECTION_UNRESOLVED,
            reason=REASON_STABILIZED_STEP_MISSING_IN_ODB,
            candidates=tuple(candidates),
            details=details,
        )
    if step_name in available:
        return StabilizedStepSelection(
            status=SELECTION_RESOLVED,
            step_name=step_name,
            candidates=tuple(candidates),
            details=details,
        )
    matches = [name for name in available if name.lower() == step_name.lower()]
    if len(matches) == 1:
        return StabilizedStepSelection(
            status=SELECTION_RESOLVED,
            step_name=matches[0],
            candidates=tuple(candidates),
            details=details,
        )
    return StabilizedStepSelection(
        status=SELECTION_UNRESOLVED,
        reason=REASON_STABILIZED_STEP_MISSING_IN_ODB,
        candidates=tuple(candidates),
        details=details,
    )
