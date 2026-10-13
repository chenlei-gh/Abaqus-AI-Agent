"""Generic & Decoupled Intent Routing for Abaqus Engineering.

Translates unconstrained natural language engineering requirements into typed,
deterministic EngineeringIntent and ResultRequirement models using declarative primitives:
- Choice: Discretely classifies physics category, unit system, and target solver.
- Noul: Assesses constraints sufficiency probability and acceptance criteria explicitness.
- Score: Quantifies engineering intent completeness (1 to 5 scale).

Architectural Decoupling Contract (REQ-P1-046 ~ REQ-P1-049, REQ-P1-053):
- Core Open-Source Engine: Deterministic offline rule engine runs 100% self-sufficiently
  without any external API keys, commercial services, or internet access.
- Optional External Provider: Cleanly isolated via ExternalIntentProviderProtocol.
  Proprietary endpoints and credentials are strictly kept outside the core open-source codebase.
- Three-State Execution Modes:
  * 'offline' (default): Pure deterministic rule engine (hermetic, reproducible, zero-cost).
  * 'live': Invokes configured external provider. Fails closed (JevApiError) on any error.
  * 'shadow': Baseline offline engine executes, while recording side-by-side discrepancy auditing.
    If external provider is not configured, records status='NOT_CONFIGURED'.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.results import ResultRequirement
from abaqus_ai_agent.contracts.units import UnitSystem


def _sanitize_error_message(err_msg: str) -> str:
    """Deep sanitization of error messages to eliminate sensitive credentials, URLs, query parameters, and unscrubbed prompts."""
    if not err_msg:
        return "Unknown error"
    # 1. Redact Authorization tokens (Bearer, Basic, etc.)
    sanitized = re.sub(r"(bearer\s+)[^\s]+", r"\1[REDACTED]", err_msg, flags=re.IGNORECASE)
    sanitized = re.sub(r"(basic\s+)[^\s]+", r"\1[REDACTED]", sanitized, flags=re.IGNORECASE)
    # 2. Redact potential API keys (e.g. sk-..., key=..., token=...)
    sanitized = re.sub(r"(sk-[a-zA-Z0-9_-]{8,})", r"[REDACTED_KEY]", sanitized)
    sanitized = re.sub(r"(?:api[_-]?key|token|secret)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-\.]+['\"]?", r"[REDACTED_CREDENTIAL]", sanitized, flags=re.IGNORECASE)
    # 3. Strip URLs and query parameters
    sanitized = re.sub(r"https?://[^\s/?#]+(?:/[^\s?#]*)?(?:\?[^\s#]*)?", r"[REDACTED_URL]", sanitized)
    # 4. Strip filesystem paths
    sanitized = re.sub(r"(?:[a-zA-Z]:\\|\/)[^\s:\"']+", r"[REDACTED_PATH]", sanitized)
    # 5. Clean extra whitespace and truncate to safe bound
    sanitized = " ".join(sanitized.split())
    return sanitized[:120] if len(sanitized) > 120 else sanitized


def _get_external_config(*var_names: str) -> Optional[str]:
    """Read external configuration in order of priority, stripping whitespace and treating empty/blank as None."""
    for name in var_names:
        if not name:
            continue
        val = os.environ.get(name)
        if val is not None:
            stripped = val.strip()
            if stripped:
                return stripped
    return None


def _has_valid_entity_data(val: Any) -> bool:
    """Validate that an input represents real engineering entity data rather than nominal boolean flags or empty stubs.

    Strict contract:
    - Boolean values (True/False) are explicitly rejected.
    - Empty strings or whitespace-only strings are rejected.
    - Empty lists, tuples, sets, or collections containing only empty/None items are rejected.
    - Empty dicts or dicts containing only boolean flags or empty values are rejected.
    """
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        fv = float(val)
        return not (math.isnan(fv) or math.isinf(fv))
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, (list, tuple, set)):
        return len(val) > 0 and any(_has_valid_entity_data(item) for item in val)
    if isinstance(val, dict):
        if not val:
            return False
        # Discard nominal boolean-only or stub dicts (e.g. {"has_model": True})
        valid_items = [
            v for k, v in val.items()
            if not isinstance(v, bool) and _has_valid_entity_data(v)
        ]
        return len(valid_items) > 0
    return False


def _is_finite_positive_number(v: Any) -> bool:
    """Check if value is a finite, positive, non-boolean number (> 0.0)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        fv = float(v)
        return not (math.isnan(fv) or math.isinf(fv)) and fv > 0.0
    except (TypeError, ValueError):
        return False


