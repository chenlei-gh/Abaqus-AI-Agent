"""Parse the material cards that a solved deck actually contains.

The report table and the yield used for a strength claim must come from this
parser, not from the material the planner intended to write. A plan can be
edited, an old evidence file can be reused, and a hand-written script can
change ``*PLASTIC`` after the plan was compiled. The deck that the solver
read is the only definition that can support a formal material claim.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


_CARD = re.compile(r"^\*([A-Za-z][A-Za-z0-9_]*(?:\s+[A-Za-z][A-Za-z0-9_]*)*)\b(.*)$")
_NAME = re.compile(r"(?:^|,)\s*NAME\s*=\s*([^,\s]+)", re.IGNORECASE)
_PARAM = re.compile(r"(?:^|,)\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*([^,]+)")
_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")


def parse_deck_materials(inp_text: str) -> Tuple[Dict[str, Any], ...]:
    """Return one normalized card per ``*MATERIAL`` block in deck order."""
    if not inp_text or not str(inp_text).strip():
        return ()
    raw_text = str(inp_text)
    cards = _material_cards(raw_text)
    assignments = _section_assignments(raw_text)
    for card in cards:
        material_name = _key(card.get("name"))
        card_assignments = tuple(
            item for item in assignments if _key(item.get("material")) == material_name
        )
        card["section_assignments"] = card_assignments
        card["applicable_regions"] = _applicable_regions(
            item.get("elset") for item in card_assignments
        )
    return tuple(_normalize_card(card) for card in cards)


def deck_material_table(inp_text: str, *, input_sha256: Optional[str] = None) -> Tuple[Dict[str, Any], ...]:
    """Build the report material rows from the solved deck, not from a plan."""
    digest = input_sha256 or (hashlib.sha256(str(inp_text or "").encode("utf-8")).hexdigest() if inp_text else None)
    rows = []
    for card in parse_deck_materials(inp_text):
        elastic = card.get("elastic") or {}
        plastic = card.get("plastic") or {}
        rows.append({
            "name": card["name"],
            "unit_system": card.get("unit_system"),
            "elastic": {
                "youngs_modulus": elastic.get("youngs_modulus"),
                "poisson_ratio": elastic.get("poisson_ratio"),
            } if elastic else None,
            "density": card.get("density"),
            "plastic": {
                "yield_stress": plastic.get("yield_stress"),
                "plastic_strain": plastic.get("plastic_strain"),
                "hardening_table": list(plastic.get("hardening_table") or ()),
            } if plastic else None,
            "applicable_regions": list(card.get("applicable_regions") or ()),
            "section_assignments": list(card.get("section_assignments") or ()),
            "source": "solved_deck",
            "input_sha256": digest,
            "line_start": card.get("line_start"),
            "line_end": card.get("line_end"),
        })
    return tuple(rows)


def compare_material_claims(
    claimed: Sequence[Any],
    deck_cards: Sequence[Dict[str, Any]],
    *,
    expected_input_sha256: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Compare a caller-supplied material table with the solved deck.

    A missing claim is not a pass. A claim that names the same material but
    carries a different curve, a different unit, or a stale deck hash is a
    mismatch. Two numbers are equal only when their normalized values match;
    the comparison does not pick the number that makes a conclusion look better.
    """
    claimed_cards = [_claim_card(item) for item in claimed or ()]
    claimed_cards = [item for item in claimed_cards if item]
    normalized_deck = []
    for item in deck_cards or ():
        if isinstance(item, str):
            normalized_deck.extend(parse_deck_materials(item))
        else:
            normalized_deck.append(_claim_card(item) or item)
    deck_cards = normalized_deck
    if not claimed_cards and not deck_cards:
        return None
    mismatches: List[Dict[str, Any]] = []
    deck_by_name = {_key(item.get("name")): item for item in deck_cards}
    claimed_names = {_key(item.get("name")) for item in claimed_cards}
    deck_names = set(deck_by_name)

    if not claimed_cards and deck_cards:
        mismatches.append({
            "code": "material_claim_missing",
            "deck_names": sorted(name for name in deck_names if name),
        })
    if claimed_names - deck_names:
        mismatches.append({
            "code": "material_name_not_in_deck",
            "claimed_names": sorted(claimed_names - deck_names),
        })
    if deck_names - claimed_names:
        mismatches.append({
            "code": "deck_material_missing_from_claim",
            "deck_names": sorted(deck_names - claimed_names),
        })
    for deck in deck_cards:
        if not _applicable_regions(deck.get("applicable_regions")):
            mismatches.append({
                "code": "material_unassigned_in_deck",
                "name": deck.get("name"),
            })

    for claim in claimed_cards:
        name = _key(claim.get("name"))
        deck = deck_by_name.get(name)
        if deck is None:
            continue
        claim_hash = claim.get("input_sha256")
        deck_hash = deck.get("input_sha256") or expected_input_sha256
        if claim_hash and deck_hash and str(claim_hash) != str(deck_hash):
            mismatches.append({
                "code": "stale_material_evidence",
                "name": claim.get("name"),
                "claimed_input_sha256": claim_hash,
                "deck_input_sha256": deck_hash,
            })
        if _unit(claim) and _unit(deck) and _unit(claim) != _unit(deck):
            mismatches.append({
                "code": "material_unit_mismatch",
                "name": claim.get("name"),
                "claimed": _unit(claim),
                "deck": _unit(deck),
            })
        for field_name in ("youngs_modulus", "poisson_ratio", "density"):
            left = _scalar(claim, field_name)
            right = _scalar(deck, field_name)
            if left is None and right is None:
                continue
            if left is None or right is None or not _close(left, right):
                mismatches.append({
                    "code": "material_value_mismatch",
                    "name": claim.get("name"),
                    "field": field_name,
                    "claimed": left,
                    "deck": right,
                })
        if _plastic_points(claim) != _plastic_points(deck):
            mismatches.append({
                "code": "plastic_curve_mismatch",
                "name": claim.get("name"),
                "claimed_points": _plastic_points(claim),
                "deck_points": _plastic_points(deck),
            })
        claim_regions = _applicable_regions(claim.get("applicable_regions"))
        deck_regions = _applicable_regions(deck.get("applicable_regions"))
        if deck_regions and not claim_regions:
            mismatches.append({
                "code": "material_applicable_regions_missing",
                "name": claim.get("name"),
                "deck_regions": list(deck_regions),
            })
        elif claim_regions != deck_regions:
            mismatches.append({
                "code": "material_applicable_regions_mismatch",
                "name": claim.get("name"),
                "claimed_regions": list(claim_regions),
                "deck_regions": list(deck_regions),
            })

    if not mismatches:
        return None
    return {
        "code": "material_card_mismatch",
        "mismatches": mismatches,
    }


