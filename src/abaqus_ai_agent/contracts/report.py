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
    assumptions: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()
    evidence: Tuple[Any, ...] = ()
    provenance: Any = None
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
        sections.setdefault("acceptance", getattr(run, "acceptance_passed", None))
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
        return cls(title or "Abaqus Engineering Analysis Report", objective=objective,
                   results=tuple(sections.pop("results", ()) or ()),
                   figures=tuple(sections.pop("figures", ()) or ()),
                   engineering_checks=tuple(sections.pop("engineering_checks", ()) or ()),
                   acceptance=sections.pop("acceptance", None),
                   evidence=tuple(sections.pop("evidence", tuple(getattr(getattr(run, "evidence", None), "items", ()) or ())) or ()),
                   provenance=getattr(run, "provenance", None), metadata=dict(metadata, **sections.pop("metadata", {})), **sections)
