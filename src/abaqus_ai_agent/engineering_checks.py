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