def _material_cards(text: str) -> List[Dict[str, Any]]:
    lines = text.splitlines()
    cards: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    keyword: Optional[str] = None
    data: List[str] = []

    def flush_keyword() -> None:
        nonlocal keyword, data
        if current is not None and keyword:
            current.setdefault("keywords", {})[keyword] = list(data)
        keyword = None
        data = []

    for index, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("**"):
            continue
        match = _CARD.match(stripped)
        if match:
            flush_keyword()
            name = match.group(1).upper()
            params = match.group(2) or ""
            if name == "MATERIAL":
                if current is not None:
                    current["line_end"] = index - 1
                    cards.append(current)
                found = _NAME.search(params)
                current = {
                    "name": (found.group(1).strip() if found else ""),
                    "line_start": index,
                    "keywords": {},
                }
                keyword = None
                continue
            if current is None:
                continue
            if name in ("ELASTIC", "PLASTIC", "DENSITY"):
                keyword = name
                current["keywords"].setdefault(name + "_params", params)
            else:
                keyword = None
            continue
        if current is not None and keyword:
            data.append(stripped)
    flush_keyword()
    if current is not None:
        current["line_end"] = len(lines)
        cards.append(current)
    return cards


def _normalize_card(card: Dict[str, Any]) -> Dict[str, Any]:
    keywords = card.get("keywords") or {}
    elastic_rows = _rows(keywords.get("ELASTIC") or ())
    plastic_rows = _rows(keywords.get("PLASTIC") or ())
    density_rows = _rows(keywords.get("DENSITY") or ())
    elastic = None
    if elastic_rows and len(elastic_rows[0]) >= 2:
        elastic = {
            "youngs_modulus": elastic_rows[0][0],
            "poisson_ratio": elastic_rows[0][1],
        }
    plastic = None
    if plastic_rows:
        points = tuple((row[0], row[1] if len(row) > 1 else 0.0) for row in plastic_rows if row)
        plastic = {
            "yield_stress": points[0][0],
            "plastic_strain": points[0][1],
            "hardening_table": points[1:],
            "points": points,
        }
    return {
        "name": card.get("name") or "",
        "unit_system": None,
        "elastic": elastic,
        "density": density_rows[0][0] if density_rows and density_rows[0] else None,
        "plastic": plastic,
        "applicable_regions": _applicable_regions(card.get("applicable_regions")),
        "section_assignments": tuple(card.get("section_assignments") or ()),
        "line_start": card.get("line_start"),
        "line_end": card.get("line_end"),
        "source": "solved_deck",
    }


