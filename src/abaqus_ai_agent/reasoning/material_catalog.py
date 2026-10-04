"""Standard Engineering Material Catalog and Normalizer for P1.2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from ..contracts.intent_reasoning import InferenceRiskLevel, InferredParameter


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
        aliases=("6061", "6061-t6", "al6061", "al 6061", "aluminum", "铝", "铝合金", "al"),
        youngs_modulus_mpa=68900.0,
        poissons_ratio=0.33,
        density_tonne_mm3=2.70e-9,
        yield_strength_mpa=276.0,
        material_family="aluminum_alloy",
        standard_reference="ASTM B221 / GB/T 3190-2020",
    ),
    StandardMaterialProfile(
        canonical_name="Aluminum_7075_T6",
        aliases=("7075", "7075-t6", "al7075", "al 7075", "航空铝"),
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

    # Handle dictionary input
    if isinstance(material_input, dict):
        # If already completely specified with numbers
        name = str(material_input.get("name", ""))
        e_val = material_input.get("elastic_modulus")
        nu_val = material_input.get("poisson_ratio")
        if e_val is not None and nu_val is not None:
            # Check if density or yield strength can be enriched
            profile = _find_profile(name)
            enriched = dict(material_input)
            if profile:
                if "density" not in enriched:
                    enriched["density"] = profile.density_tonne_mm3
                if "yield_strength" not in enriched:
                    enriched["yield_strength"] = profile.yield_strength_mpa
            return enriched, None
        # Dict has only name
        query = name
    elif isinstance(material_input, str):
        query = material_input
    else:
        query = str(material_input)

    profile = _find_profile(query)
    if profile is None:
        return None, None

    resolved_dict = {
        "name": profile.canonical_name,
        "elastic_modulus": profile.youngs_modulus_mpa,
        "poisson_ratio": profile.poissons_ratio,
        "density": profile.density_tonne_mm3,
        "yield_strength": profile.yield_strength_mpa,
        "unit": "MPa",
        "material_family": profile.material_family,
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


def _find_profile(query: str) -> Optional[StandardMaterialProfile]:
    q = query.strip().lower()
    if not q:
        return None

    # 1. Exact match in canonical name or aliases
    for p in STANDARD_MATERIALS:
        if q == p.canonical_name.lower():
            return p
        if q in p.aliases:
            return p

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
