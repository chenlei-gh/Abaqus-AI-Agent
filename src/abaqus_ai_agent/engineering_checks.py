from .contracts.engineering_checks import EngineeringCheck, EngineeringCheckReport


# Declared check families only; numerical limits remain problem-specific.
STANDARD_ENGINEERING_CHECKS = {
    "static": (
        "global_equilibrium",
        "displacement_sanity",
        "stress_result_sanity",
        "energy_sanity",
    ),
    "dynamic": (
        "energy_balance",
        "kinetic_internal_energy",
        "time_step_evidence",
    ),
    "contact": (
        "contact_state",
        "contact_opening_pressure",
        "contact_reaction_consistency",
    ),
    "thermal": (
        "temperature_result_sanity",
        "thermal_energy_sanity",
    ),
    "coupled": (
        "temperature_result_sanity",
        "displacement_sanity",
        "thermal_mechanical_consistency",
    ),
}


def relative_error(actual, expected):
    denominator = max(abs(float(expected)), 1e-30)
    return abs(float(actual) - float(expected)) / denominator


def check_balance(name, actual, expected, tolerance, unit=""):
    error = relative_error(actual, expected)
    return EngineeringCheck(
        name=name,
        passed=error <= tolerance,
        actual=float(actual),
        expected=float(expected),
        tolerance=float(tolerance),
        unit=unit,
        message="relative_error=%g" % error,
    )


def evaluate_checks(checks, warnings=()):
    return EngineeringCheckReport(tuple(checks), tuple(warnings))


def check_load_balance(applied_load, reaction_load, tolerance, unit=""):
    """Check scalar equilibrium using the convention applied + reaction = 0."""
    return check_balance(
        "global_load_balance",
        float(reaction_load),
        -float(applied_load),
        tolerance,
        unit,
    )


def check_energy_ratio(numerator, denominator, tolerance, name="energy_ratio"):
    """Check an energy component ratio against a declared engineering limit."""
    denominator = abs(float(denominator))
    if denominator <= 1e-30:
        return EngineeringCheck(
            name, False, float(numerator), 0.0, float(tolerance), "",
            "zero energy denominator"
        )
    ratio = abs(float(numerator)) / denominator
    return EngineeringCheck(
        name, ratio <= float(tolerance), ratio, 0.0, float(tolerance),
        "ratio", "ratio=%g" % ratio
    )


def sum_reaction_components(field_values):
    """Sum RF field values explicitly; does not infer the applied load."""
    totals = [0.0, 0.0, 0.0]
    count = 0
    for item in field_values or ():
        data = item.get("data") if isinstance(item, dict) else item
        if isinstance(data, (int, float)):
            data = (data,)
        if not isinstance(data, (tuple, list)):
            continue
        for i in range(min(3, len(data))):
            if isinstance(data[i], (int, float)):
                totals[i] += float(data[i])
        if data:
            count += 1
    return {"components": tuple(totals), "count": count}


def check_declared_load_balance(applied_components, reaction_components,
                                tolerance, unit=""):
    """Compare declared applied-load components with extracted RF resultants.

    The engineering convention is:
        sum(applied) + sum(reaction) = 0

    Applied components must be supplied explicitly by the caller. This
    function never infers loads from the ODB or from model names.
    """
    if len(applied_components) != len(reaction_components):
        raise ValueError("applied/reaction component lengths must match")
    checks = []
    for i, (applied, reaction) in enumerate(
            zip(applied_components, reaction_components), 1):
        checks.append(check_balance(
            "global_load_balance_RF%d" % i,
            reaction,
            -float(applied),
            tolerance,
            unit,
        ))
    return evaluate_checks(tuple(checks))
