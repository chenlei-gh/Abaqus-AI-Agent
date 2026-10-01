from .contracts.engineering_checks import EngineeringCheck, EngineeringCheckReport


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
    """Check global applied-load/reaction equilibrium from extracted ODB evidence."""
    return check_balance("global_load_balance", reaction_load, applied_load, tolerance, unit)


def check_energy_ratio(numerator, denominator, tolerance, name="energy_ratio"):
    """Check an energy component ratio against a declared engineering limit."""
    denominator = abs(float(denominator))
    if denominator <= 1e-30:
        return EngineeringCheck(name, False, float(numerator), 0.0, float(tolerance), "", "zero energy denominator")
    ratio = abs(float(numerator)) / denominator
    return EngineeringCheck(name, ratio <= float(tolerance), ratio, 0.0, float(tolerance), "ratio", "ratio=%g" % ratio)
