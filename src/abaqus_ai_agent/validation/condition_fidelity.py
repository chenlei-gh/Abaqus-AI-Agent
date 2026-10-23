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

# Words that ask for an interface to open, slide, or release. They are a request
# to examine the kinematics, not proof that the analysis must be Explicit.
_SEPARATION_TERMS = (
    "separation",
    "separate",
    "unclip",
    "snap-fit",
    "snap fit",
    "snapfit",
    "detent",
    "pull-out",
    "pull out",
    "pullout",
    "debond",
    "\u8131\u6263",
    "\u8131\u51fa",
    "\u5361\u6263",
    "\u5206\u79bb",
    "\u8131\u5f00",
)


def _contact_state(contact: Any) -> str:
    if isinstance(contact, dict):
        return str(contact.get("expected_state") or contact.get("state") or "").strip().lower()
    return str(getattr(contact, "expected_state", "") or "").strip().lower()


def _contact_expected_separation(contact: Any) -> Any:
    if isinstance(contact, dict):
        return contact.get("expected_separation")
    return getattr(contact, "expected_separation", None)


def _action_type(action: Any) -> str:
    if isinstance(action, dict):
        return str(action.get("action_type") or action.get("type") or "").strip().lower()
    return str(getattr(action, "action_type", "") or "").strip().lower()


def separation_required(
    intent: Optional[EngineeringIntent] = None,
    *,
    description: str = "",
    contacts: Sequence[Any] = (),
) -> bool:
    """Whether the engineering question needs an interface to open or slide.

    This is a requirement about the question, not about the solver. A model that
    constrains the interface cannot answer it, whether the solver is Standard or
    Explicit.
    """
    metadata = dict(getattr(intent, "metadata", None) or {})
    flags = (
        metadata.get("requires_separation"),
        metadata.get("separation_required"),
        (metadata.get("kinematic_requirement") or {}).get("separation")
        if isinstance(metadata.get("kinematic_requirement"), dict)
        else None,
    )
    if any(bool(flag) for flag in flags):
        return True
    blob = " ".join(
        str(part).lower()
        for part in (
            description,
            getattr(intent, "description", ""),
            _intent_blob(intent) if intent is not None else "",
        )
        if part
    )
    if any(term in blob for term in _SEPARATION_TERMS):
        return True
    for contact in tuple(contacts or (getattr(intent, "contacts", ()) if intent is not None else ())):
        if _contact_state(contact) == "open":
            return True
        if _contact_expected_separation(contact) is not None:
            return True
    return False


def _interaction_type(interaction: Any) -> str:
    if isinstance(interaction, dict):
        return str(interaction.get("interaction_type") or interaction.get("type") or "").strip().lower()
    return str(getattr(interaction, "interaction_type", "") or "").strip().lower()


def audit_interface_kinematics(
    intent: Optional[EngineeringIntent] = None,
    *,
    description: str = "",
    contacts: Sequence[Any] = (),
    plan_actions: Sequence[Any] = (),
    interactions: Sequence[Any] = (),
) -> Dict[str, Any]:
    """Check whether the plan can represent the interface behaviour it claims.

    Only one judgement is made, and it is deliberately narrow: when the question
    needs an interface to open or slide and the plan contains no separation-
    capable interaction at all, the model cannot answer that question. Tie makes
    the two sides permanently coincident, so a tie-only plan is INVALID for such
    a question. The blocker does not say the solve failed; it says the solve
    answers a different question.
    """
    actions = tuple(plan_actions or ())
    requires = separation_required(intent, description=description, contacts=contacts)
    action_types = tuple(_action_type(action) for action in actions)
    tie_count = action_types.count("tie")
    contact_count = action_types.count("contact")
    # Interaction specs are not always emitted as typed actions; a tie emitted as
    # a raw python action must still count as a tie here.
    for interaction in tuple(interactions or ()):
        kind = _interaction_type(interaction)
        if kind == "tie":
            tie_count += 1
        elif kind:
            contact_count += 1
    blockers = []
    warnings = []
    if requires and tie_count and not contact_count:
        blockers.append("interface_modelled_as_tie_not_contact")
    elif requires and tie_count and contact_count:
        warnings.append("tie_present_alongside_separation_contact_interface_unmapped")
    elif requires and actions and not tie_count and not contact_count:
        warnings.append("separation_required_without_any_interface_interaction")
    return {
        "separation_required": requires,
        "tie_count": tie_count,
        "contact_count": contact_count,
        "blockers": tuple(blockers),
        "warnings": tuple(warnings),
    }


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
    plan_actions: Sequence[Any] = (),
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

    kinematics = audit_interface_kinematics(
        intent,
        description=blob,
        contacts=contact_items,
        plan_actions=plan_actions,
    )
    blockers.extend(kinematics["blockers"])
    warnings.extend(kinematics["warnings"])

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
        "separation_required": kinematics["separation_required"],
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