def _claim_card(item: Any) -> Optional[Dict[str, Any]]:
    if item is None:
        return None
    if hasattr(item, "to_dict"):
        item = item.to_dict()
    if not isinstance(item, dict):
        return None
    plastic = item.get("plastic") if isinstance(item.get("plastic"), dict) else None
    points = _plastic_points(item)
    return {
        "name": item.get("name") or item.get("material") or "",
        "unit_system": item.get("unit_system"),
        "elastic": item.get("elastic") if isinstance(item.get("elastic"), dict) else None,
        "density": item.get("density"),
        "plastic": {
            "yield_stress": points[0][0] if points else (plastic or {}).get("yield_stress"),
            "plastic_strain": points[0][1] if points else (plastic or {}).get("plastic_strain"),
            "hardening_table": points[1:],
            "points": points,
        } if plastic or points else None,
        "applicable_regions": _applicable_regions(item.get("applicable_regions")),
        "section_assignments": tuple(item.get("section_assignments") or ()),
        "input_sha256": item.get("input_sha256") or (item.get("metadata") or {}).get("input_sha256"),
    }


def _section_assignments(text: str) -> Tuple[Dict[str, Any], ...]:
    '''Return section assignments carrying both a material and an ELSET.'''
    assignments: List[Dict[str, Any]] = []
    for index, raw in enumerate(str(text or "").splitlines(), start=1):
        stripped = raw.strip()
        match = _CARD.match(stripped)
        if not match:
            continue
        keyword = match.group(1).upper().replace(" ", "_")
        if not keyword.endswith("SECTION"):
            continue
        params = {
            key.upper(): value.strip().strip('"').strip("'")
            for key, value in _PARAM.findall(match.group(2) or "")
        }
        material = params.get("MATERIAL")
        elset = params.get("ELSET")
        if material and elset:
            assignments.append({
                "section_type": keyword,
                "material": material,
                "elset": elset,
                "line_start": index,
            })
    return tuple(assignments)


def _applicable_regions(value: Any) -> Tuple[str, ...]:
    '''Normalize section ELSET names or claim region declarations.'''
    if value is None:
        return ()
    if isinstance(value, str):
        values: Sequence[Any] = (value,)
    elif isinstance(value, dict):
        values = (value.get("elset") or value.get("region") or value.get("name"),)
    else:
        values = tuple(value)
    regions = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("elset") or item.get("region") or item.get("name")
        name = str(item or "").strip()
        if name:
            regions.append(name)
    return tuple(sorted(set(regions), key=lambda item: (item.upper(), item)))


def _rows(lines: Sequence[str]) -> List[Tuple[float, ...]]:
    rows = []
    for line in lines:
        values = tuple(float(item) for item in _NUMBER.findall(line))
        if values:
            rows.append(values)
    return rows


def _plastic_points(card: Dict[str, Any]) -> Tuple[Tuple[float, float], ...]:
    plastic = card.get("plastic") if isinstance(card, dict) else None
    if not isinstance(plastic, dict):
        return ()
    raw = plastic.get("points")
    if not raw:
        table = list(plastic.get("hardening_table") or ())
        if plastic.get("yield_stress") is not None:
            table = [(plastic.get("yield_stress"), plastic.get("plastic_strain") or 0.0)] + table
        raw = table
    points = []
    for item in raw:
        if isinstance(item, (list, tuple)) and item:
            stress = float(item[0])
            strain = float(item[1]) if len(item) > 1 else 0.0
            points.append((stress, strain))
    return tuple(points)


def _scalar(card: Dict[str, Any], field_name: str) -> Optional[float]:
    if field_name == "density":
        value = card.get("density")
    else:
        elastic = card.get("elastic") if isinstance(card.get("elastic"), dict) else {}
        value = elastic.get(field_name)
    if value is None or value == "":
        return None
    return float(value)


def _unit(card: Dict[str, Any]) -> str:
    return str(card.get("unit_system") or "").strip().upper()


def _key(name: Any) -> str:
    return str(name or "").strip().upper()


def _close(left: float, right: float) -> bool:
    scale = max(abs(left), abs(right), 1.0)
    return abs(left - right) <= 1e-9 * scale
