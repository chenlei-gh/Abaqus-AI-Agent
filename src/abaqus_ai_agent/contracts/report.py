from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

@dataclass(frozen=True)
class ReportFigure:
    kind: str
    path: str
    caption: str = ""
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class EngineeringReportData:
    """Structured, source-first data model for an engineering deliverable."""
    title: str
    objective: str = ""
    model: Dict[str, Any] = field(default_factory=dict)
    solver: Dict[str, Any] = field(default_factory=dict)
    materials: Tuple[Dict[str, Any], ...] = ()
    boundary_conditions: Tuple[Dict[str, Any], ...] = ()
    loads: Tuple[Dict[str, Any], ...] = ()
    mesh: Dict[str, Any] = field(default_factory=dict)
    results: Tuple[Any, ...] = ()
    figures: Tuple[ReportFigure, ...] = ()
    engineering_checks: Tuple[Any, ...] = ()
    acceptance: Any = None
    sensitivity: Any = None
    uncertainty: Any = None
    fatigue: Any = None
    contact_diagnostics: Any = None
    mechanism: Any = None
    assumptions: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()
    evidence: Tuple[Any, ...] = ()
    provenance: Any = None
    result_intelligence: Any = None
    self_healing: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    @classmethod
    def from_analysis(cls, run, title=None, objective="", **sections):
        metadata = dict(getattr(run, "metadata", {}) or {})
        metadata.setdefault("run_id", getattr(run, "id", None))
        metadata.setdefault("model_name", getattr(run, "model_name", None))
        metadata.setdefault("job_name", getattr(run, "job_name", None))
        state = getattr(run, "state", None)
        metadata.setdefault("run_state", getattr(state, "value", state))
        metadata.setdefault("engineering_status", getattr(run, "engineering_status", None))
        sections.setdefault("results", getattr(run, "metrics", ()))
        sections.setdefault("solver", metadata.get("solver_selection", {}))
        profile = metadata.get("postprocess_profile")
        if profile is not None:
            sections.setdefault("metadata", {})
            sections["metadata"] = dict(sections["metadata"], postprocess_profile=profile)
        acceptance_evidence = ()
        fatigue_evidence = ()
        contact_evidence = ()
        mechanism_evidence = ()
        sensitivity_evidence = ()
        uncertainty_evidence = ()
        if getattr(run, "evidence", None):
            acceptance_evidence = tuple(x for x in run.evidence.items if getattr(x, "kind", None) == "acceptance")
            fatigue_evidence = tuple(x for x in run.evidence.items if getattr(x, "kind", None) == "fatigue")
            contact_evidence = tuple(x for x in run.evidence.items if getattr(x, "kind", None) == "contact_diagnostics")
            mechanism_evidence = tuple(x for x in run.evidence.items if getattr(x, "kind", None) in ("mechanism", "kinematics", "topology"))
            sensitivity_evidence = tuple(x for x in run.evidence.items if getattr(x, "kind", None) == "sensitivity")
            uncertainty_evidence = tuple(x for x in run.evidence.items if getattr(x, "kind", None) == "uncertainty")
        sections.setdefault("acceptance", acceptance_evidence[-1].value if acceptance_evidence else getattr(run, "acceptance_passed", None))
        if fatigue_evidence:
            sections.setdefault("fatigue", fatigue_evidence[-1].value)
        if contact_evidence:
            sections.setdefault("contact_diagnostics", contact_evidence[-1].value)
        if mechanism_evidence:
            sections.setdefault("mechanism", mechanism_evidence[-1].value)
        if sensitivity_evidence:
            sections.setdefault("sensitivity", sensitivity_evidence[-1].value)
        if uncertainty_evidence:
            sections.setdefault("uncertainty", uncertainty_evidence[-1].value)
        if "mesh" not in sections:
            sections["mesh"] = {}
        if getattr(run, "metadata", None):
            if run.metadata.get("mesh_strategy") is not None:
                sections["mesh"] = dict(sections["mesh"], strategy=run.metadata["mesh_strategy"])
        if getattr(run, "evidence", None):
            mesh_quality = tuple(x for x in run.evidence.items if getattr(x, "kind", None) == "mesh_quality")
            mesh_convergence = tuple(x for x in run.evidence.items if getattr(x, "kind", None) == "mesh_convergence")
            if mesh_quality or mesh_convergence:
                sections["mesh"] = dict(sections["mesh"], quality=mesh_quality, convergence=mesh_convergence)
        ri = getattr(run, "result_intelligence", None) or metadata.get("result_intelligence") or sections.get("result_intelligence")
        sections.setdefault("result_intelligence", ri)
        sh = getattr(run, "self_healing", None) or metadata.get("self_healing") or sections.get("self_healing")
        sections.setdefault("self_healing", sh)
        return cls(title or "Abaqus Engineering Analysis Report", objective=objective,
                   results=tuple(sections.pop("results", ()) or ()),
                   figures=tuple(sections.pop("figures", ()) or ()),
                   engineering_checks=tuple(sections.pop("engineering_checks", ()) or ()),
                   acceptance=sections.pop("acceptance", None),
                   evidence=tuple(sections.pop("evidence", tuple(getattr(getattr(run, "evidence", None), "items", ()) or ())) or ()),
                   provenance=getattr(run, "provenance", None),
                   result_intelligence=sections.pop("result_intelligence", None),
                   self_healing=sections.pop("self_healing", None),
                   metadata=dict(metadata, **sections.pop("metadata", {})), **sections)
