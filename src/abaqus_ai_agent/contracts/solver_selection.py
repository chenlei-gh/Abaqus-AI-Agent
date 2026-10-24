from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class SolverSelection:
    """Deterministic engineering decision record for solver selection.

    ``blocked`` / ``blocking_reasons`` carry a hard pre-submission refusal
    (frozen contract D2: a user-chosen solver conflicting with a declared
    kinematic requirement blocks submission; the solver is never switched
    silently). A hard block is a refusal, not a pending confirmation, so it
    excludes ``requires_user_confirmation``.
    """
    solver: str
    analysis_type: str
    strategy: str
    reasons: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    assumptions: Tuple[str, ...] = ()
    confidence: str = "medium"
    requires_user_confirmation: bool = False
    evidence: Tuple[Dict[str, Any], ...] = ()
    blocked: bool = False
    blocking_reasons: Tuple[str, ...] = ()

    def __post_init__(self):
        if self.solver not in ("STANDARD", "EXPLICIT"):
            raise ValueError("unsupported solver: %s" % self.solver)
        if self.confidence not in ("high", "medium", "low"):
            raise ValueError("unsupported confidence: %s" % self.confidence)
        if not self.strategy:
            raise ValueError("strategy is required")
        if self.blocked and not self.blocking_reasons:
            raise ValueError("a blocked selection must carry structured blocking_reasons")
        if self.blocking_reasons and not self.blocked:
            raise ValueError("blocking_reasons require blocked=True")
        if self.blocked and self.requires_user_confirmation:
            raise ValueError("a hard block is not a pending confirmation: blocked excludes requires_user_confirmation")


class SolverSelectionBlocked(Exception):
    """Pre-submission hard block from a solver-selection conflict.

    Raised by the execution gate when a selection carries ``blocked=True``.
    The structured record travels on the exception; the message is only a
    rendering of its ``blocking_reasons``.
    """

    def __init__(self, selection: SolverSelection):
        self.selection = selection
        reasons = "; ".join(selection.blocking_reasons) or "solver selection blocked"
        super().__init__("Submission blocked by solver-selection conflict: %s" % reasons)


def _text(intent):
    values = [getattr(intent, "kind", ""), getattr(intent, "description", ""), getattr(intent, "analysis_type", "")]
    metadata = getattr(intent, "metadata", {}) or {}
    values.extend(str(metadata.get(k, "")) for k in ("analysis_type", "procedure", "solver", "dynamic_type", "event_type", "loading_type", "problem_class"))
    return " ".join(str(x).lower() for x in values if x)

def _flags(intent):
    metadata = dict(getattr(intent, "metadata", {}) or {})
    text = _text(intent)
    return {
        "explicit_requested": str(metadata.get("solver", "")).lower() == "explicit" or "explicit" in text,
        "standard_requested": str(metadata.get("solver", "")).lower() == "standard" or "implicit" in text,
        "impact": bool(metadata.get("impact")) or any(x in text for x in ("impact", "drop test", "blast", "crash", "collision")),
        "short_transient": bool(metadata.get("short_duration")) or any(x in text for x in ("short-duration", "short duration", "transient")),
        "complex_contact": bool(metadata.get("complex_contact")) or any(x in text for x in ("complex contact", "many-body contact", "self-contact")),
        "large_deformation": bool(metadata.get("large_deformation")) or any(x in text for x in ("large deformation", "large distortion", "large rotation")),
        "severe_discontinuity": bool(metadata.get("severe_discontinuity")) or any(x in text for x in ("severe discontinuity", "severe convergence", "unstable", "postbuckling")),
        "quasi_static": bool(metadata.get("quasi_static")) or any(x in text for x in ("quasi-static", "quasi static", "forming", "forging", "rolling")),
        "failure": bool(metadata.get("material_failure")) or any(x in text for x in ("material failure", "element deletion", "degradation")),
    }


# Analyses where a Standard/Explicit choice actually exists. Frequency and
# thermal procedures have no Explicit alternative, so a user solver preference
# there is not a solver-selection conflict.
_STRUCTURAL_ANALYSES = (
    "static", "dynamic", "dynamic-implicit", "implicit-dynamic",
    "explicit", "dynamic-explicit",
    "coupled", "coupled-thermal-stress", "coupled-temperature-displacement",
)

_DECLARED_SEPARATION_REVIEW = (
    "declared interface separation requirement: this selection does not assert "
    "that Abaqus/Standard is suitable for the declared separation behaviour; "
    "engineering confirmation is required"
)
_KEYWORD_SEPARATION_REVIEW = (
    "keyword-inferred separation cue triggers engineering review; only an "
    "explicit kinematic declaration participates in solver selection (contract D3)"
)
_DECLARED_SEPARATION_SUPPORT = (
    "declared interface separation requirement is consistent with the "
    "explicit-event contact behaviour driving this selection"
)


