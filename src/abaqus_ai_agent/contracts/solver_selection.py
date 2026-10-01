from dataclasses import dataclass
from typing import Any, Dict, Tuple

@dataclass(frozen=True)
class SolverSelection:
    """Deterministic engineering decision record for solver selection."""
    solver: str
    analysis_type: str
    strategy: str
    reasons: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    assumptions: Tuple[str, ...] = ()
    confidence: str = "medium"
    requires_user_confirmation: bool = False
    evidence: Tuple[Dict[str, Any], ...] = ()

    def __post_init__(self):
        if self.solver not in ("STANDARD", "EXPLICIT"):
            raise ValueError("unsupported solver: %s" % self.solver)
        if self.confidence not in ("high", "medium", "low"):
            raise ValueError("unsupported confidence: %s" % self.confidence)
        if not self.strategy:
            raise ValueError("strategy is required")

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
    if analysis in ("frequency", "modal", "eigenfrequency", "buckling", "linear-buckling"):
        strategy = "FREQUENCY" if analysis in ("frequency", "modal", "eigenfrequency") else "BUCKLING"
        return SolverSelection("STANDARD", analysis, strategy, reasons=("eigenvalue/modal procedure is represented by Abaqus/Standard in the current selector",), confidence="high", evidence=evidence)
    if analysis in ("thermal", "heat-transfer"):
        return SolverSelection("STANDARD", "thermal", "HEAT_TRANSFER", reasons=("thermal-only analysis requires a heat-transfer procedure",), confidence="high", evidence=evidence)
    if analysis in ("coupled", "coupled-thermal-stress", "coupled-temperature-displacement"):
        if flags["impact"] or flags["short_transient"] or flags["complex_contact"]:
            reasons = tuple(x for x in ("short-duration transient loading" if flags["short_transient"] else None, "impact loading" if flags["impact"] else None, "complex contact interaction" if flags["complex_contact"] else None) if x)
            return SolverSelection("EXPLICIT", "coupled", "COUPLED_TEMPERATURE_DISPLACEMENT_EXPLICIT", reasons=reasons, warnings=("coupled explicit analysis requires energy/time-history checks appropriate to the event",), confidence="medium", requires_user_confirmation=True, evidence=evidence)
        return SolverSelection("STANDARD", "coupled", "COUPLED_TEMPERATURE_DISPLACEMENT", reasons=("fully coupled thermal-mechanical response without explicit-event indicators",), confidence="high", evidence=evidence)
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
            warnings = ["Explicit selection is a procedure decision, not proof of physical adequacy.", "Energy, time-history, and stability diagnostics should be selected with the analysis outputs."]
            if flags["quasi_static"]: warnings.append("quasi-static Explicit requires kinetic/internal energy monitoring.")
            return SolverSelection("EXPLICIT", "dynamic", "DYNAMIC_EXPLICIT", reasons=tuple(reasons), warnings=tuple(warnings), assumptions=("explicit time integration is acceptable for the declared event",), confidence="high" if flags["explicit_requested"] else "medium", requires_user_confirmation=not flags["explicit_requested"], evidence=evidence)
        if flags["standard_requested"] or analysis in ("dynamic-implicit", "implicit-dynamic"):
            return SolverSelection("STANDARD", "dynamic", "DYNAMIC_IMPLICIT", reasons=("implicit dynamic procedure requested or no explicit-event trigger was identified",), warnings=("absence of explicit-event triggers is not proof that Standard is optimal",), confidence="medium", requires_user_confirmation=not flags["standard_requested"], evidence=evidence)
        return SolverSelection("STANDARD", "dynamic", "DYNAMIC_IMPLICIT", reasons=("dynamic analysis with no deterministic Explicit trigger in the supplied intent",), warnings=("solver choice remains confirmation-recommended when event severity/contact behavior is underspecified",), assumptions=("no impact, severe discontinuity, or highly nonlinear contact event was declared",), confidence="low", requires_user_confirmation=True, evidence=evidence)
    if flags["explicit_requested"] or any(flags[k] for k in ("impact", "complex_contact", "severe_discontinuity", "large_deformation", "failure", "quasi_static")):
        reasons = []
        for key, label in (("explicit_requested", "explicit solver/procedure was explicitly requested"), ("complex_contact", "complex contact interaction"), ("severe_discontinuity", "severe discontinuity or instability"), ("large_deformation", "large deformation/distortion"), ("failure", "material degradation/failure"), ("quasi_static", "highly nonlinear quasi-static process")):
            if flags[key]: reasons.append(label)
        return SolverSelection("EXPLICIT", "static", "QUASI_STATIC_EXPLICIT", reasons=tuple(reasons), warnings=("Explicit is being used for a problem described as static/quasi-static.", "Acceptance should include kinetic/internal energy monitoring and response stabilization checks."), assumptions=("the explicit formulation is being used as a nonlinear-event/quasi-static strategy",), confidence="medium", requires_user_confirmation=True, evidence=evidence)
    return SolverSelection("STANDARD", "static", "STATIC_GENERAL", reasons=("static structural response with no explicit-event trigger was declared",), assumptions=("implicit general static procedure is appropriate for the declared problem",), confidence="high", evidence=evidence)
