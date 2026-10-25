"""Structured engineering conclusions bound to evidence and applicability scope.

The acceptance layer and the engineering-objective layer are deliberately kept
separate. An ACCEPTANCE PASS means only that the listed acceptance criteria and
prerequisite gates passed; it does not prove an untested engineering objective.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Mapping, Tuple


class ReportConclusionLayer(str, Enum):
    ACCEPTANCE = "ACCEPTANCE"
    ENGINEERING_OBJECTIVE = "ENGINEERING_OBJECTIVE"
    CRITERION = "CRITERION"


class ReportConclusionStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_PROVEN = "NOT_PROVEN"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ReportConclusion:
    conclusion_id: str
    layer: ReportConclusionLayer
    statement: str
    status: ReportConclusionStatus
    evidence: Tuple[str, ...] = ()
    scope: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conclusion_id": self.conclusion_id,
            "layer": getattr(self.layer, "value", str(self.layer)),
            "statement": self.statement,
            "status": getattr(self.status, "value", str(self.status)),
            "evidence": list(self.evidence),
            "scope": self.scope,
            "source": self.source,
        }


_HARD_REJECT_PREFIXES = (
    "evidence_tampered",
    "evidence_stale",
    "evidence_corrupt",
    "solver_execution:",
    "solver_",
    "unsupported_",
    "corrupt_",
    "material_mapping:",
    "elastic_range_exceeded",
    "unit_mismatch:",
)
_MISSING_EVIDENCE_PREFIXES = (
    "missing_",
    "evidence_incomplete",
    "stress_check:",
    "yield_check:",
    "extraction_missing_for_criterion:",
    "stabilization_energy_unverifiable:",
    "dynamic_energy_unverifiable:",
    "dynamic_energy_incomplete:",
    "contact_diagnostics_insufficient_evidence",
)
_UNVERIFIABLE_PREFIXES = (
    "criteria_evaluation_error:",
)
_OBJECTIVE_CLAIMS = (
    {
        "id": "pull_out",
        "label": "pull-out",
        "objective_tokens": (
            "pull-out", "pull out", "pullout", "pull_out",
            "脱扣", "抗脱扣", "拔出", "拉脱",
        ),
        "criterion_tokens": (
            "pull-out", "pull out", "pullout", "pull_out",
            "脱扣", "抗脱扣", "拔出", "拉脱",
        ),
    },
)


def _field(item: Any, *names: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        for name in names:
            value = item.get(name)
            if value is not None:
                return value
    else:
        for name in names:
            value = getattr(item, name, None)
            if value is not None:
                return value
    return default


def _dedupe(values):
    seen = set()
    result = []
    for value in values:
        text = str(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def _acceptance_view(acceptance: Any) -> Dict[str, Any]:
    if isinstance(acceptance, bool):
        return {
            "passed": acceptance,
            "status": "PASS" if acceptance else "FAIL",
            "acceptance_status": "PASS" if acceptance else "FAIL",
            "deliverable": acceptance,
            "criteria": (),
            "gates": {},
            "failures": (),
            "blocked": (),
            "missing_required_metrics": (),
            "missing_required_fields": (),
            "missing_required_gates": (),
            "result_validity": "VALID" if acceptance else "CRITERIA_FAILED",
            "warnings": (),
            "source": "acceptance:boolean",
            "coarse": True,
        }
    if acceptance is None:
        return {
            "passed": None,
            "status": "",
            "acceptance_status": "",
            "deliverable": False,
            "criteria": (),
            "gates": {},
            "failures": (),
            "blocked": (),
            "missing_required_metrics": (),
            "missing_required_fields": (),
            "missing_required_gates": (),
            "result_validity": "",
            "warnings": (),
            "source": "acceptance:missing",
            "coarse": True,
        }
    status = _field(acceptance, "acceptance_status", "status", default="") or ""
    passed = _field(acceptance, "passed", default=None)
    if passed is None:
        status_upper = str(status).upper()
        if status_upper in ("PASS", "WARNING"):
            passed = True
        elif status_upper in ("FAIL", "BLOCKED", "RESULT_INVALID", "REJECTED"):
            passed = False
    criteria = tuple(_field(acceptance, "criteria", default=()) or ())
    gates = dict(_field(acceptance, "gates", default={}) or {})
    return {
        "passed": passed,
        "status": status,
        "acceptance_status": _field(acceptance, "acceptance_status", default="") or status,
        "deliverable": bool(_field(acceptance, "deliverable", default=False)),
        "criteria": criteria,
        "gates": gates,
        "failures": tuple(_field(acceptance, "failures", default=()) or ()),
        "blocked": tuple(_field(acceptance, "blocked", default=()) or ()),
        "missing_required_metrics": tuple(_field(acceptance, "missing_required_metrics", default=()) or ()),
        "missing_required_fields": tuple(_field(acceptance, "missing_required_fields", default=()) or ()),
        "missing_required_gates": tuple(_field(acceptance, "missing_required_gates", default=()) or ()),
        "result_validity": str(_field(acceptance, "result_validity", default="") or ""),
        "warnings": tuple(_field(acceptance, "warnings", default=()) or ()),
        "source": "acceptance",
        "coarse": not (criteria or gates),
    }


def _criterion_status(criterion: Any) -> ReportConclusionStatus:
    passed = _field(criterion, "passed", default=None)
    if passed is True:
        return ReportConclusionStatus.PASS
    if passed is False:
        return ReportConclusionStatus.FAIL
    status = str(_field(criterion, "status", default="") or "").upper()
    if status in ("PASS", "OK", "TRUE"):
        return ReportConclusionStatus.PASS
    if status in ("FAIL", "FALSE"):
        return ReportConclusionStatus.FAIL
    return ReportConclusionStatus.NOT_PROVEN


def _criterion_name(criterion: Any) -> str:
    name = _field(criterion, "name", "value_key", "metric", "key", default="unnamed criterion")
    return str(name)


def _criterion_statement(criterion: Any) -> str:
    name = _criterion_name(criterion)
    actual = _field(criterion, "actual", "value", default=None)
    operator = _field(criterion, "operator", "op", default=None)
    limit = _field(criterion, "limit", "target", default=None)
    unit = str(_field(criterion, "unit", default="") or "")
    status = _criterion_status(criterion).value
    if actual is not None and operator and limit is not None:
        expression = "%s %s %s" % (actual, operator, limit)
        if unit:
            expression = "%s %s" % (expression, unit)
    elif actual is not None:
        expression = "actual=%s" % actual
        if limit is not None:
            expression = "%s, target=%s" % (expression, limit)
        if unit:
            expression = "%s %s" % (expression, unit)
    else:
        expression = "actual/limit unavailable"
    return "%s: %s -> %s" % (name, expression, status)


def _scope(run_id: str, model_name: str, physics_domain: str, extra: str = "") -> str:
    parts = []
    if run_id:
        parts.append("run=%s" % run_id)
    if model_name:
        parts.append("model=%s" % model_name)
    if physics_domain:
        parts.append("physics_domain=%s" % physics_domain)
    parts.append("only the analyzed load case and the listed evidence are covered")
    if extra:
        parts.append(extra)
    return "; ".join(parts)


def _acceptance_status(view: Dict[str, Any]) -> ReportConclusionStatus:
    failures = tuple(str(item) for item in view["failures"])
    blocked = tuple(str(item) for item in view["blocked"])
    combined = failures + blocked

    if any(item.startswith(_HARD_REJECT_PREFIXES) for item in combined):
        return ReportConclusionStatus.REJECTED
    if any(_criterion_status(criterion) == ReportConclusionStatus.FAIL for criterion in view["criteria"]):
        return ReportConclusionStatus.FAIL

    non_missing_blocked = [
        item for item in blocked
        if not item.startswith(_MISSING_EVIDENCE_PREFIXES)
        and not item.startswith(_UNVERIFIABLE_PREFIXES)
    ]
    if non_missing_blocked:
        return ReportConclusionStatus.REJECTED

    missing = (
        view["missing_required_metrics"]
        or view["missing_required_fields"]
        or view["missing_required_gates"]
    )
    missing_evidence = any(item.startswith(_MISSING_EVIDENCE_PREFIXES) for item in combined)
    unverifiable = any(item.startswith(_UNVERIFIABLE_PREFIXES) for item in combined)
    if missing or missing_evidence or unverifiable:
        return ReportConclusionStatus.NOT_PROVEN

    result_validity = view["result_validity"].upper()
    if result_validity in ("RESULT_INVALID", "SOLVER_FAILED", "EVIDENCE_TAMPERED", "EVIDENCE_STALE", "EVIDENCE_CORRUPT"):
        return ReportConclusionStatus.REJECTED
    if result_validity == "INCOMPLETE":
        return ReportConclusionStatus.NOT_PROVEN
    if view["passed"] is True:
        return ReportConclusionStatus.PASS
    if view["passed"] is False:
        coarse_status = str(view["status"] or view["acceptance_status"] or "").upper()
        if coarse_status == "BLOCKED":
            return ReportConclusionStatus.NOT_PROVEN
        if coarse_status in ("RESULT_INVALID", "REJECTED"):
            return ReportConclusionStatus.REJECTED
        return ReportConclusionStatus.FAIL
    return ReportConclusionStatus.NOT_PROVEN


def _acceptance_statement(view: Dict[str, Any], status: ReportConclusionStatus) -> str:
    if status == ReportConclusionStatus.PASS and view.get("coarse"):
        statement = "A coarse acceptance status PASS was supplied without criterion-level evidence; only the acceptance-layer verdict is recorded."
    elif status == ReportConclusionStatus.PASS:
        statement = "Defined acceptance criteria and prerequisite gates passed."
    elif status == ReportConclusionStatus.FAIL:
        statement = "Valid evidence shows at least one defined acceptance criterion or engineering check failed."
    elif status == ReportConclusionStatus.REJECTED:
        statement = "The result is inadmissible under the established acceptance contract (input, evidence, or prerequisite gate violation)."
    else:
        statement = "Acceptance is NOT PROVEN because required metrics or evidence are missing."
    if view["warnings"]:
        statement = "%s Warnings remain: %s." % (statement, ", ".join(str(item) for item in view["warnings"]))
    if view["result_validity"] and view["result_validity"].upper() != "VALID":
        statement = "%s Result validity: %s." % (statement, view["result_validity"])
    return statement


def _acceptance_evidence(view: Dict[str, Any]) -> Tuple[str, ...]:
    evidence = []
    for criterion in view["criteria"]:
        evidence.append("criterion:%s=%s" % (_criterion_name(criterion), _criterion_status(criterion).value))
    for key, value in view["gates"].items():
        evidence.append("gate:%s=%s" % (key, value))
    for name in view["missing_required_metrics"]:
        evidence.append("missing_metric:%s" % name)
    for name in view["missing_required_fields"]:
        evidence.append("missing_field:%s" % name)
    for name in view["missing_required_gates"]:
        evidence.append("missing_gate:%s" % name)
    for item in view["failures"]:
        evidence.append("failure:%s" % item)
    for item in view["blocked"]:
        evidence.append("blocked:%s" % item)
    if not evidence:
        evidence.append("%s:status=%s" % (view["source"], view["status"] or "unknown"))
    return _dedupe(evidence)


def _criterion_text(criterion: Any) -> str:
    values = (
        _field(criterion, "name", default=""),
        _field(criterion, "value_key", default=""),
        _field(criterion, "metric", default=""),
        _field(criterion, "key", default=""),
    )
    return " ".join(str(value) for value in values if value).lower()


def _detected_objective_claims(objective_context: str):
    normalized = str(objective_context or "").lower()
    if not normalized:
        return ()
    return tuple(
        claim for claim in _OBJECTIVE_CLAIMS
        if any(token in normalized for token in claim["objective_tokens"])
    )


def _matching_criteria(claim, criteria):
    matches = []
    for criterion in criteria:
        text = _criterion_text(criterion)
        if any(token in text for token in claim["criterion_tokens"]):
            matches.append(criterion)
    return tuple(matches)


def _objective_status(base_status: ReportConclusionStatus, matched) -> ReportConclusionStatus:
    if base_status == ReportConclusionStatus.REJECTED:
        return ReportConclusionStatus.REJECTED
    if base_status == ReportConclusionStatus.NOT_PROVEN:
        return ReportConclusionStatus.NOT_PROVEN
    if not matched:
        return ReportConclusionStatus.NOT_PROVEN
    statuses = tuple(_criterion_status(criterion) for criterion in matched)
    if any(status == ReportConclusionStatus.FAIL for status in statuses):
        return ReportConclusionStatus.FAIL
    if base_status == ReportConclusionStatus.FAIL:
        return ReportConclusionStatus.NOT_PROVEN
    if all(status == ReportConclusionStatus.PASS for status in statuses):
        return ReportConclusionStatus.PASS
    return ReportConclusionStatus.NOT_PROVEN


def _objective_statement(claim, status: ReportConclusionStatus, matched) -> str:
    label = claim["label"]
    names = ", ".join(_criterion_name(criterion) for criterion in matched)
    if status == ReportConclusionStatus.PASS:
        return "%s capability is supported by the matched acceptance criterion: %s." % (label, names)
    if status == ReportConclusionStatus.FAIL:
        return "%s capability is contradicted by the matched acceptance criterion: %s." % (label, names)
    if status == ReportConclusionStatus.REJECTED:
        return "%s capability cannot be concluded because the underlying result is inadmissible." % label
    if matched:
        return "%s capability is NOT PROVEN: the matched criterion did not provide affirmative evidence." % label
    return "%s capability is NOT PROVEN: no matching acceptance criterion was supplied." % label


def _objective_evidence(claim, status: ReportConclusionStatus, matched) -> Tuple[str, ...]:
    evidence = ["objective:%s" % claim["id"]]
    if matched:
        evidence.extend("criterion:%s" % _criterion_name(criterion) for criterion in matched)
    else:
        evidence.append("criterion-search:no-match")
    evidence.append("acceptance:%s" % status.value)
    return _dedupe(evidence)


def build_report_conclusions(
    acceptance: Any,
    objective_context: str = "",
    run_id: str = "",
    model_name: str = "",
    physics_domain: str = "",
) -> Tuple[ReportConclusion, ...]:
    """Build traceable conclusions without changing the acceptance verdict itself."""
    view = _acceptance_view(acceptance)
    base_status = _acceptance_status(view)
    base_scope = _scope(run_id, model_name, physics_domain)
    conclusions = [
        ReportConclusion(
            conclusion_id="acceptance:overall",
            layer=ReportConclusionLayer.ACCEPTANCE,
            statement=_acceptance_statement(view, base_status),
            status=base_status,
            evidence=_acceptance_evidence(view),
            scope=base_scope,
            source=view["source"],
        )
    ]
    for index, criterion in enumerate(view["criteria"], 1):
        name = _criterion_name(criterion)
        conclusions.append(ReportConclusion(
            conclusion_id="criterion:%02d:%s" % (index, name),
            layer=ReportConclusionLayer.CRITERION,
            statement=_criterion_statement(criterion),
            status=_criterion_status(criterion),
            evidence=("criterion:%s" % name,),
            scope=_scope(run_id, model_name, physics_domain, "criterion-level only"),
            source="acceptance.criteria",
        ))
    for claim in _detected_objective_claims(objective_context):
        matched = _matching_criteria(claim, view["criteria"])
        objective_status = _objective_status(base_status, matched)
        conclusions.append(ReportConclusion(
            conclusion_id="objective:%s" % claim["id"],
            layer=ReportConclusionLayer.ENGINEERING_OBJECTIVE,
            statement=_objective_statement(claim, objective_status, matched),
            status=objective_status,
            evidence=_objective_evidence(claim, objective_status, matched),
            scope=_scope(
                run_id, model_name, physics_domain,
                "objective claim is limited to the analyzed model and load case; no other failure modes are covered",
            ),
            source="report.objective+acceptance.criteria",
        ))
    return tuple(conclusions)