def _is_finite_number(v: Any) -> bool:
    """Check if value is a finite, non-boolean number."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        fv = float(v)
        return not (math.isnan(fv) or math.isinf(fv))
    except (TypeError, ValueError):
        return False


def _is_unverified_or_expired_evidence(val: Any) -> bool:
    """Check if dictionary or object carries explicit UNVERIFIED, invalid, or expired evidence markers."""
    if isinstance(val, dict):
        status = str(val.get("status", "")).strip().upper()
        if status in ("UNVERIFIED", "EXPIRED", "CONFLICT", "INVALID"):
            return True
        if val.get("verified") is False:
            return True
        if val.get("expired") is True:
            return True
    return False


VALID_LENGTH_UNITS = {
    "mm", "m", "cm", "in", "inch", "ft", "um", "nm",
    "毫米", "米", "厘米", "微米", "英寸",
}

VALID_BC_TYPES = {
    "encastre", "fixed", "pinned", "roller",
    "symmetry", "antisymmetry", "displacement",
    "xsy_symmetry", "ysy_symmetry", "zsy_symmetry",
    "submodel", "spring",
}

VALID_LOAD_TYPES = {
    "concentrated_force", "pressure", "moment",
    "surface_traction", "body_force", "gravity",
    "line_load", "thermal_load", "force", "cload",
}

VALID_THERMAL_BC_TYPES = {
    "temperature", "heat_flux", "convection", "radiation", "film_condition", "flux",
}


def _validate_dimensions_entity(val: Any) -> Tuple[bool, Optional[Any], Optional[str]]:
    """Validate geometry dimensions entity.

    Rejects:
    - Booleans
    - Unverified or expired context markers
    - Non-positive numbers (<= 0), NaN, Inf
    - Nominal boolean-only dicts
    - Unsupported or invalid length units
    Returns: (is_valid, normalized_entity, error_reason)
    """
    if val is None or isinstance(val, bool):
        return False, None, "nominal_boolean_or_none"
    if _is_unverified_or_expired_evidence(val):
        return False, None, "unverified_or_expired_evidence"

    if _is_finite_positive_number(val):
        return True, [{"value": float(val), "unit": "mm"}], None

    if isinstance(val, (list, tuple)):
        if not val:
            return False, None, "empty_dimensions_collection"
        normalized = []
        for item in val:
            if isinstance(item, bool):
                return False, None, "boolean_in_dimensions"
            if _is_unverified_or_expired_evidence(item):
                return False, None, "unverified_or_expired_evidence"
            if _is_finite_positive_number(item):
                normalized.append({"value": float(item), "unit": "mm"})
            elif isinstance(item, dict):
                v = item.get("value")
                if v is not None:
                    if not _is_finite_positive_number(v):
                        return False, None, "non_positive_or_infinite_dimension"
                    u = str(item.get("unit", "mm")).strip().lower()
                    if u not in VALID_LENGTH_UNITS:
                        return False, None, f"invalid_dimension_unit_{u}"
                    normalized.append({"value": float(v), "unit": u})
                else:
                    dim_keys = [k for k in ("length", "width", "height", "thickness", "radius", "diameter", "depth") if k in item]
                    if not dim_keys:
                        return False, None, "missing_dimension_numeric_values"
                    for k in dim_keys:
                        kv = item[k]
                        if not _is_finite_positive_number(kv):
                            return False, None, "non_positive_or_infinite_dimension"
                    if "unit" in item:
                        u = str(item["unit"]).strip().lower()
                        if u not in VALID_LENGTH_UNITS:
                            return False, None, f"invalid_dimension_unit_{u}"
                    normalized.append(dict(item))
            else:
                return False, None, f"unsupported_dimension_item_type_{type(item).__name__}"
        return (True, normalized, None) if normalized else (False, None, "no_valid_dimensions")

    if isinstance(val, dict):
        if not val:
            return False, None, "empty_dimensions_dict"
        if "box" in val and isinstance(val["box"], (list, tuple)):
            box = val["box"]
            if all(_is_finite_positive_number(x) for x in box):
                u = str(val.get("unit", "mm")).strip().lower()
                if u not in VALID_LENGTH_UNITS:
                    return False, None, f"invalid_dimension_unit_{u}"
                return True, [{"value": float(x), "unit": u} for x in box], None
            return False, None, "non_positive_or_infinite_box_dimension"

        if "unit" in val:
            u = str(val["unit"]).strip().lower()
            if u not in VALID_LENGTH_UNITS:
                return False, None, f"invalid_dimension_unit_{u}"

        numeric_items = {}
        for k, v in val.items():
            if k in ("status", "verified", "source", "evidence_type", "unit"):
                continue
            if isinstance(v, bool):
                continue
            if _is_finite_positive_number(v):
                numeric_items[k] = float(v)
            elif isinstance(v, (list, tuple)) and all(_is_finite_positive_number(x) for x in v):
                numeric_items[k] = [float(x) for x in v]
            elif isinstance(v, dict):
                sub_ok, sub_norm, _ = _validate_dimensions_entity(v)
                if sub_ok:
                    numeric_items[k] = sub_norm

        if numeric_items:
            return True, numeric_items, None
        return False, None, "no_positive_numeric_dimensions_found"

    return False, None, "unsupported_dimensions_type"


def _validate_material_entity(val: Any) -> Tuple[bool, Optional[Any], Optional[str]]:
    """Validate material entity.

    Rejects:
    - Booleans
    - Unverified or expired context markers
    - Missing or null material names
    - Poisson's ratio outside [0.0, 0.5) (reject nu >= 0.5 singularity, nu < 0)
    - Elastic modulus <= 0.0 or non-finite
    Returns: (is_valid, normalized_entity, error_reason)
    """
    if val is None or isinstance(val, bool):
        return False, None, "nominal_boolean_or_none"
    if _is_unverified_or_expired_evidence(val):
        return False, None, "unverified_or_expired_evidence"

    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned or cleaned.lower() in ("null", "none", "unknown", "n/a", "undefined"):
            return False, None, "invalid_material_name_string"
        return True, {"name": cleaned, "source": "named_string"}, None

    if isinstance(val, dict):
        if not val:
            return False, None, "empty_material_dict"
        name = val.get("name")
        if name is not None:
            if isinstance(name, bool) or not str(name).strip() or str(name).strip().lower() in ("null", "none", "unknown"):
                return False, None, "invalid_material_name"

        if "elastic_modulus" in val:
            em = val["elastic_modulus"]
            if not _is_finite_positive_number(em):
                return False, None, "invalid_elastic_modulus"

        if "poisson_ratio" in val:
            pr = val["poisson_ratio"]
            if isinstance(pr, bool) or not _is_finite_number(pr):
                return False, None, "invalid_poisson_ratio_non_numeric"
            fpr = float(pr)
            if not (0.0 <= fpr < 0.5):
                return False, None, f"poisson_ratio_out_of_physical_range_{fpr}"

        has_real_fields = any(
            k in val for k in ("name", "elastic_modulus", "poisson_ratio", "density", "yield_strength", "conductivity")
        )
        if not has_real_fields:
            return False, None, "nominal_flag_only_without_engineering_properties"

        norm_mat = dict(val)
        if "name" in norm_mat:
            norm_mat["name"] = str(norm_mat["name"]).strip()
        return True, norm_mat, None

    return False, None, "unsupported_material_type"


def _validate_boundary_conditions_entity(val: Any) -> Tuple[bool, Optional[Any], Optional[str]]:
    """Validate boundary conditions entity strictly.

    Rejects:
    - Booleans and None
    - Unverified or expired context markers
    - Bare string without geometric region (no arbitrary FixedFace forgery)
    - Entities missing explicit constraint type or missing geometric region
    - Nominal boolean-only dicts
    Returns: (is_valid, normalized_entity, error_reason)
    """
    if val is None or isinstance(val, bool):
        return False, None, "nominal_boolean_or_none"
    if _is_unverified_or_expired_evidence(val):
        return False, None, "unverified_or_expired_evidence"

    def _validate_single_bc(item: Any) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        if item is None or isinstance(item, bool):
            return False, None, "boolean_or_none_in_bc"
        if _is_unverified_or_expired_evidence(item):
            return False, None, "unverified_or_expired_evidence"
        if not isinstance(item, dict):
            return False, None, f"boundary_condition_must_be_dict_got_{type(item).__name__}"

        raw_type = item.get("type") or item.get("bc_type")
        if raw_type is None or isinstance(raw_type, bool) or not str(raw_type).strip():
            return False, None, "missing_boundary_condition_type"
        bc_type = str(raw_type).strip().lower()
        if not any(valid_t in bc_type for valid_t in VALID_BC_TYPES):
            return False, None, f"unsupported_boundary_condition_type_{bc_type}"

        raw_region = item.get("region") or item.get("surface") or item.get("set") or item.get("face") or item.get("nodeset")
        if raw_region is None or isinstance(raw_region, bool) or not str(raw_region).strip():
            return False, None, "missing_boundary_condition_region"
        region = str(raw_region).strip()

        norm: Dict[str, Any] = {
            "type": bc_type,
            "region": region,
        }
        if "dofs" in item and item["dofs"] is not None:
            norm["dofs"] = item["dofs"]
        for dof_k in ("u1", "u2", "u3", "ur1", "ur2", "ur3"):
            if dof_k in item and item[dof_k] is not None:
                norm[dof_k] = item[dof_k]
        return True, norm, None

    if isinstance(val, (list, tuple)):
        if not val:
            return False, None, "empty_boundary_conditions_list"
        valid_bcs = []
        for item in val:
            ok, norm_bc, err = _validate_single_bc(item)
            if not ok:
                return False, None, err
            valid_bcs.append(norm_bc)
        return (True, valid_bcs, None) if valid_bcs else (False, None, "no_valid_boundary_condition_items")

    if isinstance(val, dict):
        if not val:
            return False, None, "empty_boundary_conditions_dict"
        ok, norm_bc, err = _validate_single_bc(val)
        if ok:
            return True, [norm_bc], None
        return False, None, err

    return False, None, "unsupported_boundary_conditions_type"


def _validate_loads_entity(val: Any, require_region: bool = False) -> Tuple[bool, Optional[Any], Optional[str]]:
    """Validate loads entity strictly.

    Rejects:
    - Booleans and None
    - Unverified or expired context markers
    - Entities missing finite numerical magnitude (no empty/missing magnitude dicts)
    - Entities missing load type or missing geometric region (when require_region=True)
    - Nominal boolean-only dicts
    Returns: (is_valid, normalized_entity, error_reason)
    """
    if val is None or isinstance(val, bool):
        return False, None, "nominal_boolean_or_none"
    if _is_unverified_or_expired_evidence(val):
        return False, None, "unverified_or_expired_evidence"

    def _validate_single_load(item: Any) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        if item is None or isinstance(item, bool):
            return False, None, "boolean_or_none_in_load"
        if _is_unverified_or_expired_evidence(item):
            return False, None, "unverified_or_expired_evidence"
        if not isinstance(item, dict):
            return False, None, f"load_must_be_dict_got_{type(item).__name__}"

        # Finite magnitude is strictly required
        mag = item.get("magnitude")
        if mag is None:
            mag = item.get("force") if "force" in item else (item.get("pressure") if "pressure" in item else item.get("value"))
        if mag is None or isinstance(mag, bool) or not _is_finite_number(mag):
            return False, None, "missing_or_non_finite_load_magnitude"
        fmag = float(mag)

        raw_type = item.get("type") or item.get("load_type")
        if raw_type is None or isinstance(raw_type, bool) or not str(raw_type).strip():
            if "pressure" in item:
                raw_type = "pressure"
            elif "force" in item or "magnitude" in item:
                raw_type = "concentrated_force"
            else:
                return False, None, "missing_load_type"
        load_type = str(raw_type).strip().lower()
        if not any(valid_t in load_type for valid_t in VALID_LOAD_TYPES):
            return False, None, f"unsupported_load_type_{load_type}"

        raw_region = item.get("region") or item.get("surface") or item.get("set") or item.get("face")
        if require_region:
            if raw_region is None or isinstance(raw_region, bool) or not str(raw_region).strip():
                return False, None, "missing_load_region"

        norm: Dict[str, Any] = {
            "type": load_type,
            "magnitude": fmag,
        }
        if raw_region and str(raw_region).strip():
            norm["region"] = str(raw_region).strip()
        if "direction" in item and item["direction"]:
            norm["direction"] = str(item["direction"]).strip()
        if "unit" in item and item["unit"]:
            norm["unit"] = str(item["unit"]).strip()
        return True, norm, None

    if isinstance(val, (list, tuple)):
        if not val:
            return False, None, "empty_loads_list"
        valid_loads = []
        for item in val:
            ok, norm_ld, err = _validate_single_load(item)
            if not ok:
                return False, None, err
            valid_loads.append(norm_ld)
        return (True, valid_loads, None) if valid_loads else (False, None, "no_valid_load_items")

    if isinstance(val, dict):
        if not val:
            return False, None, "empty_loads_dict"
        ok, norm_ld, err = _validate_single_load(val)
        if ok:
            return True, [norm_ld], None
        return False, None, err

    return False, None, "unsupported_loads_type"


def _validate_thermal_bcs_entity(val: Any) -> Tuple[bool, Optional[Any], Optional[str]]:
    """Validate thermal boundary conditions entity strictly."""
    if val is None or isinstance(val, bool):
        return False, None, "nominal_boolean_or_none"
    if _is_unverified_or_expired_evidence(val):
        return False, None, "unverified_or_expired_evidence"

    def _validate_single_th(item: Any) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        if item is None or isinstance(item, bool):
            return False, None, "boolean_or_none_in_thermal_bc"
        if _is_unverified_or_expired_evidence(item):
            return False, None, "unverified_or_expired_evidence"
        if not isinstance(item, dict):
            return False, None, f"thermal_bc_must_be_dict_got_{type(item).__name__}"

        raw_type = item.get("type") or item.get("bc_type")
        if raw_type is None or isinstance(raw_type, bool) or not str(raw_type).strip():
            if "temperature" in item:
                raw_type = "temperature"
            elif "heat_flux" in item or "flux" in item:
                raw_type = "heat_flux"
            else:
                return False, None, "missing_thermal_bc_type"
        th_type = str(raw_type).strip().lower()
        if not any(valid_t in th_type for valid_t in VALID_THERMAL_BC_TYPES):
            return False, None, f"unsupported_thermal_bc_type_{th_type}"

        val_mag = item.get("magnitude") or item.get("temperature") or item.get("heat_flux") or item.get("value")
        if val_mag is not None and (isinstance(val_mag, bool) or not _is_finite_number(val_mag)):
            return False, None, "invalid_thermal_magnitude"

        raw_region = item.get("region") or item.get("surface") or item.get("set") or item.get("face")
        if raw_region is None or isinstance(raw_region, bool) or not str(raw_region).strip():
            return False, None, "missing_thermal_bc_region"

        norm: Dict[str, Any] = {
            "type": th_type,
            "region": str(raw_region).strip(),
        }
        if val_mag is not None:
            norm["magnitude"] = float(val_mag)
        return True, norm, None

    if isinstance(val, (list, tuple)):
        if not val:
            return False, None, "empty_thermal_bcs_list"
        valid_items = []
        for item in val:
            ok, norm_th, err = _validate_single_th(item)
            if not ok:
                return False, None, err
            valid_items.append(norm_th)
        return (True, valid_items, None) if valid_items else (False, None, "no_valid_thermal_bc_items")

    if isinstance(val, dict):
        if not val:
            return False, None, "empty_thermal_bcs_dict"
        ok, norm_th, err = _validate_single_th(val)
        if ok:
            return True, [norm_th], None
        return False, None, err

    return False, None, "unsupported_thermal_bcs_type"


def _validate_acceptance_criteria_entity(val: Any) -> Tuple[bool, Optional[Any], Optional[str]]:
    """Validate acceptance criteria entity strictly."""
    if val is None or isinstance(val, bool):
        return False, None, "nominal_boolean_or_none"
    if _is_unverified_or_expired_evidence(val):
        return False, None, "unverified_or_expired_evidence"

    def _validate_single_crit(item: Any) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        if item is None or isinstance(item, bool):
            return False, None, "boolean_or_none_in_criteria"
        if _is_unverified_or_expired_evidence(item):
            return False, None, "unverified_or_expired_evidence"
        if not isinstance(item, dict):
            return False, None, f"criteria_must_be_dict_got_{type(item).__name__}"

        lim = item.get("limit")
        if lim is None or isinstance(lim, bool) or not _is_finite_number(lim):
            return False, None, "missing_or_invalid_limit"

        name = item.get("metric") or item.get("name") or item.get("value_key")
        if name is None or isinstance(name, bool) or not str(name).strip():
            return False, None, "missing_metric_name"

        op = str(item.get("operator", "<=")).strip()
        norm: Dict[str, Any] = {
            "name": str(name).strip(),
            "metric": str(name).strip(),
            "operator": op,
            "limit": float(lim),
        }
        if "unit" in item and item["unit"]:
            norm["unit"] = str(item["unit"]).strip()
        return True, norm, None

    if isinstance(val, (list, tuple)):
        if not val:
            return False, None, "empty_criteria_list"
        valid_crits = []
        for item in val:
            ok, norm_cr, err = _validate_single_crit(item)
            if not ok:
                return False, None, err
            valid_crits.append(norm_cr)
        return (True, valid_crits, None) if valid_crits else (False, None, "no_valid_criteria_items")

    if isinstance(val, dict):
        ok, norm_cr, err = _validate_single_crit(val)
        if ok:
            return True, [norm_cr], None
        return False, None, err

    return False, None, "unsupported_criteria_type"


def _normalize_material_class(name: Optional[str]) -> Optional[str]:
    """Map natural or structured material names into canonical physics classification classes."""
    if not name:
        return None
    nl = str(name).strip().lower()
    if any(w in nl for w in ("steel", "结构钢", "q235", "45", "碳钢", "合金钢", "astm")):
        return "steel"
    if any(w in nl for w in ("aluminum", "al6061", "al7075", "铝", "铝合金")):
        return "aluminum"
    if any(w in nl for w in ("rubber", "橡胶", "hyperelastic", "silicone")):
        return "rubber"
    if any(w in nl for w in ("copper", "铜", "黄铜", "紫铜")):
        return "copper"
    if any(w in nl for w in ("titanium", "钛", "钛合金", "ti6al4v")):
        return "titanium"
    if any(w in nl for w in ("elastic", "linear_elastic", "线性弹性")):
        return "linear_elastic"
    return nl


def _detect_entity_conflicts(
    prompt: str,
    extracted_params: Dict[str, Any],
    context: Optional[Dict[str, Any]],
    physics_choice: str,
) -> List[str]:
    """Detect unresolvable engineering conflicts between user prompt and upstream context.

    Zero silent overriding: Any fundamental engineering contradiction between prompt specifications
    and context entities must trigger explicit clarification rather than silent arbitrary selection.
    """
    conflicts: List[str] = []
    if not context:
        return conflicts

    # 1. Material Conflicts
    p_mat = extracted_params.get("material")
    c_mat = context.get("material") or (context.get("inp_evidence", {}).get("material") if isinstance(context.get("inp_evidence"), dict) else None)

    if p_mat and c_mat:
        p_name = p_mat.get("name") if isinstance(p_mat, dict) else str(p_mat)
        c_name = c_mat.get("name") if isinstance(c_mat, dict) else str(c_mat)
        p_class = _normalize_material_class(p_name)
        c_class = _normalize_material_class(c_name)
        if p_class and c_class and p_class != c_class:
            conflicts.append(
                f"conflict_material_specification: Prompt specifies '{p_name}' ({p_class}) "
                f"while context specifies '{c_name}' ({c_class}). "
                "Engineering properties differ significantly; please clarify intended material."
            )

    # 2. Physics Domain Conflicts
    c_phys = context.get("physics") or context.get("analysis_type")
    if c_phys and isinstance(c_phys, str):
        c_phys_norm = c_phys.strip().lower()
        if c_phys_norm in ("linear_static", "steady_thermal", "transient_dynamic", "modal_frequency", "contact_frictional", "fatigue_damage") and c_phys_norm != physics_choice:
            conflicts.append(
                f"conflict_physics_domain: Prompt requires '{physics_choice}' "
                f"while context enforces '{c_phys_norm}'. "
                "Analysis domains are incompatible; please clarify simulation objective."
            )

    # 3. Loads Conflicts (Type and Magnitude contradictions)
    p_loads = extracted_params.get("loads", [])
    c_loads = context.get("loads")
    if p_loads and c_loads:
        c_load_ok, c_load_norm, _ = _validate_loads_entity(c_loads, require_region=False)
        if c_load_ok and c_load_norm:
            p_types = {str(ld.get("type", "concentrated_force")).lower() for ld in p_loads}
            c_types = {str(c_ld.get("type", "")).lower() for c_ld in c_load_norm}
            if ("concentrated_force" in p_types and "pressure" in c_types) or ("pressure" in p_types and "concentrated_force" in c_types):
                conflicts.append(
                    f"conflict_load_type: Prompt specifies load type {list(p_types)} "
                    f"while context defines {list(c_types)}. Please clarify load application type."
                )

    # 4. Boundary Condition Conflicts (e.g. Free-Free / Simple vs Encastre / Fixed)
    prompt_lower = prompt.lower()
    c_bcs = context.get("boundary_conditions") or context.get("constraints")
    if c_bcs:
        c_bc_ok, c_bc_norm, _ = _validate_boundary_conditions_entity(c_bcs)
        if c_bc_ok and c_bc_norm:
            has_encastre_ctx = any("encastre" in bc.get("type", "") or "fixed" in bc.get("type", "") for bc in c_bc_norm)
            if has_encastre_ctx and any(w in prompt_lower for w in ("自由模态", "自由自由", "free-free", "无约束", "两端简支", "简支", "simply supported", "simply-supported", "pinned")):
                conflicts.append(
                    "conflict_boundary_constraints: Prompt requests unconstrained/simply-supported conditions "
                    "while context enforces fixed/encastre boundary conditions."
                )

    # 5. Unit System Conflicts
    c_unit_sys = context.get("unit_system")
    if c_unit_sys and isinstance(c_unit_sys, str):
        cus = c_unit_sys.strip().upper()
        if cus in ("SI_M", "M", "SI-M"):
            if any(w in prompt_lower for w in ("mm", "毫米", "mpa", "兆帕")):
                conflicts.append(
                    f"conflict_unit_system: Context specifies '{cus}' (meter-based) "
                    "while prompt specifies millimeter/MPa units (SI_MM)."
                )
        elif cus in ("SI_MM", "MM", "SI-MM"):
            if re.search(r'\b\d+\s*m\b', prompt_lower) or any(w in prompt_lower for w in ("米制", "国际单位制(m)")):
                conflicts.append(
                    f"conflict_unit_system: Context specifies '{cus}' (millimeter-based) "
                    "while prompt specifies meter-based units."
                )

    return conflicts


def _validate_numeric(
    value: Any,
    min_val: float,
    max_val: float,
    field_name: str,
) -> float:
    """Strictly validate numeric values: reject booleans, NaN, Inf, and out-of-range floats."""
    if isinstance(value, bool):
        raise ExternalIntentApiError(
            f"Field {field_name!r} must not be a boolean value: {value!r}"
        )
    if not isinstance(value, (int, float)):
        raise ExternalIntentApiError(
            f"Field {field_name!r} must be a numeric value, got {type(value).__name__}: {value!r}"
        )
    fval = float(value)
    if math.isnan(fval) or math.isinf(fval):
        raise ExternalIntentApiError(
            f"Field {field_name!r} must be a finite number, got {fval!r}"
        )
    if not (min_val <= fval <= max_val):
        raise ExternalIntentApiError(
            f"Field {field_name!r} value {fval} out of bounds [{min_val}, {max_val}]"
        )
    return fval


def _validate_distribution(
    dist: Any,
    allowed_keys: Tuple[str, ...],
    field_name: str,
) -> Dict[str, float]:
    """Strictly validate probability distributions: dict type, allowed keys, non-empty, probabilities in [0.0, 1.0], and sum(probabilities) == 1.0."""
    if not isinstance(dist, dict) or not dist:
        raise ExternalIntentApiError(f"Field {field_name!r} distribution must be a non-empty dictionary.")
    validated: Dict[str, float] = {}
    for k, v in dist.items():
        if k not in allowed_keys:
            raise ExternalIntentApiError(f"Invalid {field_name} choice in distribution: {k!r}")
        prob = _validate_numeric(v, 0.0, 1.0, f"{field_name}.distribution[{k}]")
        validated[k] = prob
    total_prob = sum(validated.values())
    if not math.isclose(total_prob, 1.0, abs_tol=0.05):
        raise ExternalIntentApiError(
            f"Field {field_name!r} probability distribution must sum to 1.0 (got {total_prob:.4f})"
        )
    return validated


def _validate_score_levels(levels: Any) -> Dict[int, float]:
    """Strictly validate completeness score levels: dict type, non-empty, int keys in 1..5, probabilities in [0.0, 1.0], and sum(probabilities) == 1.0."""
    if not isinstance(levels, dict) or not levels:
        raise ExternalIntentApiError("Completeness score 'levels' must be a non-empty dictionary.")
    validated: Dict[int, float] = {}
    for k, v in levels.items():
        if isinstance(k, bool):
            raise ExternalIntentApiError(f"Invalid level key in completeness levels: {k!r}")
        try:
            ik = int(k)
        except (ValueError, TypeError):
            raise ExternalIntentApiError(f"Invalid level key in completeness levels: {k!r}")
        if not (1 <= ik <= 5):
            raise ExternalIntentApiError(f"Completeness level key out of range [1, 5]: {ik}")
        prob = _validate_numeric(v, 0.0, 1.0, f"completeness.levels[{ik}]")
        validated[ik] = prob
    total_prob = sum(validated.values())
    if not math.isclose(total_prob, 1.0, abs_tol=0.05):
        raise ExternalIntentApiError(
            f"Completeness score levels distribution must sum to 1.0 (got {total_prob:.4f})"
        )
    return validated


@dataclass(frozen=True)
class DraftEngineeringIntent:
    """Non-executable draft intent contract strictly isolated from FEA solver execution pipelines.

    Used exclusively for exploratory, interactive UI, or diagnostic inspection.
    Any attempt to execute this object directly will be blocked by downstream preflights.
    """
    id: str
    kind: str
    description: str
    analysis_type: str
    unit_system: str
    material: Optional[Dict[str, Any]] = None
    boundary_conditions: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    loads: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    acceptance_criteria: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_executable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExternalIntentApiError(RuntimeError):
    """Raised when external AI intent provider fails or returns invalid payloads in live mode."""


# Backwards compatibility alias
JevApiError = ExternalIntentApiError


class IntentAmbiguityError(ValueError):
    """Raised when natural language prompt is ambiguous or missing required physics definition."""

    def __init__(self, message: str, missing_requirements: List[str], bundle: IntentDecisionBundle):
        super().__init__(message)
        self.missing_requirements = missing_requirements
        self.bundle = bundle


@dataclass(frozen=True)
class IntentRoutingResult:
    """Complete result of intent routing with fail-closed clarification gating."""
    status: str  # "ROUTED", "NEEDS_CLARIFICATION", "BLOCKED"
    intent: Optional[EngineeringIntent]
    decision_bundle: IntentDecisionBundle
    missing_requirements: List[str] = field(default_factory=list)
    clarification_prompt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "intent": asdict(self.intent) if self.intent else None,
            "decision_bundle": self.decision_bundle.to_dict(),
            "missing_requirements": self.missing_requirements,
            "clarification_prompt": self.clarification_prompt,
        }


@dataclass(frozen=True)
class ChoiceJudgment:
    """Discrete choice primitive result."""
    value: str
    confidence: float
    distribution: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class NoulJudgment:
    """Binary probability primitive result (probability of Yes)."""
    probability: float
    is_yes: bool = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "is_yes", self.probability >= 0.5)


@dataclass(frozen=True)
class ScoreJudgment:
    """Continuous or graded score primitive result (1 to 5 scale)."""
    score: float
    levels: Dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True)
class IntentDecisionBundle:
    """Consolidated judgments from intent reasoning."""
    physics_choice: ChoiceJudgment
    unit_system_choice: ChoiceJudgment
    solver_choice: ChoiceJudgment
    is_well_constrained_noul: NoulJudgment
    has_acceptance_criteria_noul: NoulJudgment
    completeness_score: ScoreJudgment
    extracted_parameters: Dict[str, Any] = field(default_factory=dict)
    source_model: str = "offline-rule-engine-v1"
    execution_mode: str = "offline"
    latency_ms: float = 0.0
    inferred_fields: List[str] = field(default_factory=list)
    shadow_diff: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_model": self.source_model,
            "execution_mode": self.execution_mode,
            "latency_ms": self.latency_ms,
            "physics_choice": asdict(self.physics_choice),
            "unit_system_choice": asdict(self.unit_system_choice),
            "solver_choice": asdict(self.solver_choice),
            "is_well_constrained_noul": asdict(self.is_well_constrained_noul),
            "has_acceptance_criteria_noul": asdict(self.has_acceptance_criteria_noul),
            "completeness_score": asdict(self.completeness_score),
            "extracted_parameters": self.extracted_parameters,
            "inferred_fields": self.inferred_fields,
            "shadow_diff": self.shadow_diff,
        }


# Backwards compatibility alias
JevDecisionBundle = IntentDecisionBundle


@runtime_checkable
class ExternalIntentProviderProtocol(Protocol):
    """Protocol for optional external AI decision providers."""

    def judge(self, prompt: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Execute judgment against external provider and return normalized judgments dictionary."""
        ...


