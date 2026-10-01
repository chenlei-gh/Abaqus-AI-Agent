"""Adapters from ODB evidence envelopes to deterministic engineering checks.

These functions deliberately do not discover loads, regions or engineering
thresholds. Callers must provide the engineering assumptions explicitly.
"""

from .engineering_checks import (
    check_declared_load_balance,
    check_energy_ratio,
    sum_reaction_components,
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
