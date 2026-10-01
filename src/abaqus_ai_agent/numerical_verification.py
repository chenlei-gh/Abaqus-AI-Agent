from .contracts.numerical import NumericalVerificationResult


def verify_series(name, values, tolerance):
    """Check successive result changes and return explicit verification method."""
    values = tuple(float(v) for v in values)
    tolerance = float(tolerance)
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    if len(values) < 2:
        return NumericalVerificationResult(
            name=name,
            status="insufficient_data",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="successive_relative_change",
            message="at least two points are required",
        )
    reference = max(abs(values[-1]), 1e-30)
    error = abs(values[-1] - values[-2]) / reference
    status = "converged" if error <= tolerance else "not_converged"
    return NumericalVerificationResult(
        name=name,
        status=status,
        error=error,
        tolerance=tolerance,
        points=values,
        method="successive_relative_change",
        message="relative_change=%g" % error,
    )
