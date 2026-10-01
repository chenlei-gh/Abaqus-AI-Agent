from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

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
        return cls(title or "Abaqus Engineering Analysis Report", objective=objective,
                   results=tuple(sections.pop("results", ()) or ()),
                   engineering_checks=tuple(sections.pop("engineering_checks", ()) or ()),
                   acceptance=sections.pop("acceptance", None),
                   evidence=tuple(sections.pop("evidence", tuple(getattr(getattr(run, "evidence", None), "items", ()) or ())) or ()),
                   provenance=getattr(run, "provenance", None), metadata=metadata, **sections)