def _kinematics(intent):
    """Declared vs keyword-inferred kinematic requirements (evidence only).

    The strength tier matters: declared evidence participates in the decision
    and drives the D2 conflict block, while keyword-only cues may only trigger
    review (frozen contract D3).
    """
    from ..validation.condition_fidelity import kinematic_evidence
    sep = (kinematic_evidence(intent) or {}).get("separation") or {}
    return {
        "declared": bool(sep.get("declared")),
        "keyword": bool(sep.get("keyword")),
        "signals": tuple(sep.get("evidence") or ()),
    }


def _kinematic_evidence_record(signals):
    return {"source": "kinematic_evidence", "requirement": "separation",
            "strength": "declared", "signals": list(signals)}


def select_solver(intent):
    """Select a procedure from explicit engineering intent; never invent a choice."""
    analysis = str(getattr(intent, "analysis_type", None) or "").lower().replace("_", "-")
    text = _text(intent)
    flags = _flags(intent)
    if not analysis:
        if any(x in text for x in ("frequency", "modal", "eigenfrequency")): analysis = "frequency"
        elif any(x in text for x in ("heat transfer", "thermal")): analysis = "thermal"
        elif "coupled" in text and "temperature" in text: analysis = "coupled"
        elif any(x in text for x in ("dynamic", "transient", "impact")): analysis = "dynamic"
        else: analysis = "static"
    evidence = ({"source": "engineering_intent", "analysis_type": analysis},)
    kinematics = _kinematics(intent)
    # An analysis_type of dynamic-implicit is itself a user declaration of the
    # implicit procedure, so it counts as a user-chosen Standard for D2.
    user_standard = flags["standard_requested"] or analysis in ("dynamic-implicit", "implicit-dynamic")
    if kinematics["declared"] and user_standard and analysis in _STRUCTURAL_ANALYSES:
        return SolverSelection(
            "STANDARD", analysis, "BLOCKED",
            reasons=("user explicitly requested Abaqus/Standard",),
            confidence="high",
            evidence=evidence + (_kinematic_evidence_record(kinematics["signals"]),),
            blocked=True,
            blocking_reasons=(
                "user_solver_conflicts_with_declared_separation_requirement: the intent "
                "declares an interface separation requirement (signals: %s) while the user "
                "specified Abaqus/Standard; per frozen contract D2 the submission is "
                "blocked and the solver is not switched silently; resolve by revising the "
                "solver specification or the declared kinematic requirement"
                % (", ".join(kinematics["signals"]) or "declared"),
            ),
        )
    if analysis in ("frequency", "modal", "eigenfrequency", "buckling", "linear-buckling"):
        strategy = "FREQUENCY" if analysis in ("frequency", "modal", "eigenfrequency") else "BUCKLING"
        return SolverSelection("STANDARD", analysis, strategy, reasons=("eigenvalue/modal procedure is represented by Abaqus/Standard in the current selector",), confidence="high", evidence=evidence)
    if analysis in ("thermal", "heat-transfer"):
        return SolverSelection("STANDARD", "thermal", "HEAT_TRANSFER", reasons=("thermal-only analysis requires a heat-transfer procedure",), confidence="high", evidence=evidence)
    if analysis in ("coupled", "coupled-thermal-stress", "coupled-temperature-displacement"):
        if flags["impact"] or flags["short_transient"] or flags["complex_contact"]:
            reasons = tuple(x for x in ("short-duration transient loading" if flags["short_transient"] else None, "impact loading" if flags["impact"] else None, "complex contact interaction" if flags["complex_contact"] else None) if x)
            if kinematics["declared"]: reasons = reasons + (_DECLARED_SEPARATION_SUPPORT,)
            return SolverSelection("EXPLICIT", "coupled", "COUPLED_TEMPERATURE_DISPLACEMENT_EXPLICIT", reasons=reasons, warnings=("coupled explicit analysis requires energy/time-history checks appropriate to the event",), confidence="medium", requires_user_confirmation=True, evidence=evidence)
        warnings = ()
        confirmation = False
        if kinematics["declared"]:
            warnings = (_DECLARED_SEPARATION_REVIEW,)
            confirmation = True
        elif kinematics["keyword"]:
            warnings = (_KEYWORD_SEPARATION_REVIEW,)
            confirmation = True
        return SolverSelection("STANDARD", "coupled", "COUPLED_TEMPERATURE_DISPLACEMENT", reasons=("fully coupled thermal-mechanical response without explicit-event indicators",), warnings=warnings, confidence="high", requires_user_confirmation=confirmation, evidence=evidence)
    if analysis in ("dynamic", "dynamic-implicit", "dynamic-explicit", "explicit", "implicit-dynamic"):
        event = any(flags[k] for k in ("impact", "short_transient", "complex_contact", "severe_discontinuity", "large_deformation", "failure"))
        if flags["explicit_requested"] or event:
            reasons = []
            if flags["explicit_requested"]: reasons.append("explicit solver/procedure was explicitly requested")
            if flags["impact"]: reasons.append("impact or collision event")
            if flags["short_transient"]: reasons.append("short-duration transient response")
            if flags["complex_contact"]: reasons.append("complex contact interaction")
            if flags["severe_discontinuity"]: reasons.append("severe discontinuity or instability")
            if flags["large_deformation"]: reasons.append("large deformation/distortion")
            if flags["failure"]: reasons.append("material degradation/failure")
            if kinematics["declared"]: reasons.append(_DECLARED_SEPARATION_SUPPORT)
            warnings = ["Explicit selection is a procedure decision, not proof of physical adequacy.", "Energy, time-history, and stability diagnostics should be selected with the analysis outputs."]
            if flags["quasi_static"]: warnings.append("quasi-static Explicit requires kinetic/internal energy monitoring.")
            return SolverSelection("EXPLICIT", "dynamic", "DYNAMIC_EXPLICIT", reasons=tuple(reasons), warnings=tuple(warnings), assumptions=("explicit time integration is acceptable for the declared event",), confidence="high" if flags["explicit_requested"] else "medium", requires_user_confirmation=not flags["explicit_requested"], evidence=evidence)
        if flags["standard_requested"] or analysis in ("dynamic-implicit", "implicit-dynamic"):
            warnings = ["absence of explicit-event triggers is not proof that Standard is optimal"]
            if kinematics["keyword"]: warnings.append(_KEYWORD_SEPARATION_REVIEW)
            return SolverSelection("STANDARD", "dynamic", "DYNAMIC_IMPLICIT", reasons=("implicit dynamic procedure requested or no explicit-event trigger was identified",), warnings=tuple(warnings), confidence="medium", requires_user_confirmation=(not flags["standard_requested"]) or kinematics["keyword"], evidence=evidence)
        warnings = ["solver choice remains confirmation-recommended when event severity/contact behavior is underspecified"]
        if kinematics["declared"]: warnings.append(_DECLARED_SEPARATION_REVIEW)
        elif kinematics["keyword"]: warnings.append(_KEYWORD_SEPARATION_REVIEW)
        return SolverSelection("STANDARD", "dynamic", "DYNAMIC_IMPLICIT", reasons=("dynamic analysis with no deterministic Explicit trigger in the supplied intent",), warnings=tuple(warnings), assumptions=("no impact, severe discontinuity, or highly nonlinear contact event was declared",), confidence="low", requires_user_confirmation=True, evidence=evidence)
    if flags["explicit_requested"] or any(flags[k] for k in ("impact", "complex_contact", "severe_discontinuity", "large_deformation", "failure", "quasi_static")):
        reasons = []
        for key, label in (("explicit_requested", "explicit solver/procedure was explicitly requested"), ("complex_contact", "complex contact interaction"), ("severe_discontinuity", "severe discontinuity or instability"), ("large_deformation", "large deformation/distortion"), ("failure", "material degradation/failure"), ("quasi_static", "highly nonlinear quasi-static process")):
            if flags[key]: reasons.append(label)
        if kinematics["declared"]: reasons.append(_DECLARED_SEPARATION_SUPPORT)
        return SolverSelection("EXPLICIT", "static", "QUASI_STATIC_EXPLICIT", reasons=tuple(reasons), warnings=("Explicit is being used for a problem described as static/quasi-static.", "Acceptance should include kinetic/internal energy monitoring and response stabilization checks."), assumptions=("the explicit formulation is being used as a nonlinear-event/quasi-static strategy",), confidence="medium", requires_user_confirmation=True, evidence=evidence)
    warnings = ()
    confirmation = False
    confidence = "high"
    if kinematics["declared"]:
        warnings = (_DECLARED_SEPARATION_REVIEW,)
        confirmation = True
        confidence = "medium"
    elif kinematics["keyword"]:
        warnings = (_KEYWORD_SEPARATION_REVIEW,)
        confirmation = True
        confidence = "medium"
    return SolverSelection("STANDARD", "static", "STATIC_GENERAL", reasons=("static structural response with no explicit-event trigger was declared",), warnings=warnings, assumptions=("implicit general static procedure is appropriate for the declared problem",), confidence=confidence, requires_user_confirmation=confirmation, evidence=evidence)
