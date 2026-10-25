from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Tuple

@dataclass(frozen=True)
class ReportFigure:
    kind: str
    path: str
    caption: str = ""
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

class ReportFactClass(str, Enum):
    """Evidentiary role of a statement in an engineering report."""
    RESULT = "RESULT"
    LIMITATION = "LIMITATION"
    DEV_PROCESS = "DEV_PROCESS"


@dataclass(frozen=True)
class ReportFact:
    """A single classified report statement.

    ``LIMITATION`` facts are mandatory-retention facts: they constrain the
    validity or applicability of the reported results and must not be removed
    to improve readability.
    """
    category: ReportFactClass
    statement: str
    source: str = ""

    @property
    def mandatory_retention(self) -> bool:
        return self.category == ReportFactClass.LIMITATION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": getattr(self.category, "value", str(self.category)),
            "statement": self.statement,
            "source": self.source,
            "mandatory_retention": self.mandatory_retention,
        }


def _result_fact(item: Any) -> "ReportFact | None":
    if isinstance(item, dict):
        name = item.get("name") or item.get("metric") or ""
        value = item.get("value")
        if value is None:
            value = item.get("actual")
        unit = item.get("unit") or ""
        source = item.get("source")
    else:
        name = getattr(item, "name", "") or getattr(item, "metric", "") or ""
        value = getattr(item, "value", None)
        if value is None:
            value = getattr(item, "actual", None)
        unit = getattr(item, "unit", "") or ""
        source = getattr(item, "source", None)

    if name and value is not None:
        statement = "%s: %s" % (name, value)
    elif name:
        statement = str(name)
    elif value is not None:
        statement = str(value)
    else:
        statement = str(item).strip()
    if not statement:
        return None
    if unit:
        statement = "%s %s" % (statement, unit)
    return ReportFact(ReportFactClass.RESULT, statement, str(source or "results"))


def _as_mapping(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        return data if isinstance(data, dict) else {}
    return {}


def _self_healing_facts(value: Any) -> Tuple["ReportFact", ...]:
    data = _as_mapping(value)
    if not data:
        return ()
    facts = []
    attempts = data.get("attempts") or ()
    total_attempts = data.get("total_attempts", len(attempts))
    healed = data.get("healed")
    initial_status = data.get("initial_status") or "unknown"
    final_status = data.get("final_status") or "unknown"
    if healed is not None or total_attempts:
        facts.append(ReportFact(
            ReportFactClass.DEV_PROCESS,
            "Self-healing cycle: healed=%s; attempts=%s; initial_status=%s; final_status=%s"
            % (healed, total_attempts, initial_status, final_status),
            "self_healing",
        ))
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    if metadata.get("awaiting_confirmation"):
        facts.append(ReportFact(
            ReportFactClass.DEV_PROCESS,
            "Self-healing changes were proposed but not applied (awaiting confirmation).",
            "self_healing.metadata",
        ))
    for issue in data.get("unresolved_issues") or ():
        issue_text = str(issue).strip()
        if issue_text:
            facts.append(ReportFact(
                ReportFactClass.DEV_PROCESS,
                "Unresolved self-healing issue: %s" % issue_text,
                "self_healing.unresolved_issues",
            ))
    for attempt in attempts:
        attempt_data = _as_mapping(attempt)
        if not attempt_data:
            continue
        triggers = attempt_data.get("trigger_issues") or ()
        trigger_text = "; ".join(str(t) for t in triggers if str(t).strip())
        statement = "Healing attempt %s: outcome=%s" % (
            attempt_data.get("attempt_number", "?"),
            attempt_data.get("outcome", "UNKNOWN"),
        )
        if trigger_text:
            statement = "%s; triggers=%s" % (statement, trigger_text)
        facts.append(ReportFact(
            ReportFactClass.DEV_PROCESS,
            statement,
            "self_healing.attempts",
        ))
    return tuple(facts)


def classify_report_facts(
    results: Any = (),
    limitations: Any = (),
    self_healing: Any = None,
    limitation_source: str = "report.limitations",
) -> Tuple[ReportFact, ...]:
    """Classify existing report evidence without inventing new facts."""
    facts = []
    for item in results or ():
        fact = _result_fact(item)
        if fact is not None:
            facts.append(fact)
    for limitation in limitations or ():
        limitation_text = str(limitation).strip()
        if limitation_text:
            facts.append(ReportFact(
                ReportFactClass.LIMITATION,
                limitation_text,
                limitation_source,
            ))
    facts.extend(_self_healing_facts(self_healing))
    return tuple(facts)


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
    classified_facts: Tuple[ReportFact, ...] = ()
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
        sections.setdefault(
            "classified_facts",
            classify_report_facts(
                sections.get("results", ()),
                sections.get("limitations", ()),
                sections.get("self_healing"),
            ),
        )
        return cls(title or "Abaqus Engineering Analysis Report", objective=objective,
                   results=tuple(sections.pop("results", ()) or ()),
                   figures=tuple(sections.pop("figures", ()) or ()),
                   engineering_checks=tuple(sections.pop("engineering_checks", ()) or ()),
                   acceptance=sections.pop("acceptance", None),
                   evidence=tuple(sections.pop("evidence", tuple(getattr(getattr(run, "evidence", None), "items", ()) or ())) or ()),
                   provenance=getattr(run, "provenance", None),
                   result_intelligence=sections.pop("result_intelligence", None),
                   self_healing=sections.pop("self_healing", None),
                   classified_facts=sections.pop("classified_facts", ()),
                   metadata=dict(metadata, **sections.pop("metadata", {})), **sections)