class GenericHttpIntentProvider:
    """Vendor-neutral HTTP adapter for optional external AI intent providers.

    Zero proprietary endpoints or models are hardcoded. All service coordinates are
    explicitly injected via constructor parameters or vendor-neutral environment variables.
    """

    MAX_RESPONSE_BYTES: int = 1_048_576  # 1 MB maximum response payload gate

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        payload_builder: Optional[Callable[[str, "GenericHttpIntentProvider"], Dict[str, Any]]] = None,
        response_normalizer: Optional[Callable[[Any], Dict[str, Any]]] = None,
    ):
        raw_endpoint = endpoint or _get_external_config("EXTERNAL_INTENT_API_URL", "INTENT_API_URL", "TYPESAFE_API_URL")
        self.endpoint = raw_endpoint.strip() if raw_endpoint else None

        raw_api_key = api_key or _get_external_config("EXTERNAL_INTENT_API_KEY", "INTENT_API_KEY", "TYPESAFE_API_KEY")
        self.api_key = raw_api_key.strip() if raw_api_key else None

        raw_model = model or _get_external_config("EXTERNAL_INTENT_MODEL", "INTENT_MODEL")
        self.model = raw_model.strip() if raw_model else "external-intent-v1"

        self._payload_builder = payload_builder
        self._response_normalizer = response_normalizer or self._default_response_normalizer

    @staticmethod
    def _default_response_normalizer(raw_data: Any) -> Dict[str, Any]:
        """Normalize provider response into standard engineering judgment dictionary.

        Supports both direct standard judgment dicts and wrapped dicts (e.g. {'answers': ...}).
        """
        if not isinstance(raw_data, dict):
            return {}
        if "answers" in raw_data and isinstance(raw_data["answers"], dict):
            return raw_data["answers"]
        return raw_data

    def is_configured(self) -> bool:
        """Return True only if both endpoint and credentials are provided."""
        return bool(self.endpoint and self.api_key)

    def judge(self, prompt: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Send prompt to the configured HTTP endpoint and return normalized judgments."""
        if not self.endpoint:
            raise ExternalIntentApiError(
                "External intent provider endpoint is not configured. "
                "Explicit endpoint configuration is required."
            )
        if not self.api_key:
            raise ExternalIntentApiError(
                "API credentials are required for external intent provider."
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if self._payload_builder:
            payload = self._payload_builder(prompt, self)
        else:
            payload = {
                "model": self.model,
                "prompt": prompt,
            }

        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_bytes = resp.read(self.MAX_RESPONSE_BYTES + 1)
                if len(raw_bytes) > self.MAX_RESPONSE_BYTES:
                    raise ExternalIntentApiError(
                        f"External intent API response exceeded maximum allowed payload size of {self.MAX_RESPONSE_BYTES} bytes."
                    )
                raw_json = json.loads(raw_bytes.decode("utf-8"))
                normalized = self._response_normalizer(raw_json)
                if not isinstance(normalized, dict):
                    raise ExternalIntentApiError(
                        f"Response normalizer returned {type(normalized).__name__}, expected dict."
                    )
                return normalized
        except urllib.error.HTTPError as http_err:
            try:
                http_err.close()
            except Exception:
                pass
            sanitized_reason = _sanitize_error_message(f"HTTP {http_err.code} error: {http_err.reason}")
            raise ExternalIntentApiError(
                f"External intent API {sanitized_reason}."
            ) from http_err
        except urllib.error.URLError as url_err:
            sanitized_reason = _sanitize_error_message(f"network unreachable: {url_err.reason}")
            raise ExternalIntentApiError(
                f"External intent API {sanitized_reason}"
            ) from url_err
        except Exception as exc:
            if isinstance(exc, ExternalIntentApiError):
                raise
            sanitized_exc = _sanitize_error_message(str(exc))
            raise ExternalIntentApiError(
                f"External intent API invocation failed: {sanitized_exc}"
            ) from exc


class EngineeringIntentRouter:
    """Vendor-neutral Engineering Intent Router supporting deterministic offline rules and optional external AI."""

    PHYSICS_OPTIONS = (
        "linear_static",
        "steady_thermal",
        "transient_dynamic",
        "modal_frequency",
        "contact_frictional",
        "fatigue_damage",
    )

    UNIT_OPTIONS = (
        "MM_N_MPA",
        "SI",
        "IN_LBF_PSI",
    )

    SOLVER_OPTIONS = (
        "abaqus_standard",
        "abaqus_explicit",
    )

    VALID_MODES = ("offline", "live", "shadow")

    def __init__(
        self,
        api_key: Optional[str] = None,
        use_live_api: bool = False,
        mode: Optional[str] = None,
        timeout: float = 5.0,
        api_url: Optional[str] = None,
        external_provider: Optional[Any] = None,
    ):
        raw_key = api_key or _get_external_config("EXTERNAL_INTENT_API_KEY", "INTENT_API_KEY", "TYPESAFE_API_KEY")
        self.api_key = raw_key.strip() if raw_key else None
        raw_url = api_url or _get_external_config("EXTERNAL_INTENT_API_URL", "INTENT_API_URL", "TYPESAFE_API_URL")
        self.api_url = raw_url.strip() if raw_url else None
        self.timeout = timeout

        if mode is not None:
            norm_mode = mode.strip().lower()
            if norm_mode not in self.VALID_MODES:
                raise ValueError(f"Invalid JEV mode / intent mode: {mode!r}. Must be one of {self.VALID_MODES}.")
            self.mode = norm_mode
        elif use_live_api:
            self.mode = "live"
        else:
            env_mode = _get_external_config(
                "EXTERNAL_INTENT_RUN_MODE", "INTENT_RUN_MODE", "TYPESAFE_RUN_MODE"
            )
            if env_mode:
                norm_env = env_mode.strip().lower()
                if norm_env not in self.VALID_MODES:
                    raise ValueError(
                        f"Invalid intent run mode in environment: {env_mode!r}. Must be one of {self.VALID_MODES}."
                    )
                self.mode = norm_env
            else:
                self.mode = "offline"

        self.use_live_api = (self.mode == "live")

        # Configure optional external provider (zero default proprietary endpoints)
        if external_provider is not None:
            self.external_provider = external_provider
        elif self.api_url and self.api_key:
            self.external_provider = GenericHttpIntentProvider(
                endpoint=self.api_url,
                api_key=self.api_key,
            )
        else:
            self.external_provider = None

    def route(
        self, prompt: str, context: Optional[Dict[str, Any]] = None
    ) -> IntentRoutingResult:
        """Route prompt with explicit fail-closed clarification gate and optional engineering context merge."""
        prompt_clean = prompt.strip()
        if not prompt_clean:
            raise ValueError("Engineering intent prompt cannot be empty.")

        decisions = self._evaluate_system_one_judgments(prompt_clean)
        verified_entities: Dict[str, Any] = {
            "evidence_sources": {},
            "evidence_status": {},
            "normalized": {},
        }
        missing = self._detect_missing_engineering_prerequisites(
            prompt_clean, decisions, context=context, verified_entities_out=verified_entities
        )

        if missing:
            clarification_msg = (
                f"Engineering specification is ambiguous, contradictory, or incomplete. Missing prerequisites: {', '.join(missing)}. "
                "Please clarify structural dimensions, boundary conditions, applied loads, material properties, "
                "or resolve conflicting specifications before submitting simulation execution."
            )
            return IntentRoutingResult(
                status="NEEDS_CLARIFICATION",
                intent=None,
                decision_bundle=decisions,
                missing_requirements=missing,
                clarification_prompt=clarification_msg,
            )

        intent = self._build_intent_from_decisions(
            prompt_clean, decisions, context=context, verified_entities=verified_entities
        )
        return IntentRoutingResult(
            status="ROUTED",
            intent=intent,
            decision_bundle=decisions,
            missing_requirements=[],
            clarification_prompt=None,
        )

    def route_prompt_to_intent(
        self,
        prompt: str,
        strict: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[EngineeringIntent, JevDecisionBundle]:
        """Convert natural language requirement into typed EngineeringIntent via judgments.

        Fail-closed contract: If requirements are incomplete or ambiguous (non-ROUTED),
        always raises IntentAmbiguityError. Does NOT allow bypassing execution gates
        even if strict=False is passed.
        """
        res = self.route(prompt, context=context)
        if res.status != "ROUTED":
            raise IntentAmbiguityError(
                res.clarification_prompt or "Incomplete engineering intent.",
                res.missing_requirements,
                res.decision_bundle,
            )

        assert res.intent is not None
        return res.intent, res.decision_bundle

    def create_draft_intent(
        self, prompt: str, context: Optional[Dict[str, Any]] = None
    ) -> Tuple[DraftEngineeringIntent, JevDecisionBundle]:
        """Create an exploratory, non-executable draft intent for inspection or interactive UX.

        Returns DraftEngineeringIntent (with is_executable=False) which is explicitly
        rejected from solver compilation and execution pipelines.
        """
        prompt_clean = prompt.strip()
        if not prompt_clean:
            raise ValueError("Engineering intent prompt cannot be empty.")
        decisions = self._evaluate_system_one_judgments(prompt_clean)
        verified_entities: Dict[str, Any] = {
            "evidence_sources": {},
            "evidence_status": {},
            "normalized": {},
        }
        self._detect_missing_engineering_prerequisites(
            prompt_clean, decisions, context=context, verified_entities_out=verified_entities
        )
        draft = self._build_draft_intent_from_decisions(
            prompt_clean, decisions, context=context, verified_entities=verified_entities
        )
        return draft, decisions

    PHYSICS_PREREQUISITE_RULES: Dict[str, Dict[str, bool]] = {
        "linear_static": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": True,
            "require_loads": True,
            "require_thermal_bcs": False,
        },
        "steady_thermal": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": False,
            "require_loads": False,
            "require_thermal_bcs": True,
        },
        "transient_dynamic": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": True,
            "require_loads": True,
            "require_thermal_bcs": False,
        },
        "modal_frequency": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": True,
            "require_loads": False,
            "require_thermal_bcs": False,
        },
        "contact_frictional": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": True,
            "require_loads": True,
            "require_thermal_bcs": False,
        },
        "fatigue_damage": {
            "require_dimensions": True,
            "require_material": True,
            "require_constraints": True,
            "require_loads": True,
            "require_thermal_bcs": False,
        },
    }

    @staticmethod
    def _has_thermal_boundary_conditions(prompt: str) -> bool:
        """Accurately detect whether prompt specifies thermal boundary conditions.

        Avoid single-character matches (like 'k' in English words such as 'check').
        Matches:
        - Specific temperatures with units: 100C, 0°C, 300 K, 25 degC, etc.
        - Bounded thermal boundary/excitation keywords: 热端, 冷端, 恒温, 绝热, 温差, 对流, 辐射, 热流,
          heat flux, heat source, thermal load, convection, radiation, insulated, adiabatic.
        """
        temp_unit_pattern = re.compile(
            r"(?<![a-zA-Z0-9])\d+(?:\.\d+)?\s*(?:°c|degc|deg\s*c|c|k|kelvin)(?![a-zA-Z0-9])",
            re.IGNORECASE,
        )
        if temp_unit_pattern.search(prompt):
            return True

        prompt_lower = prompt.lower()
        thermal_keywords = (
            "热端",
            "冷端",
            "恒温",
            "绝热",
            "温差",
            "对流",
            "辐射",
            "热流",
            "热源",
            "生热",
            "heat flux",
            "heat source",
            "thermal load",
            "convection",
            "radiation",
            "insulated",
            "adiabatic",
            "ambient temperature",
            "prescribed temperature",
            "fixed temperature",
            "applied temperature",
        )
        return any(kw in prompt_lower for kw in thermal_keywords)

    def _detect_missing_engineering_prerequisites(
        self,
        prompt: str,
        bundle: JevDecisionBundle,
        context: Optional[Dict[str, Any]] = None,
        verified_entities_out: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Verify whether prompt contains all necessary engineering prerequisites via table-driven rules.

        Seamlessly merges model context (existing CAE/INP geometry, materials, boundary conditions)
        to prevent false-positive blocks when evidence already exists in upstream project assets.
        Performs typed structural validation and conflict detection against nominal boolean flags.
        """
        missing = []
        verified_entities: Dict[str, Any] = {
            "evidence_sources": {},
            "evidence_status": {},
            "normalized": {},
        }
        params = bundle.extracted_parameters
        phys = bundle.physics_choice.value
        ctx = context or {}

        # 0. Prompt vs Context Engineering Conflict Detection (Zero silent overriding!)
        conflicts = _detect_entity_conflicts(prompt, params, ctx, phys)
        if conflicts:
            missing.extend(conflicts)

        rules = self.PHYSICS_PREREQUISITE_RULES.get(
            phys,
            {
                "require_dimensions": True,
                "require_material": True,
                "require_constraints": True,
                "require_loads": True,
                "require_thermal_bcs": False,
                "require_acceptance_criteria": True,
            },
        )

        # 1. Geometry Dimensions: Requires explicit entity data (dimensions, geometry, inp_evidence)
        # Rejects nominal boolean flags like has_model: True or has_geometry: True, and unverified/expired evidence!
        dim_ok = False
        p_dim = params.get("dimensions")
        p_dim_ok, p_dim_norm, _ = _validate_dimensions_entity(p_dim)
        if p_dim_ok:
            dim_ok = True
            verified_entities["evidence_sources"]["dimensions"] = "prompt"
            verified_entities["evidence_status"]["dimensions"] = "VERIFIED"
            verified_entities["normalized"]["dimensions"] = p_dim_norm
        else:
            c_dim = ctx.get("dimensions") or ctx.get("geometry") or ctx.get("inp_evidence")
            c_dim_ok, c_dim_norm, _ = _validate_dimensions_entity(c_dim)
            if c_dim_ok:
                dim_ok = True
                src = "inp_evidence" if ("inp_evidence" in ctx and ctx.get("inp_evidence")) else "context"
                verified_entities["evidence_sources"]["dimensions"] = src
                verified_entities["evidence_status"]["dimensions"] = "VERIFIED"
                verified_entities["normalized"]["dimensions"] = c_dim_norm

        if rules["require_dimensions"] and not dim_ok:
            missing.append("missing_geometry_dimensions")

        # 2. Material: Requires structured or named material entity data
        # Rejects nominal boolean flags like has_material: True and unverified/expired/invalid evidence!
        mat_ok = False
        p_mat = params.get("material")
        p_mat_ok, p_mat_norm, _ = _validate_material_entity(p_mat)
        if p_mat_ok:
            mat_ok = True
            verified_entities["evidence_sources"]["material"] = "prompt"
            verified_entities["evidence_status"]["material"] = "VERIFIED"
            verified_entities["normalized"]["material"] = p_mat_norm
        else:
            c_mat = ctx.get("material") or (ctx.get("inp_evidence", {}).get("material") if isinstance(ctx.get("inp_evidence"), dict) else None)
            c_mat_ok, c_mat_norm, _ = _validate_material_entity(c_mat)
            if c_mat_ok:
                mat_ok = True
                src = "inp_evidence" if (isinstance(ctx.get("inp_evidence"), dict) and ctx["inp_evidence"].get("material")) else "context"
                verified_entities["evidence_sources"]["material"] = src
                verified_entities["evidence_status"]["material"] = "VERIFIED"
                verified_entities["normalized"]["material"] = c_mat_norm

        if rules["require_material"] and not mat_ok:
            missing.append("missing_material_specification")

        # 3. Boundary Constraints: Requires NLP well-constrained judgment or structured BC entities
        # Rejects nominal boolean flags like is_well_constrained: True or has_constraints: True!
        bc_ok = False
        if bundle.is_well_constrained_noul.is_yes:
            bc_ok = True
            verified_entities["evidence_sources"]["boundary_conditions"] = "prompt"
            verified_entities["evidence_status"]["boundary_conditions"] = "VERIFIED"
        else:
            c_bc = ctx.get("boundary_conditions") or ctx.get("constraints")
            c_bc_ok, c_bc_norm, _ = _validate_boundary_conditions_entity(c_bc)
            if c_bc_ok:
                bc_ok = True
                verified_entities["evidence_sources"]["boundary_conditions"] = "context"
                verified_entities["evidence_status"]["boundary_conditions"] = "VERIFIED"
                verified_entities["normalized"]["boundary_conditions"] = c_bc_norm

        if rules["require_constraints"] and not bc_ok:
            missing.append("missing_boundary_constraints")

        # 4. Applied Loads / Excitation: Requires extracted loads or structured load entities
        # Rejects nominal boolean flags like has_loads: True!
        load_ok = False
        p_load = params.get("loads")
        p_load_ok, p_load_norm, _ = _validate_loads_entity(p_load, require_region=False)
        if p_load_ok:
            load_ok = True
            verified_entities["evidence_sources"]["loads"] = "prompt"
            verified_entities["evidence_status"]["loads"] = "VERIFIED"
            verified_entities["normalized"]["loads"] = p_load_norm
        else:
            c_load = ctx.get("loads")
            c_load_ok, c_load_norm, _ = _validate_loads_entity(c_load, require_region=True)
            if c_load_ok:
                load_ok = True
                verified_entities["evidence_sources"]["loads"] = "context"
                verified_entities["evidence_status"]["loads"] = "VERIFIED"
                verified_entities["normalized"]["loads"] = c_load_norm

        if rules["require_loads"] and not load_ok:
            missing.append("missing_applied_loads")

        # 5. Thermal Boundary Conditions: Requires explicit thermal conditions in prompt or structured thermal entities
        # Rejects nominal boolean flags like has_thermal_bcs: True!
        thermal_ok = False
        if self._has_thermal_boundary_conditions(prompt):
            thermal_ok = True
            verified_entities["evidence_sources"]["thermal_bcs"] = "prompt"
            verified_entities["evidence_status"]["thermal_bcs"] = "VERIFIED"
        else:
            c_th = ctx.get("thermal_bcs") or ctx.get("thermal_boundary_conditions")
            c_th_ok, c_th_norm, _ = _validate_thermal_bcs_entity(c_th)
            if c_th_ok:
                thermal_ok = True
                verified_entities["evidence_sources"]["thermal_bcs"] = "context"
                verified_entities["evidence_status"]["thermal_bcs"] = "VERIFIED"
                verified_entities["normalized"]["thermal_bcs"] = c_th_norm

        if rules["require_thermal_bcs"] and not thermal_ok:
            missing.append("missing_thermal_boundary_conditions")

        # 6. Acceptance Criteria / Limits
        prompt_lower = prompt.lower()
        unspecified_compliance_check = any(
            w in prompt_lower for w in ("是否达标", "是否合格", "是否满足要求", "compliance", "is compliant")
        )
        if unspecified_compliance_check:
            crit_ok = False
            p_crit = params.get("acceptance_criteria")
            p_crit_ok, p_crit_norm, _ = _validate_acceptance_criteria_entity(p_crit)
            if p_crit_ok:
                crit_ok = True
                verified_entities["evidence_sources"]["acceptance_criteria"] = "prompt"
                verified_entities["evidence_status"]["acceptance_criteria"] = "VERIFIED"
                verified_entities["normalized"]["acceptance_criteria"] = p_crit_norm
            else:
                c_crit = ctx.get("acceptance_criteria")
                c_crit_ok, c_crit_norm, _ = _validate_acceptance_criteria_entity(c_crit)
                if c_crit_ok:
                    crit_ok = True
                    verified_entities["evidence_sources"]["acceptance_criteria"] = "context"
                    verified_entities["evidence_status"]["acceptance_criteria"] = "VERIFIED"
                    verified_entities["normalized"]["acceptance_criteria"] = c_crit_norm

            if not crit_ok:
                missing.append("missing_acceptance_criteria_or_limits")

        if verified_entities_out is not None:
            verified_entities_out.update(verified_entities)

        return missing

    def _evaluate_system_one_judgments(self, prompt: str) -> JevDecisionBundle:
        """Evaluate judgments over input prompt in accordance with the configured execution mode."""
        if self.mode == "live":
            if not self.external_provider:
                raise JevApiError(
                    "External intent provider is not configured. "
                    "Fail-closed: refused to silently degrade to offline engine in strict live mode."
                )
            if hasattr(self.external_provider, "is_configured") and not self.external_provider.is_configured():
                raise JevApiError(
                    "External intent provider is not fully configured (missing endpoint or credentials). "
                    "Fail-closed: refused to silently degrade to offline engine in strict live mode."
                )

            t0 = time.perf_counter()
            try:
                if hasattr(self.external_provider, "judge"):
                    raw_data = self.external_provider.judge(prompt, timeout=self.timeout)
                elif callable(self.external_provider):
                    raw_data = self.external_provider(prompt)
                else:
                    raise JevApiError(f"Unsupported external provider type: {type(self.external_provider).__name__}")
            except JevApiError as jae:
                raise JevApiError(_sanitize_error_message(str(jae))) from jae
            except Exception as exc:
                sanitized_exc = _sanitize_error_message(str(exc))
                raise JevApiError(
                    f"External intent provider request failed in live mode: {sanitized_exc}. "
                    "Fail-closed: refusing silent fallback to offline engine."
                ) from exc

            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return self._parse_provider_response(raw_data, prompt, latency_ms=latency_ms)

        if self.mode == "shadow":
            baseline = self._evaluate_offline_engine(prompt)
            shadow_diff: Dict[str, Any] = {
                "status": "NOT_CONFIGURED",
                "reason": "No external intent provider configured",
            }
            if self.external_provider:
                try:
                    is_conf = (
                        self.external_provider.is_configured()
                        if hasattr(self.external_provider, "is_configured")
                        else True
                    )
                    if not is_conf:
                        shadow_diff = {
                            "status": "NOT_CONFIGURED",
                            "reason": "External intent provider is not fully configured",
                        }
                    else:
                        if hasattr(self.external_provider, "judge"):
                            raw_data = self.external_provider.judge(prompt, timeout=self.timeout)
                        elif callable(self.external_provider):
                            raw_data = self.external_provider(prompt)
                        else:
                            raise ExternalIntentApiError(
                                f"Unsupported provider type: {type(self.external_provider).__name__}"
                            )
                        live_res = self._parse_provider_response(raw_data, prompt, latency_ms=0.0)
                        shadow_diff = self._compute_shadow_diff(baseline, live_res)
                except Exception as shadow_err:
                    root_cause = getattr(shadow_err, "__cause__", None)
                    if isinstance(shadow_err, urllib.error.HTTPError) or (
                        isinstance(shadow_err, ExternalIntentApiError) and "HTTP" in str(shadow_err)
                    ):
                        err_cat = "PROVIDER_HTTP_ERROR"
                    elif (
                        isinstance(shadow_err, urllib.error.URLError)
                        or isinstance(root_cause, urllib.error.URLError)
                        or "network unreachable" in str(shadow_err).lower()
                    ):
                        err_cat = "PROVIDER_NETWORK_ERROR"
                    elif isinstance(shadow_err, ExternalIntentApiError):
                        err_cat = "PROVIDER_CONTRACT_VIOLATION"
                    elif isinstance(shadow_err, TimeoutError) or isinstance(root_cause, TimeoutError):
                        err_cat = "PROVIDER_TIMEOUT"
                    else:
                        err_cat = "PROVIDER_INTERNAL_ERROR"

                    err_msg = str(shadow_err)
                    sanitized_err = _sanitize_error_message(err_msg)
                    shadow_diff = {
                        "status": "LIVE_FAILED",
                        "error_category": err_cat,
                        "error": sanitized_err,
                        "baseline_model": baseline.source_model,
                    }

            return JevDecisionBundle(
                physics_choice=baseline.physics_choice,
                unit_system_choice=baseline.unit_system_choice,
                solver_choice=baseline.solver_choice,
                is_well_constrained_noul=baseline.is_well_constrained_noul,
                has_acceptance_criteria_noul=baseline.has_acceptance_criteria_noul,
                completeness_score=baseline.completeness_score,
                extracted_parameters=baseline.extracted_parameters,
                source_model="offline-shadow-audited",
                execution_mode="shadow",
                latency_ms=baseline.latency_ms,
                inferred_fields=baseline.inferred_fields,
                shadow_diff=shadow_diff,
            )

        # Default offline deterministic execution mode (100% self-contained)
        return self._evaluate_offline_engine(prompt)

    def _compute_shadow_diff(
        self, baseline: JevDecisionBundle, live: JevDecisionBundle
    ) -> Dict[str, Any]:
        """Compute discrepancy metrics between baseline offline rule and live external provider."""
        return {
            "status": "EVALUATED",
            "physics_match": baseline.physics_choice.value == live.physics_choice.value,
            "unit_system_match": baseline.unit_system_choice.value == live.unit_system_choice.value,
            "solver_match": baseline.solver_choice.value == live.solver_choice.value,
            "constrained_match": baseline.is_well_constrained_noul.is_yes == live.is_well_constrained_noul.is_yes,
            "criteria_match": baseline.has_acceptance_criteria_noul.is_yes == live.has_acceptance_criteria_noul.is_yes,
            "baseline_physics": baseline.physics_choice.value,
            "live_physics": live.physics_choice.value,
            "baseline_model": baseline.source_model,
            "live_model": live.source_model,
            "live_latency_ms": live.latency_ms,
        }

    def _parse_provider_response(
        self, data: Dict[str, Any], prompt: str, latency_ms: float = 0.0
    ) -> IntentDecisionBundle:
        """Parse and strictly validate normalized judgments dictionary into typed bundle.

        Accepts either standard normalized dict directly or legacy dict wrapped in 'answers'.
        """
        if not isinstance(data, dict):
            raise ExternalIntentApiError(f"Expected dict response from external provider, got {type(data).__name__}")

        # Support direct normalized dictionary as well as wrapped dictionary
        answers = data.get("answers") if ("answers" in data and isinstance(data.get("answers"), dict)) else data
        if not isinstance(answers, dict) or not answers:
            raise ExternalIntentApiError("Missing or invalid normalized judgments dictionary in external provider response.")

        # 1. Physics Validation
        phys_info = answers.get("physics")
        if not isinstance(phys_info, dict):
            raise ExternalIntentApiError("Missing required 'physics' judgment in external provider response.")
        phys_val = phys_info.get("choice")
        if phys_val not in self.PHYSICS_OPTIONS:
            raise ExternalIntentApiError(f"Invalid physics choice {phys_val!r}. Allowed: {self.PHYSICS_OPTIONS}")
        if "confidence" not in phys_info or phys_info["confidence"] is None:
            raise ExternalIntentApiError("Missing required 'confidence' in physics judgment.")
        phys_conf = _validate_numeric(phys_info["confidence"], 0.0, 1.0, "physics.confidence")

        phys_dist = None
        if phys_info.get("distribution") is not None:
            phys_dist = _validate_distribution(phys_info["distribution"], self.PHYSICS_OPTIONS, "physics")

        # 2. Units Validation
        unit_info = answers.get("units")
        if not isinstance(unit_info, dict):
            raise ExternalIntentApiError("Missing required 'units' judgment in external provider response.")
        unit_val = unit_info.get("choice")
        if unit_val not in self.UNIT_OPTIONS:
            raise ExternalIntentApiError(f"Invalid units choice {unit_val!r}. Allowed: {self.UNIT_OPTIONS}")
        if "confidence" not in unit_info or unit_info["confidence"] is None:
            raise ExternalIntentApiError("Missing required 'confidence' in units judgment.")
        unit_conf = _validate_numeric(unit_info["confidence"], 0.0, 1.0, "units.confidence")

        unit_dist = None
        if unit_info.get("distribution") is not None:
            unit_dist = _validate_distribution(unit_info["distribution"], self.UNIT_OPTIONS, "units")

        # 3. Solver Validation
        solver_info = answers.get("solver")
        if not isinstance(solver_info, dict):
            raise ExternalIntentApiError("Missing required 'solver' judgment in external provider response.")
        solver_val = solver_info.get("choice")
        if solver_val not in self.SOLVER_OPTIONS:
            raise ExternalIntentApiError(f"Invalid solver choice {solver_val!r}. Allowed: {self.SOLVER_OPTIONS}")
        if "confidence" not in solver_info or solver_info["confidence"] is None:
            raise ExternalIntentApiError("Missing required 'confidence' in solver judgment.")
        solver_conf = _validate_numeric(solver_info["confidence"], 0.0, 1.0, "solver.confidence")

        solver_dist = None
        if solver_info.get("distribution") is not None:
            solver_dist = _validate_distribution(solver_info["distribution"], self.SOLVER_OPTIONS, "solver")

        # 4. Well-constrained Validation
        wc_info = answers.get("well_constrained")
        if not isinstance(wc_info, dict):
            raise ExternalIntentApiError("Missing required 'well_constrained' judgment in external provider response.")
        if "probability" not in wc_info or wc_info["probability"] is None:
            raise ExternalIntentApiError("Missing required 'probability' in well_constrained judgment.")
        noul_prob = _validate_numeric(wc_info["probability"], 0.0, 1.0, "well_constrained.probability")

        # 5. Acceptance criteria presence Validation
        crit_info = answers.get("has_acceptance_criteria")
        if not isinstance(crit_info, dict):
            raise ExternalIntentApiError("Missing required 'has_acceptance_criteria' judgment in external provider response.")
        if "probability" not in crit_info or crit_info["probability"] is None:
            raise ExternalIntentApiError("Missing required 'probability' in has_acceptance_criteria judgment.")
        crit_prob = _validate_numeric(crit_info["probability"], 0.0, 1.0, "has_acceptance_criteria.probability")

        # 6. Completeness score Validation
        comp_info = answers.get("completeness")
        if not isinstance(comp_info, dict):
            raise ExternalIntentApiError("Missing required 'completeness' judgment in external provider response.")
        if "score" not in comp_info or comp_info["score"] is None:
            raise ExternalIntentApiError("Missing required 'score' in completeness judgment.")
        score_val = _validate_numeric(comp_info["score"], 1.0, 5.0, "completeness.score")

        comp_levels = None
        if comp_info.get("levels") is not None:
            comp_levels = _validate_score_levels(comp_info["levels"])

        extracted = self._extract_domain_quantities(prompt)
        inferred = [k for k in ("dimensions", "loads", "material", "acceptance_criteria") if k in extracted]

        model_tag = "external-provider-live"
        if hasattr(self.external_provider, "model"):
            model_tag = getattr(self.external_provider, "model")
        elif hasattr(self.external_provider, "__class__"):
            model_tag = self.external_provider.__class__.__name__

        return IntentDecisionBundle(
            physics_choice=ChoiceJudgment(
                phys_val,
                round(phys_conf, 3),
                phys_dist or {phys_val: phys_conf},
            ),
            unit_system_choice=ChoiceJudgment(
                unit_val,
                round(unit_conf, 3),
                unit_dist or {unit_val: unit_conf},
            ),
            solver_choice=ChoiceJudgment(
                solver_val,
                round(solver_conf, 3),
                solver_dist or {solver_val: solver_conf},
            ),
            is_well_constrained_noul=NoulJudgment(round(noul_prob, 3)),
            has_acceptance_criteria_noul=NoulJudgment(round(crit_prob, 3)),
            completeness_score=ScoreJudgment(
                round(score_val, 2),
                comp_levels or {int(round(score_val)): 1.0},
            ),
            extracted_parameters=extracted,
            source_model=model_tag,
            execution_mode="live",
            latency_ms=latency_ms,
            inferred_fields=inferred,
        )

    def _evaluate_offline_engine(self, prompt: str) -> IntentDecisionBundle:
        """High-precision deterministic System One inference engine (100% offline & reproducible)."""
        prompt_lower = prompt.lower()
        extracted = self._extract_domain_quantities(prompt)

        # 1. Physics Choice
        physics_scores: Dict[str, float] = {p: 0.05 for p in self.PHYSICS_OPTIONS}
        if any(w in prompt_lower for w in ("热", "thermal", "temperature", "conduction", "heat", "flux", "温")):
            physics_scores["steady_thermal"] += 0.85
        elif any(w in prompt_lower for w in ("接触", "contact", "friction", "摩擦", "sliding")):
            physics_scores["contact_frictional"] += 0.85
        elif any(w in prompt_lower for w in ("疲劳", "fatigue", "rainflow", "雨流", "damage", "miner")):
            physics_scores["fatigue_damage"] += 0.85
        elif any(w in prompt_lower for w in ("模态", "modal", "frequency", "固有频率", "振型")):
            physics_scores["modal_frequency"] += 0.85
        elif any(w in prompt_lower for w in ("动态", "dynamic", "transient", "冲击", "impact")):
            physics_scores["transient_dynamic"] += 0.85
        else:
            physics_scores["linear_static"] += 0.90

        total_p = sum(physics_scores.values())
        norm_physics = {k: v / total_p for k, v in physics_scores.items()}
        best_phys = max(norm_physics.items(), key=lambda kv: kv[1])
        phys_judgment = ChoiceJudgment(value=best_phys[0], confidence=round(best_phys[1], 3), distribution=norm_physics)

        # 2. Unit System Choice
        unit_scores: Dict[str, float] = {u: 0.1 for u in self.UNIT_OPTIONS}
        if any(w in prompt_lower for w in ("mpa", "mm", "n/mm", "毫米", "牛顿")):
            unit_scores["MM_N_MPA"] += 0.85
        elif any(w in prompt_lower for w in ("pa", "meter", "kg", "米")):
            unit_scores["SI"] += 0.85
        elif any(w in prompt_lower for w in ("psi", "inch", "lbf", "英寸")):
            unit_scores["IN_LBF_PSI"] += 0.85
        else:
            unit_scores["MM_N_MPA"] += 0.80

        total_u = sum(unit_scores.values())
        norm_units = {k: v / total_u for k, v in unit_scores.items()}
        best_unit = max(norm_units.items(), key=lambda kv: kv[1])
        unit_judgment = ChoiceJudgment(value=best_unit[0], confidence=round(best_unit[1], 3), distribution=norm_units)

        # 3. Solver Choice
        if best_phys[0] in ("transient_dynamic",) and ("explicit" in prompt_lower or "高速" in prompt_lower):
            solver_judgment = ChoiceJudgment(value="abaqus_explicit", confidence=0.92, distribution={"abaqus_explicit": 0.92, "abaqus_standard": 0.08})
        else:
            solver_judgment = ChoiceJudgment(value="abaqus_standard", confidence=0.96, distribution={"abaqus_standard": 0.96, "abaqus_explicit": 0.04})

        # 4. Noul: Constraints Sufficiency
        has_negated_constraint = bool(
            re.search(r"(忽略|无需|不用|没有|未|不加|不|不要|bypass|ignore).{0,12}(约束|固定|边界|限制)", prompt_lower)
        )
        is_constrained = False
        if not has_negated_constraint:
            is_constrained = bool(
                any(w in prompt_lower for w in ("固定", "fixed", "encastre", "约束", "clamp", "pinned", "对称"))
            )
        has_negated_load = bool(
            re.search(r"(忽略|无需|不用|没有|未|不加|不|不要|bypass|ignore).{0,12}(载荷|受力|力|压力|load|force)", prompt_lower)
        )
        if has_negated_load:
            extracted.pop("loads", None)
            has_load = False
        else:
            has_load = bool(extracted.get("loads") or any(w in prompt_lower for w in ("载荷", "load", "force", "压力", "pressure", "n", "kn")))
        prob_constrained = 0.95 if is_constrained else (0.20 if has_load else 0.50)
        noul_constrained = NoulJudgment(probability=prob_constrained)

        # 5. Noul: Acceptance Criteria Presence
        has_crit = bool(
            extracted.get("acceptance_criteria")
            or any(
                w in prompt_lower
                for w in (
                    "校核",
                    "check",
                    "verify",
                    "limit",
                    "上限",
                    "不超过",
                    "应力",
                    "挠度",
                    "mises",
                    "displacement",
                    "温度",
                    "temperature",
                    "频率",
                    "frequency",
                )
            )
        )
        noul_crit = NoulJudgment(probability=0.95 if has_crit else 0.35)

        # 6. Score: Intent Completeness (1.0 to 5.0)
        score_val = 1.0
        if best_phys[0]:
            score_val += 1.0
        if extracted.get("dimensions"):
            score_val += 1.0
        if is_constrained and has_load:
            score_val += 1.0
        if has_crit or extracted.get("material"):
            score_val += 1.0
        completeness_judgment = ScoreJudgment(score=round(score_val, 1))

        return JevDecisionBundle(
            physics_choice=phys_judgment,
            unit_system_choice=unit_judgment,
            solver_choice=solver_judgment,
            is_well_constrained_noul=noul_constrained,
            has_acceptance_criteria_noul=noul_crit,
            completeness_score=completeness_judgment,
            extracted_parameters=extracted,
            source_model="offline-rule-engine-v1",
            execution_mode="offline",
            latency_ms=0.0,
            inferred_fields=list(extracted.keys()) + ["physics", "units", "solver"],
        )

    def _extract_domain_quantities(self, prompt: str) -> Dict[str, Any]:
        """Extract engineering entities (dimensions, forces, material, criteria) via typed regex."""
        params: Dict[str, Any] = {}
        prompt_lower = prompt.lower()

        # Criteria: Only extract if explicit numeric threshold is provided (Zero Fabrication)
        criteria = []
        if any(w in prompt_lower for w in ("挠度", "位移", "deflection", "displacement")):
            crit_match = re.search(r"(?:挠度|位移|deflection|displacement)[^\d]*(\d+(?:\.\d+)?)\s*(mm|inch|毫米|m(?![a-zA-Z]))?", prompt, re.IGNORECASE)
            if crit_match and crit_match.group(1):
                limit_val = float(crit_match.group(1))
                unit_val = crit_match.group(2) if crit_match.group(2) else "mm"
                criteria.append({"metric": "tip_displacement", "operator": "<=", "limit": limit_val, "unit": unit_val})
        if any(w in prompt_lower for w in ("应力", "mises", "stress")):
            stress_match = re.search(r"(?:应力|mises|stress)[^\d]*(\d+(?:\.\d+)?)\s*(mpa|kpa|pa|psi|n/mm2)?", prompt, re.IGNORECASE)
            if stress_match and stress_match.group(1):
                limit_val = float(stress_match.group(1))
                unit_val = stress_match.group(2) if stress_match.group(2) else "MPa"
                criteria.append({"metric": "max_mises", "operator": "<=", "limit": limit_val, "unit": unit_val})
        if any(w in prompt_lower for w in ("温度", "temperature")):
            temp_match = re.search(r"(?:温度|temperature)[^\d]*(\d+(?:\.\d+)?)\s*(°c|degc|deg\s*c|c|k|kelvin)?", prompt, re.IGNORECASE)
            if temp_match and temp_match.group(1):
                limit_val = float(temp_match.group(1))
                unit_val = temp_match.group(2) if temp_match.group(2) else "C"
                criteria.append({"metric": "midpoint_temperature", "operator": "==", "limit": limit_val, "unit": unit_val})
        if any(w in prompt_lower for w in ("频率", "frequency", "hz")):
            freq_match = re.search(r"(?:频率|frequency)[^\d]*(\d+(?:\.\d+)?)\s*(hz)?", prompt, re.IGNORECASE)
            if freq_match and freq_match.group(1):
                limit_val = float(freq_match.group(1))
                criteria.append({"metric": "fundamental_frequency", "operator": ">=", "limit": limit_val, "unit": "Hz"})
        if criteria:
            params["acceptance_criteria"] = criteria

        # Dimensions: e.g. 100mm, 500 mm, 2 m
        dim_matches = re.finditer(
            r"(\d+(?:\.\d+)?)\s*(mm|inch|毫米|米|m(?![a-zA-Z]))",
            prompt,
            re.IGNORECASE,
        )
        dims = []
        for m in dim_matches:
            val = float(m.group(1))
            start_pos = max(0, m.start() - 20)
            prefix = prompt[start_pos:m.start()].lower()
            if any(w in prefix for w in ("挠度", "位移", "deflection", "displacement")):
                continue
            dims.append({"value": val, "unit": m.group(2)})
        if dims:
            params["dimensions"] = dims

        # Loads: e.g. 1000N, 50kN, 2.5 MPa (exclude acceptance criteria / allowable stress / modulus prefixes)
        load_matches = re.finditer(
            r"(\d+(?:\.\d+)?)\s*(kn|mpa|kpa|千牛|牛|n(?![a-zA-Z]))",
            prompt,
            re.IGNORECASE,
        )
        loads = []
        for m in load_matches:
            val = float(m.group(1))
            unit_str = m.group(2).upper()
            start_pos = max(0, m.start() - 25)
            prefix = prompt[start_pos:m.start()].lower()
            if any(w in prefix for w in ("应力", "stress", "mises", "校核", "不超过", "小于", "<", "容许", "allowable", "模量", "modulus")):
                continue
            loads.append({"magnitude": val, "unit": unit_str})
        if loads:
            params["loads"] = loads

        # Material detection
        if any(w in prompt_lower for w in ("结构钢", "steel", "钢", "q235")):
            params["material"] = {
                "name": "Structural_Steel",
                "elastic_modulus": 210000.0,
                "poisson_ratio": 0.3,
                "unit": "MPa",
            }
        elif any(w in prompt_lower for w in ("铝", "aluminum", "al6061")):
            params["material"] = {
                "name": "Aluminum_6061",
                "elastic_modulus": 70000.0,
                "poisson_ratio": 0.33,
                "unit": "MPa",
            }
        elif any(w in prompt_lower for w in ("橡胶", "rubber")):
            params["material"] = {
                "name": "Rubber_Hyperelastic",
                "elastic_modulus": 10.0,
                "poisson_ratio": 0.499,
                "unit": "MPa",
            }
        elif any(w in prompt_lower for w in ("elastic", "弹性")):
            params["material"] = {
                "name": "Linear_Elastic",
                "elastic_modulus": 200000.0,
                "poisson_ratio": 0.3,
                "unit": "MPa",
            }

        return params

    def _build_intent_from_decisions(
        self,
        prompt: str,
        bundle: IntentDecisionBundle,
        context: Optional[Dict[str, Any]] = None,
        verified_entities: Optional[Dict[str, Any]] = None,
    ) -> EngineeringIntent:
        """Synthesize EngineeringIntent from judgments and merge upstream model context."""
        phys = bundle.physics_choice.value
        unit_sys = bundle.unit_system_choice.value
        params = bundle.extracted_parameters
        ctx = context or {}
        norm = verified_entities.get("normalized", {}) if verified_entities else {}
        sources = verified_entities.get("evidence_sources", {}) if verified_entities else {}
        statuses = verified_entities.get("evidence_status", {}) if verified_entities else {}

        # Resolve Material: Strictly consume verified normalized entity or extracted prompt parameters (Zero Raw Context Fallback!)
        material = norm.get("material") or params.get("material")

        # Construct boundary conditions tuple: Strictly consume verified normalized entity or prompt judgment
        bcs = []
        if bundle.is_well_constrained_noul.is_yes:
            bcs.append({"type": "encastre", "region": "FixedFace", "dofs": (1, 2, 3, 4, 5, 6)})
        elif norm.get("boundary_conditions"):
            bcs.extend(norm["boundary_conditions"])

        # Construct loads tuple: Strictly consume extracted prompt loads or verified normalized loads
        loads = []
        for ld in params.get("loads", []):
            mag = ld["magnitude"]
            u = ld["unit"]
            if u in ("KN", "千牛"):
                mag *= 1000.0
                loads.append({"type": "concentrated_force", "region": "TipFace", "magnitude": mag, "direction": "-Y"})
            elif u in ("N", "牛"):
                loads.append({"type": "concentrated_force", "region": "TipFace", "magnitude": mag, "direction": "-Y"})
            elif u in ("MPA", "KPA"):
                if any(w in prompt.lower() for w in ("压力", "压强", "pressure")):
                    loads.append({"type": "pressure", "region": "TopFace", "magnitude": mag})
        if not loads and norm.get("loads"):
            loads.extend(norm["loads"])

        # Construct acceptance criteria tuple: Strictly consume verified normalized criteria or prompt criteria
        crit_list = []
        for c in params.get("acceptance_criteria", []):
            crit_list.append({
                "name": c["metric"],
                "value_key": c["metric"],
                "operator": c["operator"],
                "limit": c["limit"],
                "unit": c.get("unit", ""),
            })
        if not crit_list and norm.get("acceptance_criteria"):
            crit_list.extend(norm["acceptance_criteria"])

        # Resolve dimensions: Strictly consume verified normalized dimensions or prompt parameters
        dims = norm.get("dimensions") or params.get("dimensions")

        metadata = {
            "dimensions": dims,
            "jev_source": bundle.source_model,
            "confidence": bundle.physics_choice.confidence,
            "completeness_score": bundle.completeness_score.score,
            "well_constrained": bundle.is_well_constrained_noul.is_yes or bool(bcs),
            "context_merged": bool(ctx),
            "evidence_sources": sources,
            "evidence_status": statuses,
            "routing_gate_passed": True,
            "preflight_required": True,
            "solver_ready": False,
            "execution_gate_note": (
                "Intent routing passed does NOT imply mesh/solver readiness. "
                "Execution remains strictly subject to deterministic Preflight and ODB evidence gates."
            ),
        }

        return EngineeringIntent(
            id=f"INTENT-{bundle.physics_choice.value.upper()}",
            kind=phys,
            description=prompt,
            analysis_type=phys,
            unit_system=unit_sys,
            material=material,
            boundary_conditions=tuple(bcs),
            loads=tuple(loads),
            acceptance_criteria=tuple(crit_list),
            metadata=metadata,
        )

    def _build_draft_intent_from_decisions(
        self,
        prompt: str,
        bundle: IntentDecisionBundle,
        context: Optional[Dict[str, Any]] = None,
        verified_entities: Optional[Dict[str, Any]] = None,
    ) -> DraftEngineeringIntent:
        """Synthesize non-executable DraftEngineeringIntent from judgments and context."""
        phys = bundle.physics_choice.value
        unit_sys = bundle.unit_system_choice.value
        params = bundle.extracted_parameters
        ctx = context or {}
        norm = verified_entities.get("normalized", {}) if verified_entities else {}
        sources = verified_entities.get("evidence_sources", {}) if verified_entities else {}
        statuses = verified_entities.get("evidence_status", {}) if verified_entities else {}

        material = norm.get("material") or params.get("material")

        bcs = []
        if bundle.is_well_constrained_noul.is_yes:
            bcs.append({"type": "encastre", "region": "FixedFace", "dofs": (1, 2, 3, 4, 5, 6)})
        elif norm.get("boundary_conditions"):
            bcs.extend(norm["boundary_conditions"])

        loads = []
        for ld in params.get("loads", []):
            mag = ld["magnitude"]
            u = ld["unit"]
            if u in ("KN", "千牛"):
                mag *= 1000.0
                loads.append({"type": "concentrated_force", "region": "TipFace", "magnitude": mag, "direction": "-Y"})
            elif u in ("N", "牛"):
                loads.append({"type": "concentrated_force", "region": "TipFace", "magnitude": mag, "direction": "-Y"})
            elif u in ("MPA", "KPA"):
                if any(w in prompt.lower() for w in ("压力", "压强", "pressure")):
                    loads.append({"type": "pressure", "region": "TopFace", "magnitude": mag})
        if not loads and norm.get("loads"):
            loads.extend(norm["loads"])

        crit_list = []
        for c in params.get("acceptance_criteria", []):
            crit_list.append({
                "name": c["metric"],
                "value_key": c["metric"],
                "operator": c["operator"],
                "limit": c["limit"],
                "unit": c.get("unit", ""),
            })
        if not crit_list and norm.get("acceptance_criteria"):
            crit_list.extend(norm["acceptance_criteria"])

        dims = norm.get("dimensions") or params.get("dimensions")

        return DraftEngineeringIntent(
            id=f"DRAFT-INTENT-{bundle.physics_choice.value.upper()}",
            kind=phys,
            description=prompt,
            analysis_type=phys,
            unit_system=unit_sys,
            material=material,
            boundary_conditions=tuple(bcs),
            loads=tuple(loads),
            acceptance_criteria=tuple(crit_list),
            metadata={
                "dimensions": dims,
                "source_model": bundle.source_model,
                "confidence": bundle.physics_choice.confidence,
                "completeness_score": bundle.completeness_score.score,
                "well_constrained": bundle.is_well_constrained_noul.is_yes or bool(bcs),
                "context_merged": bool(ctx),
                "evidence_sources": sources,
                "evidence_status": statuses,
            },
            is_executable=False,
        )


# Backwards compatibility alias
JevIntentRouter = EngineeringIntentRouter
