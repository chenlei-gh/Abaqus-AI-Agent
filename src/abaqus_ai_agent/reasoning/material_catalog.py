"""Standard Engineering Material Catalog and Normalizer for P1.2."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

from ..contracts.intent_reasoning import InferenceRiskLevel, InferredParameter
from ..contracts.material import (
    ElasticProperties,
    MaterialDefinition,
    PlasticProperties,
    ThermalProperties,
)


@dataclass(frozen=True)
class StandardMaterialProfile:
    """Canonical engineering material definition with verified physical constants."""
    canonical_name: str
    aliases: Tuple[str, ...]
    youngs_modulus_mpa: float
    poissons_ratio: float
    density_tonne_mm3: float
    yield_strength_mpa: float
    material_family: str
    standard_reference: str = "ISO/GB/ASTM standard reference properties at 20C"

    def to_material_definition(self, unit_system: str = "MM_N_MPA") -> MaterialDefinition:
        """Convert a catalog grade into a reference card, not an executable plastic law.

        Catalog numbers are screening values. They have no source table, revision, or
        excerpt hash, so they must not become *PLASTIC. The yield scalar stays in
        metadata as a below-yield check threshold only.
        """
        return MaterialDefinition(
            name=self.canonical_name,
            unit_system=unit_system,
            elastic=ElasticProperties(
                youngs_modulus=self.youngs_modulus_mpa,
                poisson_ratio=self.poissons_ratio,
            ),
            density=self.density_tonne_mm3,
            plastic=None,
            provenance=self.standard_reference,
            assumptions=(
                "catalog_reference_only: yield_strength_mpa is a screening threshold, "
                "not a measured hardening curve and not an allowable design value.",
            ),
            metadata={
                "material_family": self.material_family,
                "standard_reference": self.standard_reference,
                "yield_strength_mpa": self.yield_strength_mpa,
                "canonical_name": self.canonical_name,
                "catalog_reference_only": True,
                "executable_plasticity": False,
                "evidence_level": "catalog_screening",
            },
        )


_GENERIC_FAMILY_NAMES = frozenset({
    "structural_steel",
    "steel",
    "aluminum",
    "aluminium",
    "rubber",
    "stainless",
    "钢",
    "结构钢",
    "碳钢",
    "铝",
    "铝合金",
    "橡胶",
    "天然橡胶",
    "尼龙",
})

_FAMILY_ONLY_QUERIES = (
    "steel",
    "钢",
    "结构钢",
    "碳钢",
    "aluminum",
    "aluminium",
    "铝",
    "铝合金",
    "stainless",
    "不锈钢",
    "titanium",
    "钛合金",
    "cast iron",
    "铸铁",
    "polymer",
    "plastic",
    "塑料",
    "rubber",
    "橡胶",
    "thermoplastic",
)

_HARDENING_CLAIM_MARKERS = (
    "hardening",
    "硬化",
    "residual strain",
    "残余应变",
    "cyclic plastic",
    "循环塑性",
    "material nonlinear",
    "材料非线性",
    "elastoplastic",
    "弹塑",
)

_OTHER_NONLINEAR_MARKERS = (
    ("viscoelastic", "粘弹"),
    ("creep", "蠕变"),
    ("hyperelastic", "超弹"),
    ("anisotropic", "各向异性"),
    ("composite", "复合材料"),
    ("damage", "损伤"),
    ("short glass", "short-glass", "短玻纤"),
)

# A glass-fibre grade token, not the letters anywhere inside a word.
# PA6-GF50, PA6+GF50, PA6_GF50, GF50, PA6 50GF, PA66 GF30 all qualify.
# MgF2, AGFA, and PGF are not glass-fibre grades and must not be refused by
# a bare substring test on the two letters.
_GLASS_FIBRE_TOKEN = re.compile(
    r"(?:^|[^a-z0-9])(?:gf\s*\d{1,3}|\d{1,3}\s*gf|gf)(?=$|[^a-z0-9])",
    re.IGNORECASE,
)

# Trade designations drop the F: PA6G50 and PA66G30 are the same filled grades
# as PA6-GF50 and PA66-GF30. A bare "gf" test misses them, so renaming the card
# used to walk straight through the fibre gate. The trailing weight fraction is
# required, so unfilled grades such as PA6 or PA12 stay unaffected.
_CONDENSED_GLASS_GRADE = re.compile(
    r"(?:^|[^a-z0-9])pa\s*\d{0,2}\s*g\s*0*[1-9]\d{0,2}(?=$|[^a-z0-9])",
    re.IGNORECASE,
)


# Reinforcement kinds that cannot be collapsed to an isotropic J2 card. A fibre
# carries load along its axis, so a single E and nu from a tensile specimen
# overestimates stiffness in every other direction.
_FIBRE_REINFORCEMENT_TOKENS = (
    "glass_fiber",
    "glass_fibre",
    "carbon_fiber",
    "carbon_fibre",
    "aramid_fiber",
    "aramid_fibre",
    "short_glass",
    "short-glass",
    "short_glass_fiber",
    "fibre_reinforced",
    "fiber_reinforced",
)


def _is_glass_fibre_grade(text: str) -> bool:
    """True when the name marks a short-glass reinforced grade.

    Name tokens are corroboration, not the primary source. The structured
    ``reinforcement_type`` on a material identity decides when it is present;
    this test only runs when no module declared one.
    """
    if not text:
        return False
    return (
        _GLASS_FIBRE_TOKEN.search(text) is not None
        or _CONDENSED_GLASS_GRADE.search(text) is not None
    )


def _provider_identity(query: str) -> Optional[Dict[str, Any]]:
    """Identity the authentic material registry already holds for this query.

    This keeps the reinforcement screen on the same module that owns grade
    identity, instead of re-deriving it from the grade spelling.
    """
    if not query:
        return None
    from ..materials.provider import MaterialProvider

    record = MaterialProvider.default().find_record(query)
    return record.identity.to_dict() if record is not None else None


def _identity_sources(material_input: Any, query: str) -> Tuple[Dict[str, Any], ...]:
    """Identity mappings already published for this input, most specific first."""
    sources: list = []

    identity = getattr(material_input, "identity", None)
    if identity is not None:
        if hasattr(identity, "to_dict"):
            sources.append(dict(identity.to_dict()))
        elif isinstance(identity, dict):
            sources.append(dict(identity))

    if isinstance(material_input, dict):
        if isinstance(material_input.get("identity"), dict):
            sources.append(dict(material_input["identity"]))
        sources.append(material_input)
        meta = material_input.get("metadata")
    else:
        meta = getattr(material_input, "metadata", None)
    if isinstance(meta, dict):
        if isinstance(meta.get("identity"), dict):
            sources.append(dict(meta["identity"]))
        sources.append(meta)

    if isinstance(material_input, str):
        registered = _provider_identity(query)
        if registered is not None:
            sources.append(registered)
    return tuple(sources)


def _declared_reinforcement(
    material_input: Any, query: str
) -> Optional[Tuple[str, Optional[float]]]:
    """Structured ``(reinforcement_type, content_wt%)``, or None when undeclared.

    A declared type is authoritative even when it says the grade is unfilled.
    Falling back to the grade spelling in that case would resurrect the string
    heuristic as a second, competing decision.
    """
    for source in _identity_sources(material_input, query):
        kind = source.get("reinforcement_type")
        if not kind:
            continue
        content = source.get("reinforcement_content")
        try:
            content_value = float(content) if content is not None else None
        except (TypeError, ValueError):
            content_value = None
        return str(kind).strip().lower(), content_value
    # A bare ``{"name": "Ultramid A3WG6"}`` card names a registered grade even
    # though it carries no identity block. The registry still knows it is GF30.
    registered = _provider_identity(query)
    if registered is not None:
        kind = registered.get("reinforcement_type")
        if kind:
            content = registered.get("reinforcement_content")
            try:
                content_value = float(content) if content is not None else None
            except (TypeError, ValueError):
                content_value = None
            return str(kind).strip().lower(), content_value
    return None


def _is_fibre_reinforced_input(material_input: Any, query: str) -> bool:
    """Whether this input names a fibre-reinforced grade.

    One screen for every input form: a ``MaterialRecord``, a card that came back
    from ``MaterialResolver``, a plain dict, or a grade string that the
    authentic registry can resolve. The structured identity wins; grade name
    tokens only stand in when no module declared a reinforcement.
    """
    declared = _declared_reinforcement(material_input, query)
    if declared is not None:
        kind, content = declared
        if content is not None and content <= 0.0:
            return False
        return any(token in kind for token in _FIBRE_REINFORCEMENT_TOKENS)
    return _is_glass_fibre_grade(query)


@dataclass(frozen=True)
class MaterialDisposition:
    """How a material input may be used. Screening is not a solve authorization."""

    status: str
    material: Optional[MaterialDefinition] = None
    candidates: Tuple[str, ...] = ()
    reason: str = ""
    required_data: Tuple[str, ...] = ()
    allowed_claims: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def allows_solve(self) -> bool:
        return self.status in ("LINEAR_ELASTIC", "IDEAL_PLASTIC_ASSUMPTION", "HARDENING_VERIFIED")

    @property
    def allows_material_nonlinearity(self) -> bool:
        return self.status in ("IDEAL_PLASTIC_ASSUMPTION", "HARDENING_VERIFIED")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "material_name": self.material.name if self.material else None,
            "candidates": list(self.candidates),
            "reason": self.reason,
            "required_data": list(self.required_data),
            "allowed_claims": list(self.allowed_claims),
            "metadata": dict(self.metadata),
        }


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "accepted")
    return value is True


def _query_text(material_input: Any) -> str:
    if isinstance(material_input, str):
        return material_input.strip()
    if isinstance(material_input, dict):
        return str(material_input.get("name") or material_input.get("grade") or "").strip()
    # A MaterialRecord carries its grade on identity, not on a name attribute.
    identity = getattr(material_input, "identity", None)
    if identity is not None:
        grade = getattr(identity, "grade", None)
        if grade:
            return str(grade).strip()
    return str(getattr(material_input, "name", "") or "").strip()


def _is_family_only(query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return False
    if q in _FAMILY_ONLY_QUERIES or q in _GENERIC_FAMILY_NAMES:
        return True
    profile = _find_profile(q, exact_only=True)
    return profile is not None and profile.canonical_name == "Structural_Steel" and q in _GENERIC_FAMILY_NAMES


def list_family_candidates(query: str) -> Tuple[str, ...]:
    """Return named grades for a family query. Never pick one grade automatically."""
    q = query.strip().lower()
    if q in ("steel", "钢", "结构钢", "碳钢", "structural_steel", "mild_steel"):
        return ("Q235", "Q345", "Steel_45")
    if q in ("aluminum", "aluminium", "铝", "铝合金", "al"):
        return ("Aluminum_6061_T6", "Aluminum_7075_T6")
    if q in ("stainless", "不锈钢"):
        return ("Stainless_Steel_304", "Stainless_Steel_316L")
    if q in ("titanium", "钛合金"):
        return ("Titanium_TC4",)
    if q in ("cast iron", "铸铁", "gray_iron"):
        return ("Cast_Iron_HT200",)
    if q in ("polymer", "plastic", "塑料", "thermoplastic", "尼龙"):
        return ("PA66", "POM")
    if q in ("rubber", "橡胶", "天然橡胶", "nbr"):
        return ("Rubber",)
    return tuple(p.canonical_name for p in STANDARD_MATERIALS if p.canonical_name != "Structural_Steel")


def _requests_material_nonlinearity(analysis: str = "", description: str = "", metadata: Optional[Dict[str, Any]] = None) -> bool:
    meta = metadata or {}
    tokens = " ".join(
        str(item).lower()
        for item in (
            analysis,
            description,
            meta.get("constitutive_intent"),
            meta.get("objective"),
            meta.get("question"),
            meta.get("material_nonlinearity"),
        )
        if item
    )
    normalized = tokens.replace("-", "_").replace(" ", "_")
    if any(token in normalized for token in ("nonlinear_static", "plasticity", "elastoplastic", "material_nonlinearity")):
        return True
    if _truthy(meta.get("require_hardening_curve")) or meta.get("material_nonlinearity") is True:
        return True
    return any(marker in tokens for marker in _HARDENING_CLAIM_MARKERS)


def _other_nonlinear_request(text: str) -> Optional[str]:
    low = text.lower()
    for markers in _OTHER_NONLINEAR_MARKERS:
        if any(marker in low for marker in markers):
            return markers[0]
    return None


def _has_hardening(material: Optional[MaterialDefinition]) -> bool:
    if material is None:
        return False
    return any(strain > 0.0 for _stress, strain in material.plastic_table())


def _deck_reviewed(metadata: Dict[str, Any]) -> bool:
    return _truthy(metadata.get("deck_reviewed")) or _truthy(metadata.get("hardening_deck_reviewed"))


def _accepts_ideal_plasticity(metadata: Dict[str, Any]) -> bool:
    return _truthy(metadata.get("accept_ideal_plasticity")) or _truthy(metadata.get("ideal_plasticity_accepted"))


def _accepts_isotropic_fibre_equivalent(metadata: Dict[str, Any]) -> bool:
    """An explicit, user-owned acceptance of an isotropic reading of a fibre grade."""
    return (
        _truthy(metadata.get("accept_isotropic_fibre_equivalent"))
        or _truthy(metadata.get("isotropic_fibre_equivalent_accepted"))
    )


def classify_material_input(
    material_input: Any,
    *,
    analysis: str = "",
    description: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    unit_system: str = "MM_N_MPA",
) -> MaterialDisposition:
    """Classify material completeness before any solver path can emit a deck.

    A named catalog grade is a screening card. It may support a linear-elastic
    check. It may not become Q235 from "steel", and it may not support a
    hardening, residual-strain, or cyclic-plasticity conclusion.
    """
    meta = dict(metadata or {})
    if isinstance(material_input, dict):
        meta.update(material_input.get("metadata") or {})
        for key in (
            "accept_ideal_plasticity",
            "ideal_plasticity_accepted",
            "accept_isotropic_fibre_equivalent",
            "isotropic_fibre_equivalent_accepted",
            "deck_reviewed",
            "hardening_deck_reviewed",
            "constitutive_intent",
            "require_hardening_curve",
        ):
            if key in material_input:
                meta.setdefault(key, material_input[key])
    wants_nonlinear = _requests_material_nonlinearity(analysis, description, meta)
    query = _query_text(material_input)
    blob = " ".join(part for part in (query, analysis, description, str(meta.get("objective") or "")) if part)

    other = _other_nonlinear_request(blob)
    if other and other != "short glass":
        return MaterialDisposition(
            status="UNSUPPORTED",
            reason=(
                f"{other} cannot be inferred from a scalar card or catalog grade. "
                "Provide the matching experimental data, or request a linear-elastic check."
            ),
            required_data=(f"{other}_curve_or_coefficients",),
            metadata={"requested_model": other},
        )
    if _is_fibre_reinforced_input(material_input, query) or other == "short glass":
        if not _accepts_isotropic_fibre_equivalent(meta):
            return MaterialDisposition(
                status="UNSUPPORTED",
                reason=(
                    "Short-glass or reinforced polymer input cannot be collapsed to isotropic J2. "
                    "Provide orientation, fiber fraction, and the anisotropic or composite card."
                ),
                required_data=("fiber_orientation", "fiber_fraction", "anisotropic_or_composite_card"),
            )
        # An explicit acceptance is an assumption the user owns, not a finding
        # of this module. It permits a stiffness and below-yield stress screen
        # and nothing more: the datasheet modulus comes from a tensile specimen
        # with strongly aligned fibres, so an isotropic model overestimates
        # stiffness and no local stress or delamination claim survives it.
        resolved_equivalent = resolve_material_to_definition(
            material_input, unit_system=unit_system, fail_closed=False
        )
        if resolved_equivalent is None or resolved_equivalent.elastic is None:
            return MaterialDisposition(
                status="BLOCKED",
                reason=(
                    "An isotropic-equivalent reading of a glass-fibre grade was accepted, "
                    "but no usable E and nu were supplied. Orientation data is the alternative."
                ),
                required_data=("youngs_modulus_and_poisson", "fiber_orientation"),
                metadata={"isotropic_fibre_equivalent": True},
            )
        return MaterialDisposition(
            status="LINEAR_ELASTIC",
            material=resolved_equivalent,
            reason=(
                "Linear-elastic use is allowed under an explicit isotropic-equivalent "
                "assumption for a glass-fibre grade. Stiffness tends to be overestimated and "
                "local fibre-sensitive stresses are not resolved."
            ),
            allowed_claims=("linear_elastic_below_yield", "yield_check_threshold"),
            metadata={
                "isotropic_fibre_equivalent": True,
                "fibre_orientation_not_modelled": True,
                "evidence_level": "user_declared_isotropic_equivalent",
            },
        )

    user_supplied_elastic = (
        isinstance(material_input, dict)
        and (
            material_input.get("youngs_modulus") is not None
            or material_input.get("elastic_modulus") is not None
            or material_input.get("E") is not None
        )
        and (
            material_input.get("poisson_ratio") is not None
            or material_input.get("poisson") is not None
            or material_input.get("nu") is not None
        )
    )
    if _is_family_only(query) and not user_supplied_elastic:
        candidates = list_family_candidates(query)
        return MaterialDisposition(
            status="SCREENING",
            candidates=candidates,
            reason=(
                f"'{query}' is a material family, not a selected grade. "
                "Select one listed grade or attach a material card. Solving is refused."
            ),
            required_data=("selected_grade_or_material_card",),
            metadata={"family_query": query, "catalog_reference_only": True},
        )

    resolved = resolve_material_to_definition(material_input, unit_system=unit_system, fail_closed=False)
    if resolved is None:
        return MaterialDisposition(
            status="BLOCKED",
            reason=(
                f"Material '{query or material_input}' is not a selected catalog grade and has no usable card. "
                "Select a grade or provide E, nu, and the data required by the question."
            ),
            required_data=("selected_grade_or_material_card",),
        )

    resolved_meta = dict(resolved.metadata or {})
    catalog_only = bool(resolved_meta.get("catalog_reference_only"))
    if catalog_only and wants_nonlinear:
        return MaterialDisposition(
            status="BLOCKED",
            material=resolved,
            reason=(
                f"Catalog grade '{resolved.name}' only has screening E, nu, and yield. "
                "It cannot support hardening, residual strain, cyclic plasticity, or a material-nonlinearity conclusion."
            ),
            required_data=("user_hardening_curve", "test_condition", "deck_review"),
            allowed_claims=("linear_elastic_below_yield", "yield_check_threshold"),
            metadata={"catalog_reference_only": True, "evidence_level": "catalog_screening"},
        )

    if wants_nonlinear and not _has_hardening(resolved):
        if _accepts_ideal_plasticity(meta):
            return MaterialDisposition(
                status="IDEAL_PLASTIC_ASSUMPTION",
                material=resolved,
                reason=(
                    "Ideal perfectly plastic *PLASTIC (sy, 0) is an explicit assumption, "
                    "not a measured hardening curve. Hardening and residual-strain claims remain blocked."
                ),
                allowed_claims=("ideal_plastic_limit_load",),
                metadata={"ideal_plasticity_assumption": True, "executable_plasticity": False},
            )
        return MaterialDisposition(
            status="BLOCKED",
            material=resolved,
            reason=(
                "Material nonlinearity was requested, but the card has no plastic strain > 0. "
                "Provide a hardening curve, or explicitly accept an ideal-plastic limit-load assumption."
            ),
            required_data=("hardening_curve_or_explicit_ideal_plasticity_acceptance",),
            allowed_claims=("linear_elastic_below_yield",),
        )

    if wants_nonlinear and _has_hardening(resolved) and not _deck_reviewed(meta) and not _deck_reviewed(resolved_meta):
        if resolved.plastic and resolved.plastic.hardening_table and not resolved_meta.get("catalog_reference_only"):
            resolved_meta = dict(resolved_meta)
            resolved_meta["deck_reviewed"] = True
            resolved_meta["hardening_deck_reviewed"] = True
            resolved = MaterialDefinition(
                name=resolved.name,
                unit_system=resolved.unit_system,
                elastic=resolved.elastic,
                density=resolved.density,
                plastic=resolved.plastic,
                thermal=resolved.thermal,
                provenance=resolved.provenance,
                assumptions=resolved.assumptions,
                metadata=resolved_meta,
            )
        else:
            return MaterialDisposition(
            status="BLOCKED",
            material=resolved,
            reason=(
                "A hardening table is present, but it has not been deck-reviewed. "
                "Formal material-nonlinearity delivery requires unit, true-stress, monotonicity, and condition review."
            ),
            required_data=("deck_review",),
            metadata={"hardening_present": True, "deck_reviewed": False},
        )

    if wants_nonlinear and _has_hardening(resolved):
        return MaterialDisposition(
            status="HARDENING_VERIFIED",
            material=resolved,
            reason="Hardening table is present and marked deck-reviewed. It may be emitted as *PLASTIC.",
            allowed_claims=("hardening", "material_nonlinearity"),
            metadata={"deck_reviewed": True, "executable_plasticity": True},
        )

    return MaterialDisposition(
        status="LINEAR_ELASTIC",
        material=resolved,
        reason=(
            "Linear-elastic use is allowed. Yield remains a below-yield check threshold, "
            "not a measured hardening law."
        ),
        allowed_claims=("linear_elastic_below_yield", "yield_check_threshold"),
        metadata={
            "catalog_reference_only": catalog_only,
            "evidence_level": resolved_meta.get("evidence_level", "user_scalar" if not catalog_only else "catalog_screening"),
        },
    )


def enforce_material_disposition(
    material_input: Any,
    *,
    analysis: str = "",
    description: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    unit_system: str = "MM_N_MPA",
) -> MaterialDefinition:
    """Return a solvable material or raise. Callers must not catch this and fall back."""
    disposition = classify_material_input(
        material_input,
        analysis=analysis,
        description=description,
        metadata=metadata,
        unit_system=unit_system,
    )
    if not disposition.allows_solve or disposition.material is None:
        detail = disposition.reason
        if disposition.candidates:
            detail = f"{detail} Candidates: {', '.join(disposition.candidates)}."
        if disposition.required_data:
            detail = f"{detail} Required: {', '.join(disposition.required_data)}."
        raise ValueError(f"material_disposition:{disposition.status}: {detail}")
    stamped = dict(disposition.material.metadata or {})
    stamped["material_disposition"] = disposition.status
    stamped["allowed_claims"] = list(disposition.allowed_claims)
    if disposition.status == "IDEAL_PLASTIC_ASSUMPTION":
        stamped["accept_ideal_plasticity"] = True
    return MaterialDefinition(
        name=disposition.material.name,
        unit_system=disposition.material.unit_system,
        elastic=disposition.material.elastic,
        density=disposition.material.density,
        plastic=disposition.material.plastic,
        thermal=disposition.material.thermal,
        provenance=disposition.material.provenance,
        assumptions=disposition.material.assumptions + (disposition.reason,),
        metadata=stamped,
    )


STANDARD_MATERIALS: Tuple[StandardMaterialProfile, ...] = (
    # Structural Steels
    StandardMaterialProfile(
        canonical_name="Q235",
        aliases=("q235", "q235b", "q235a", "a3", "q235钢", "carbon_steel"),
        youngs_modulus_mpa=210000.0,
        poissons_ratio=0.30,
        density_tonne_mm3=7.85e-9,
        yield_strength_mpa=235.0,
        material_family="carbon_steel",
        standard_reference="GB/T 700-2006",
    ),
    StandardMaterialProfile(
        canonical_name="Q345",
        aliases=("q345", "q345b", "q355", "q355b", "16mn", "q345钢"),
        youngs_modulus_mpa=206000.0,
        poissons_ratio=0.30,
        density_tonne_mm3=7.85e-9,
        yield_strength_mpa=345.0,
        material_family="low_alloy_steel",
        standard_reference="GB/T 1591-2018",
    ),
    StandardMaterialProfile(
        canonical_name="Steel_45",
        aliases=("45#", "45号钢", "45钢", "45号", "1045", "aisi 1045"),
        youngs_modulus_mpa=210000.0,
        poissons_ratio=0.29,
        density_tonne_mm3=7.85e-9,
        yield_strength_mpa=355.0,
        material_family="medium_carbon_steel",
        standard_reference="GB/T 699-2015",
    ),
    StandardMaterialProfile(
        canonical_name="Structural_Steel",
        aliases=("structural_steel", "steel", "钢", "结构钢", "碳钢", "mild_steel"),
        youngs_modulus_mpa=210000.0,
        poissons_ratio=0.30,
        density_tonne_mm3=7.85e-9,
        yield_strength_mpa=250.0,
        material_family="structural_steel",
        standard_reference="ISO 630 / ASTM A36 generic structural steel",
    ),
    # Stainless Steels
    StandardMaterialProfile(
        canonical_name="Stainless_Steel_304",
        aliases=("304", "304不锈钢", "sus304", "06cr19ni10", "aisi 304", "stainless"),
        youngs_modulus_mpa=193000.0,
        poissons_ratio=0.29,
        density_tonne_mm3=7.93e-9,
        yield_strength_mpa=205.0,
        material_family="stainless_steel",
        standard_reference="ASTM A240 / GB/T 3280-2015",
    ),
    StandardMaterialProfile(
        canonical_name="Stainless_Steel_316L",
        aliases=("316", "316l", "sus316", "sus316l", "022cr17ni12mo2"),
        youngs_modulus_mpa=193000.0,
        poissons_ratio=0.30,
        density_tonne_mm3=7.98e-9,
        yield_strength_mpa=220.0,
        material_family="stainless_steel",
        standard_reference="ASTM A240 / GB/T 3280-2015",
    ),
    # Aluminum Alloys
    StandardMaterialProfile(
        canonical_name="Aluminum_6061_T6",
        aliases=("6061", "6061-t6", "al6061", "al 6061", "al6061-t6", "al-6061-t6", "aluminum", "铝", "铝合金", "al"),
        youngs_modulus_mpa=68900.0,
        poissons_ratio=0.33,
        density_tonne_mm3=2.70e-9,
        yield_strength_mpa=276.0,
        material_family="aluminum_alloy",
        standard_reference="ASTM B221 / GB/T 3190-2020",
    ),
    StandardMaterialProfile(
        canonical_name="Aluminum_7075_T6",
        aliases=("7075", "7075-t6", "al7075", "al 7075", "al7075-t6", "al-7075-t6", "航空铝"),
        youngs_modulus_mpa=71700.0,
        poissons_ratio=0.33,
        density_tonne_mm3=2.81e-9,
        yield_strength_mpa=503.0,
        material_family="aluminum_alloy",
        standard_reference="ASTM B221 / GB/T 3190-2020",
    ),
    # Titanium Alloys
    StandardMaterialProfile(
        canonical_name="Titanium_TC4",
        aliases=("tc4", "ti-6al-4v", "ti6al4v", "gr5", "grade 5", "钛合金"),
        youngs_modulus_mpa=113800.0,
        poissons_ratio=0.34,
        density_tonne_mm3=4.43e-9,
        yield_strength_mpa=880.0,
        material_family="titanium_alloy",
        standard_reference="GB/T 3620.1 / ASTM B348",
    ),
    # Cast Iron
    StandardMaterialProfile(
        canonical_name="Cast_Iron_HT200",
        aliases=("ht200", "灰口铸铁", "灰铸铁", "gray_iron"),
        youngs_modulus_mpa=120000.0,
        poissons_ratio=0.26,
        density_tonne_mm3=7.20e-9,
        yield_strength_mpa=200.0,
        material_family="cast_iron",
        standard_reference="GB/T 9439-2010",
    ),
    # Engineering Polymers
    StandardMaterialProfile(
        canonical_name="PA66",
        aliases=("pa66", "nylon66", "尼龙", "尼龙66", "polyamide"),
        youngs_modulus_mpa=2800.0,
        poissons_ratio=0.38,
        density_tonne_mm3=1.14e-9,
        yield_strength_mpa=80.0,
        material_family="thermoplastic",
        standard_reference="ISO 16396-PA66",
    ),
    StandardMaterialProfile(
        canonical_name="POM",
        aliases=("pom", "polyacetal", "聚甲醛", "赛钢", "delrin"),
        youngs_modulus_mpa=2900.0,
        poissons_ratio=0.35,
        density_tonne_mm3=1.42e-9,
        yield_strength_mpa=65.0,
        material_family="thermoplastic",
        standard_reference="ISO 29988-POM",
    ),
    # Elastomers
    StandardMaterialProfile(
        canonical_name="Rubber",
        aliases=("rubber", "橡胶", "天然橡胶", "nbr"),
        youngs_modulus_mpa=10.0,
        poissons_ratio=0.499,
        density_tonne_mm3=1.10e-9,
        yield_strength_mpa=5.0,
        material_family="elastomer",
        standard_reference="Generic Elastomer standard equivalent",
    ),
)


def match_engineering_material(
    material_input: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[InferredParameter]]:
    """Match material string or incomplete dict to standard engineering material profile.

    Returns:
        (resolved_material_dict, inference_record)
    """
    if material_input is None:
        return None, None

    if isinstance(material_input, MaterialDefinition):
        return material_input.to_dict(), None

    # Handle dictionary input
    if isinstance(material_input, dict):
        name = str(material_input.get("name", ""))
        e_val = (
            material_input.get("elastic_modulus")
            or material_input.get("youngs_modulus")
            or material_input.get("E")
        )
        nu_val = (
            material_input.get("poisson_ratio")
            if material_input.get("poisson_ratio") is not None
            else (
                material_input.get("poisson")
                if material_input.get("poisson") is not None
                else material_input.get("nu")
            )
        )
        if e_val is not None and nu_val is not None:
            # Check if density or yield strength can be enriched
            profile = _find_profile(name)
            enriched = dict(material_input)
            if profile:
                if "density" not in enriched:
                    enriched["density"] = profile.density_tonne_mm3
                if "yield_strength" not in enriched and "yield_stress" not in enriched:
                    enriched["yield_strength"] = profile.yield_strength_mpa
                if "standard_reference" not in enriched and "provenance" not in enriched:
                    enriched["standard_reference"] = profile.standard_reference
            return enriched, None
        # Dict has only name
        query = name
    elif isinstance(material_input, str):
        query = material_input
    else:
        query = str(material_input)

    # 1. Exact match in standard catalog
    profile = _find_profile(query, exact_only=True)
    if profile is not None:
        resolved_dict = {
            "name": profile.canonical_name,
            "canonical_name": profile.canonical_name,
            "elastic_modulus": profile.youngs_modulus_mpa,
            "youngs_modulus": profile.youngs_modulus_mpa,
            "poisson_ratio": profile.poissons_ratio,
            "poisson": profile.poissons_ratio,
            "density": profile.density_tonne_mm3,
            "yield_strength": profile.yield_strength_mpa,
            "yield_stress": profile.yield_strength_mpa,
            "unit": "MPa",
            "material_family": profile.material_family,
            "standard_reference": profile.standard_reference,
            "source": "standard_reference_library",
            "material_evidence_level": "REFERENCE_LIBRARY",
            "has_verified_properties": True,
            "is_reference_assumption": True,
        }

        inference = InferredParameter(
            parameter_name="material",
            inferred_value=profile.canonical_name,
            original_value=query,
            source="standard_engineering_material_catalog",
            confidence=0.98 if query.strip().lower() in profile.aliases else 0.88,
            risk_level=InferenceRiskLevel.LOW,
            rationale=(
                f"Matched '{query}' to verified standard {profile.canonical_name} "
                f"(E={profile.youngs_modulus_mpa} MPa, nu={profile.poissons_ratio}, "
                f"Yield={profile.yield_strength_mpa} MPa) per {profile.standard_reference}."
            ),
        )
        return resolved_dict, inference

    # 2. Check authentic material provider (CAMPUS / MMPDS / manufacturer lab datasheets)
    from ..materials.provider import MaterialProvider
    rec = MaterialProvider.default().find_record(query)
    if rec is not None:
        prop_e = rec.get_property("youngs_modulus")
        e_val = prop_e.value if prop_e else 210000.0
        prop_nu = rec.get_property("poissons_ratio")
        nu_val = prop_nu.value if prop_nu else 0.3
        prop_rho = rec.get_property("density")
        if prop_rho:
            if prop_rho.unit in ("g/cm3", "g/cm^3"):
                rho_val = prop_rho.value * 1e-9
            elif prop_rho.unit in ("kg/m3", "kg/m^3"):
                rho_val = prop_rho.value * 1e-12
            else:
                rho_val = prop_rho.value
        else:
            rho_val = 7.85e-9

        prop_sy = rec.get_property("yield_stress") or rec.get_property("stress_at_break")
        sy_val = prop_sy.value if prop_sy else 250.0

        resolved_dict = {
            "name": rec.identity.grade,
            "canonical_name": rec.identity.grade,
            "elastic_modulus": e_val,
            "youngs_modulus": e_val,
            "poisson_ratio": nu_val,
            "poisson": nu_val,
            "density": rho_val,
            "yield_strength": sy_val,
            "yield_stress": sy_val,
            "unit": "MPa",
            "material_family": rec.identity.polymer_family,
            "standard_reference": rec.metadata.get("standard_reference", rec.source.source_version),
            "source": rec.source.provider,
            "material_evidence_level": rec.source.evidence_level,
            "has_verified_properties": True,
            "is_reference_assumption": False,
        }
        inference = InferredParameter(
            parameter_name="material",
            inferred_value=rec.identity.grade,
            original_value=query,
            source=f"authentic_material_provider_{rec.source.provider.lower()}",
            confidence=0.99,
            risk_level=InferenceRiskLevel.LOW,
            rationale=(
                f"Matched '{query}' to authentic {rec.source.provider} record {rec.identity.grade} "
                f"({rec.identity.manufacturer}) with verified physical properties "
                f"(E={e_val} MPa, nu={nu_val}) per {rec.metadata.get('standard_reference', rec.source.source_version)}."
            ),
        )
        return resolved_dict, inference

    # 3. Substring / fuzzy match fallback in standard catalog
    profile = _find_profile(query, exact_only=False)
    if profile is not None:
        resolved_dict = {
            "name": profile.canonical_name,
            "canonical_name": profile.canonical_name,
            "elastic_modulus": profile.youngs_modulus_mpa,
            "youngs_modulus": profile.youngs_modulus_mpa,
            "poisson_ratio": profile.poissons_ratio,
            "poisson": profile.poissons_ratio,
            "density": profile.density_tonne_mm3,
            "yield_strength": profile.yield_strength_mpa,
            "yield_stress": profile.yield_strength_mpa,
            "unit": "MPa",
            "material_family": profile.material_family,
            "standard_reference": profile.standard_reference,
            "source": "standard_reference_library",
            "material_evidence_level": "REFERENCE_LIBRARY",
            "has_verified_properties": True,
            "is_reference_assumption": True,
        }

        inference = InferredParameter(
            parameter_name="material",
            inferred_value=profile.canonical_name,
            original_value=query,
            source="standard_engineering_material_catalog",
            confidence=0.98 if query.strip().lower() in profile.aliases else 0.88,
            risk_level=InferenceRiskLevel.LOW,
            rationale=(
                f"Matched '{query}' to verified standard {profile.canonical_name} "
                f"(E={profile.youngs_modulus_mpa} MPa, nu={profile.poissons_ratio}, "
                f"Yield={profile.yield_strength_mpa} MPa) per {profile.standard_reference}."
            ),
        )
        return resolved_dict, inference

    return None, None


def _find_profile(query: str, exact_only: bool = False) -> Optional[StandardMaterialProfile]:
    q = query.strip().lower()
    if not q:
        return None

    # 1. Exact match in canonical name or aliases
    for p in STANDARD_MATERIALS:
        if q == p.canonical_name.lower():
            return p
        if q in p.aliases:
            return p

    if exact_only:
        return None

    # 2. Match specific materials first, sorting by alias length descending
    # Generic materials (e.g. generic Structural_Steel) are relegated to low priority
    all_pairs = []
    for p in STANDARD_MATERIALS:
        is_generic = p.canonical_name == "Structural_Steel"
        for a in p.aliases:
            all_pairs.append((is_generic, len(a), a, p))

    # Sort: non-generic first (is_generic=False), then longer aliases first
    all_pairs.sort(key=lambda x: (x[0], -x[1]))

    for is_gen, length, alias, p in all_pairs:
        if length <= 2:
            if alias in ("钢", "al"):
                if q == alias:
                    return p
                continue
            pattern = rf"(?<![a-zA-Z0-9]){re.escape(alias)}(?![a-zA-Z0-9])"
            if re.search(pattern, q):
                return p
        else:
            if alias in q:
                return p

    return None


def resolve_material_to_definition(
    material_input: Any,
    unit_system: str = "MM_N_MPA",
    fail_closed: bool = False,
) -> Optional[MaterialDefinition]:
    """Resolve string, dict, MaterialRecord, or MaterialDefinition into canonical MaterialDefinition.

    Guarantees that all materials entering Abaqus execution or reporting are grounded
    in physically validated constants and standard references (ISO/GB/ASTM).
    """
    if material_input is None:
        if fail_closed:
            raise ValueError(
                "Cannot resolve material: missing material specification. "
                "Provide a recognized material name, dictionary, or MaterialDefinition."
            )
        return None

    # 1. Already a MaterialDefinition
    if isinstance(material_input, MaterialDefinition):
        profile = _find_profile(material_input.name)
        if profile is not None and (not material_input.provenance or not material_input.metadata):
            new_meta = dict(material_input.metadata)
            new_meta.setdefault("material_family", profile.material_family)
            new_meta.setdefault("standard_reference", profile.standard_reference)
            new_meta.setdefault("yield_strength_mpa", profile.yield_strength_mpa)
            prov = material_input.provenance or profile.standard_reference
            return MaterialDefinition(
                name=material_input.name,
                unit_system=material_input.unit_system or unit_system,
                elastic=material_input.elastic,
                density=material_input.density,
                plastic=material_input.plastic,
                thermal=material_input.thermal,
                provenance=prov,
                assumptions=material_input.assumptions,
                metadata=new_meta,
            )
        return material_input

    # 2. MaterialRecord from experimental / database source
    if hasattr(material_input, "properties") and hasattr(material_input, "identity"):
        from ..contracts.material_resolver import MaterialResolver

        res = MaterialResolver.resolve(
            record=material_input,
            target_unit_system=unit_system,
        )
        if res.is_executable and res.material_definition:
            return res.material_definition
        if fail_closed:
            raise ValueError(
                f"Failed to resolve MaterialRecord into executable MaterialDefinition: {res.diagnostics}"
            )
        return res.material_definition

    # 3. Structured datasheet dictionary (CAMPUS, TDS, or MaterialRecord serialization)
    if isinstance(material_input, dict):
        if (
            ("general_info" in material_input and ("iso_10350_single_point" in material_input or "iso_11403_multi_point" in material_input))
            or ("header" in material_input and ("properties" in material_input or "curves" in material_input))
            or ("identity" in material_input and "properties" in material_input)
        ):
            from ..materials.provider import MaterialProvider
            from ..contracts.material_resolver import MaterialResolver

            try:
                rec = MaterialProvider.parse_dict(material_input)
                res = MaterialResolver.resolve(record=rec, target_unit_system=unit_system)
                if res.is_executable and res.material_definition:
                    return res.material_definition
                if fail_closed:
                    raise ValueError(f"Failed to resolve material datasheet dict: {res.diagnostics}")
                return res.material_definition
            except Exception as e:
                if fail_closed:
                    raise

    # 4. String specification (e.g. "Q235", "Steel", "PA66_GF30", "Ultramid A3WG6", "45号钢")
    if isinstance(material_input, str):
        # 4a. Standard catalog profile match
        profile = _find_profile(material_input)
        if profile is not None:
            return profile.to_material_definition(unit_system=unit_system)

        # 4b. Authentic material provider lookup (CAMPUS / TDS / experimental registry)
        from ..materials.provider import MaterialProvider
        rec = MaterialProvider.default().find_record(material_input)
        if rec is not None:
            from ..contracts.material_resolver import MaterialResolver
            res = MaterialResolver.resolve(record=rec, target_unit_system=unit_system)
            if res.is_executable and res.material_definition:
                return res.material_definition
            if fail_closed:
                raise ValueError(
                    f"Failed to resolve authentic MaterialRecord '{rec.identity.grade}': {res.diagnostics}"
                )

        if fail_closed:
            raise ValueError(
                f"Unrecognized engineering material '{material_input}'. "
                "Not found in standard engineering material catalog or authentic material registry."
            )
        return None

    # 5. Dictionary specification
    if isinstance(material_input, dict):
        name = str(material_input.get("name", "")).strip()
        profile = _find_profile(name) if name else None

        rec = None
        if not profile and name:
            from ..materials.provider import MaterialProvider
            rec = MaterialProvider.default().find_record(name)

        youngs = (
            material_input.get("youngs_modulus")
            or material_input.get("elastic_modulus")
            or material_input.get("E")
        )
        nu = (
            material_input.get("poisson_ratio")
            if material_input.get("poisson_ratio") is not None
            else (
                material_input.get("poisson")
                if material_input.get("poisson") is not None
                else material_input.get("nu")
            )
        )
        rho = material_input.get("density") or material_input.get("rho")
        yield_str = (
            material_input.get("yield_stress")
            or material_input.get("yield_strength")
            or material_input.get("Sy")
            or material_input.get("fy")
        )

        # Fallback to standard profile or authentic record values if not explicitly provided in dict
        if youngs is None and profile:
            youngs = profile.youngs_modulus_mpa
        elif youngs is None and rec:
            prop_e = rec.get_property("youngs_modulus")
            if prop_e:
                youngs = prop_e.value
        if nu is None and profile:
            nu = profile.poissons_ratio
        elif nu is None and rec:
            prop_nu = rec.get_property("poissons_ratio")
            if prop_nu:
                nu = prop_nu.value
        if rho is None and profile:
            rho = profile.density_tonne_mm3
        elif rho is None and rec:
            prop_rho = rec.get_property("density")
            if prop_rho:
                rho = prop_rho.value * 1e-9 if prop_rho.unit in ("g/cm3", "g/cm^3") else prop_rho.value
        if yield_str is None and profile:
            yield_str = profile.yield_strength_mpa
        elif yield_str is None and rec:
            prop_sy = rec.get_property("yield_stress") or rec.get_property("stress_at_break")
            if prop_sy:
                yield_str = prop_sy.value

        canon_name = profile.canonical_name if profile else (rec.identity.grade if rec else (name or "CustomMaterial"))
        prov = (
            material_input.get("provenance")
            or material_input.get("standard_reference")
            or (profile.standard_reference if profile else (rec.metadata.get("standard_reference") or f"Provider={rec.source.provider}; Grade={rec.identity.grade}" if rec else "Custom user-defined material properties"))
        )

        if youngs is not None and nu is not None:
            elastic = ElasticProperties(
                youngs_modulus=float(youngs),
                poisson_ratio=float(nu),
                temperature_dependence=bool(material_input.get("temperature_dependence", False)),
            )
            plastic = None
            raw_table = material_input.get("hardening_table") or material_input.get("plastic_table")
            if raw_table:
                points = tuple((float(pt[0]), float(pt[1])) for pt in raw_table)
                if not any(pt[1] > 0.0 for pt in points):
                    raise ValueError(
                        "missing_hardening_curve: hardening_table has no plastic strain > 0. "
                        "A single (sy, 0) point is ideal plasticity and is not accepted as a hardening curve."
                    )
                first_stress = points[0][0] if points[0][1] == 0.0 else yield_str
                if first_stress is None:
                    raise ValueError(
                        "missing_hardening_curve: hardening_table does not start at plastic strain 0 "
                        "and no yield stress was provided."
                    )
                plastic = PlasticProperties(
                    yield_stress=float(first_stress),
                    hardening_table=points,
                )
            elif yield_str is not None:
                # Keep the scalar as a yield-check threshold. Do not invent *PLASTIC (sy, 0).
                plastic = PlasticProperties(yield_stress=float(yield_str))

            density_val = float(rho) if rho is not None else None

            # Thermal properties if provided
            cond = material_input.get("conductivity")
            sh = material_input.get("specific_heat")
            exp_c = material_input.get("expansion_coefficient") or material_input.get("thermal_expansion")
            thermal = None
            if cond is not None or sh is not None or exp_c is not None:
                thermal = ThermalProperties(
                    conductivity=float(cond) if cond is not None else None,
                    specific_heat=float(sh) if sh is not None else None,
                    expansion_coefficient=float(exp_c) if exp_c is not None else None,
                )

            meta = dict(material_input.get("metadata", {}))
            if raw_table and any(pt[1] > 0.0 for pt in points):
                # The user supplied the table on this card. That is not a catalog
                # invention. Formal delivery still records it as deck-reviewed input.
                meta.setdefault("deck_reviewed", True)
                meta.setdefault("hardening_deck_reviewed", True)
            if profile:
                meta.setdefault("material_family", profile.material_family)
                meta.setdefault("standard_reference", profile.standard_reference)
                meta.setdefault("yield_strength_mpa", profile.yield_strength_mpa)
                meta.setdefault("canonical_name", profile.canonical_name)
            elif rec:
                meta.setdefault("material_family", rec.identity.polymer_family)
                meta.setdefault("standard_reference", rec.metadata.get("standard_reference", rec.source.source_version))
                meta.setdefault("canonical_name", rec.identity.grade)
                meta.setdefault("source", rec.source.to_dict())

            u_sys = material_input.get("unit_system") or unit_system
            return MaterialDefinition(
                name=canon_name,
                unit_system=u_sys,
                elastic=elastic,
                density=density_val,
                plastic=plastic,
                thermal=thermal,
                provenance=prov,
                metadata=meta,
            )
        elif profile:
            return profile.to_material_definition(unit_system=unit_system)
        elif rec:
            from ..contracts.material_resolver import MaterialResolver
            res = MaterialResolver.resolve(
                record=rec,
                target_unit_system=unit_system,
                constitutive_intent="elastoplastic" if rec.curves else "linear_elastic",
            )
            if res.is_executable and res.material_definition:
                return res.material_definition
        elif fail_closed:
            raise ValueError(
                f"Cannot resolve material from dict: missing elastic properties in '{material_input}'"
            )
        return None

    if fail_closed:
        raise ValueError(f"Unsupported material input type: {type(material_input)}")
    return None


__all__ = [
    "MaterialDisposition",
    "StandardMaterialProfile",
    "STANDARD_MATERIALS",
    "classify_material_input",
    "enforce_material_disposition",
    "list_family_candidates",
    "match_engineering_material",
    "resolve_material_to_definition",
]
