"""Adapters from ODB evidence envelopes to deterministic engineering checks.

These functions deliberately do not discover loads, regions or engineering
thresholds. Callers must provide the engineering assumptions explicitly.
"""

from .engineering_checks import (
    check_declared_load_balance,
    check_energy_ratio,
    sum_reaction_components,
    check_numeric_range,
    check_time_step_evidence,
    check_thermal_mechanical_consistency,
)


def _require_available(evidence, label):
    if not isinstance(evidence, dict):
        raise ValueError("%s evidence must be a dictionary" % label)
    status = evidence.get("status")
    if status != "available":
        raise ValueError("%s evidence is not available: %s" % (label, status))
    return evidence


def reaction_balance_from_field_evidence(
    field_evidence, applied_components, tolerance, unit=""
):
    """Convert RF field evidence into an explicit component balance report."""
    evidence = _require_available(field_evidence, "reaction field")
    values = evidence.get("values") or ()
    if not values:
        raise ValueError("reaction field evidence contains no values")
    reaction = sum_reaction_components(values)
    if reaction["count"] == 0:
        raise ValueError("reaction field evidence contains no numeric values")
    report = check_declared_load_balance(
        applied_components,
        reaction["components"],
        tolerance,
        unit,
    )
    return report, reaction


def energy_ratio_from_history_evidence(
    history_evidence, numerator, denominator, tolerance, name="energy_ratio"
):
    """Convert two history-output series into a deterministic energy check."""
    evidence = _require_available(history_evidence, "history")
    variables = evidence.get("variables") or {}
    numerator_data = variables.get(numerator)
    denominator_data = variables.get(denominator)
    if not numerator_data:
        raise ValueError("missing history variable: %s" % numerator)
    if not denominator_data:
        raise ValueError("missing history variable: %s" % denominator)
    if isinstance(numerator_data, dict):
        if numerator_data.get("status") != "available":
            raise ValueError("history variable unavailable: %s" % numerator)
        numerator_data = numerator_data.get("data")
    if isinstance(denominator_data, dict):
        if denominator_data.get("status") != "available":
            raise ValueError("history variable unavailable: %s" % denominator)
        denominator_data = denominator_data.get("data")
    if not numerator_data or not denominator_data:
        raise ValueError("history variable has no samples")
    try:
        numerator_last = float(numerator_data[-1][1])
        denominator_last = float(denominator_data[-1][1])
    except (IndexError, TypeError, ValueError):
        raise ValueError("history variable data must contain (time, value) pairs")
    check = check_energy_ratio(
        numerator_last, denominator_last, tolerance, name=name
    )
    return check, {"numerator": numerator_last, "denominator": denominator_last}


def numeric_field_sanity_from_field_evidence(
    field_evidence, minimum=None, maximum=None, name="field_result_sanity", unit=""
):
    """Evaluate scalar/vector magnitudes from an available ODB field envelope.

    The caller supplies any engineering bounds. No default physical threshold
    is inferred from the field variable name.
    """
    evidence = _require_available(field_evidence, "field")
    values = evidence.get("values") or ()
    numbers = []
    for item in values:
        data = item.get("data") if isinstance(item, dict) else item
        if isinstance(data, (int, float)):
            numbers.append(float(data))
        elif isinstance(data, (tuple, list)):
            numbers.extend(float(v) for v in data if isinstance(v, (int, float)))
        if isinstance(item, dict):
            for key in ("magnitude", "mises", "maxPrincipal"):
                value = item.get(key)
                if isinstance(value, (int, float)):
                    numbers.append(float(value))
    if not numbers:
        raise ValueError("field evidence contains no numeric values")
    return check_numeric_range(
        name, numbers, minimum=minimum, maximum=maximum, unit=unit
    ), {"count": len(numbers), "minimum": min(numbers), "maximum": max(numbers)}


def time_step_from_history_evidence(
    history_evidence, variable, minimum=None, maximum=None, unit="s"
):
    """Evaluate an explicitly declared time-step history variable."""
    evidence = _require_available(history_evidence, "history")
    variables = evidence.get("variables") or {}
    data = variables.get(variable)
    if isinstance(data, dict):
        if data.get("status") != "available":
            raise ValueError("history variable unavailable: %s" % variable)
        data = data.get("data")
    if not data:
        raise ValueError("missing history variable: %s" % variable)
    try:
        values = tuple(float(pair[1]) for pair in data)
    except (IndexError, TypeError, ValueError):
        raise ValueError("history variable data must contain (time, value) pairs")
    return check_time_step_evidence(values, minimum=minimum, maximum=maximum, unit=unit), {
        "count": len(values), "minimum": min(values), "maximum": max(values)
    }


def thermal_mechanical_consistency_from_field_evidence(
    thermal_evidence, mechanical_evidence, thermal_key, mechanical_key,
    expected_ratio, tolerance, name="thermal_mechanical_consistency"
):
    """Compare two caller-selected scalar field envelopes with an explicit ratio."""
    thermal = _require_available(thermal_evidence, "thermal field")
    mechanical = _require_available(mechanical_evidence, "mechanical field")

    def _first_scalar(evidence, key):
        values = evidence.get("values") or ()
        for item in values:
            if isinstance(item, dict) and isinstance(item.get(key), (int, float)):
                return float(item[key])
            data = item.get("data") if isinstance(item, dict) else item
            if isinstance(data, (int, float)):
                return float(data)
        raise ValueError("field evidence contains no scalar value for %s" % key)

    return check_thermal_mechanical_consistency(
        _first_scalar(thermal, thermal_key),
        _first_scalar(mechanical, mechanical_key),
        expected_ratio,
        tolerance,
        name=name,
    )
