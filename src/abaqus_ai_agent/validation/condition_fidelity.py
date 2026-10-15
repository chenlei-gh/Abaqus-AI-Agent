"""Fail-closed audit for coating claims and contact-loading fidelity.

The audit does not choose a thickness, an indenter size, a friction value, or
a regulation clause. It only decides whether the current intent is allowed to
become a formal model and a formal report.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

from ..contracts.condition import (
    ContactLoadingSpec,
    SurfaceTreatmentSpec,
    mentions_coating,
    mentions_contact_loading,
    mentions_unverified_regulation,
    parse_contact_loadings,
    parse_surface_treatments,
)
from ..contracts.intent import EngineeringIntent


_POINT_LOADS = {"concentrated_force", "point_force", "cf", "concentrated"}
_FORMAL_FIGURE_KINDS = ("boundary_conditions", "contact_definition", "load_application")


def _load_type(load: Any) -> str:
    if isinstance(load, dict):
        return str(load.get("type") or load.get("load_type") or "").strip().lower()
    return str(getattr(load, "load_type", "") or getattr(load, "type", "")).strip().lower()


def _load_region(load: Any) -> str:
    if isinstance(load, dict):
        return str(load.get("region") or "")
    return str(getattr(load, "region", "") or "")


def _as_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "to_dict"):
        return item.to_dict()
    return {"value": str(item)}


def _intent_blob(intent: EngineeringIntent) -> str:
    metadata = intent.metadata or {}
    parts = [intent.description, intent.kind, intent.analysis_type, metadata.get("requirement")]
    for load in intent.loads or ():
        parts.append(_load_type(load))
        parts.append(_load_region(load))
        if isinstance(load, dict):
            parts.append(load.get("description"))
    return " ".join(str(part) for part in parts if part)


def _figure_kind(figure: Any) -> str:
    if isinstance(figure, dict):
        return str(figure.get("kind") or figure.get("visualization_type") or "").strip().lower()
    return str(getattr(figure, "kind", "") or getattr(figure, "visualization_type", "")).strip().lower()


def _figure_path(figure: Any) -> str:
    if isinstance(figure, dict):
        return str(figure.get("path") or "")
    return str(getattr(figure, "path", "") or "")


def audit_condition_fidelity(
    intent: Optional[EngineeringIntent] = None,
    *,
    description: str = "",
    loads: Sequence[Any] = (),
    contacts: Sequence[Any] = (),
    surface_treatments: Any = None,
    contact_loadings: Any = None,
    figures: Sequence[Any] = (),
    require_preprocessing_figures: bool = False,
) -> Dict[str, Any]:
    """Return a deterministic fidelity verdict. It never fills missing physics."""
    metadata = dict(getattr(intent, "metadata", None) or {})
    blob = " ".join(
        part for part in (
            description,
            getattr(intent, "description", ""),
            _intent_blob(intent) if intent is not None else "",
        ) if part
    )
    treatments = parse_surface_treatments(
        surface_treatments if surface_treatments is not None else metadata.get("surface_treatments")
    )
    loadings = parse_contact_loadings(
        contact_loadings if contact_loadings is not None else metadata.get("contact_loadings")
    )
    load_items = tuple(loads or (getattr(intent, "loads", ()) if intent is not None else ()))
    contact_items = tuple(contacts or (getattr(intent, "contacts", ()) if intent is not None else ()))

    blockers = []
    warnings = []
    if mentions_coating(blob) or treatments:
        if not treatments:
            blockers.append("coating_claim_without_surface_treatment_spec")
        for spec in treatments:
            blockers.extend(spec.gaps())
    if mentions_unverified_regulation(blob) and not any(item.regulation_verified for item in loadings):
        blockers.append("regulation_name_is_not_a_fixture_specification")

    point_loads = [item for item in load_items if _load_type(item) in _POINT_LOADS]
    contact_claimed = mentions_contact_loading(blob) or bool(loadings)
    if contact_claimed:
        if not loadings:
            blockers.append("contact_loading_claim_without_contact_loading_spec")
        else:
            for spec in loadings:
                blockers.extend(spec.gaps())
        if point_loads and not any(spec.authorizes_formal_model for spec in loadings):
            blockers.append("point_force_is_not_indenter_contact")
        if not contact_items and not any(spec.is_independent_contact and spec.authorizes_formal_model for spec in loadings):
            blockers.append("contact_loading_has_no_contact_definition")
    elif point_loads and not contact_items:
        warnings.append("point_force_has_no_contact_definition")

    figure_kinds = {_figure_kind(fig) for fig in figures if _figure_kind(fig) and _figure_path(fig)}
    missing_figures = tuple(kind for kind in _FORMAL_FIGURE_KINDS if kind not in figure_kinds)
    if require_preprocessing_figures and missing_figures:
        blockers.append("formal_report_missing_preprocessing_figures")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return {
        "passed": not unique_blockers,
        "formal_model_allowed": not unique_blockers,
        "formal_report_allowed": not unique_blockers and not (require_preprocessing_figures and missing_figures),
        "blockers": unique_blockers,
        "warnings": tuple(dict.fromkeys(warnings)),
        "missing_figures": missing_figures,
        "surface_treatments": tuple(spec.to_dict() for spec in treatments),
        "contact_loadings": tuple(spec.to_dict() for spec in loadings),
        "point_load_count": len(point_loads),
        "contact_count": len(contact_items),
    }


def required_formal_figure_kinds() -> Tuple[str, ...]:
    return _FORMAL_FIGURE_KINDS


def required_preprocessing_figure_kinds(
    *,
    boundary_evidence: Optional[Dict[str, Any]] = None,
    loads: Sequence[Any] = (),
    contacts: Sequence[Any] = (),
    bcs: Sequence[Any] = (),
    description: str = "",
    intent: Optional[EngineeringIntent] = None,
) -> Tuple[str, ...]:
    """Return only the preprocessing figures this model actually claims.

    A plain beam with no fixture, contact, or load record does not need those
    figures. A claimed fixture, contact, or load without its real figure cannot
    pass a formal report. Planned visualization specs are not evidence.
    """
    evidence = boundary_evidence or {}
    blob = " ".join(
        part for part in (
            description,
            getattr(intent, "description", "") if intent is not None else "",
        ) if part
    )
    required = []
    has_fixture = bool(evidence.get("bcs") or evidence.get("fixture") or bcs)
    has_contact = bool(evidence.get("contacts") or contacts or mentions_contact_loading(blob))
    has_load = bool(evidence.get("loads") or loads)
    if has_fixture:
        required.append("boundary_conditions")
    if has_contact:
        required.append("contact_definition")
    if has_load:
        required.append("load_application")
    return tuple(required)


def missing_preprocessing_figures(
    figures: Sequence[Any] = (),
    *,
    required: Sequence[str] = (),
) -> Tuple[str, ...]:
    present = set()
    for figure in figures or ():
        kind = _figure_kind(figure)
        path = _figure_path(figure)
        if kind and path:
            present.add(kind)
    return tuple(kind for kind in required if kind not in present)
