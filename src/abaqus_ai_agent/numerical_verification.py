from .contracts.numerical import NumericalVerificationResult


def verify_series(name, values, tolerance):
    values = tuple(float(v) for v in values)
    if len(values) < 2:
        return NumericalVerificationResult(
            name, "insufficient_data", float("inf"), float(tolerance), values,
            "at least two points are required")
    reference = max(abs(values[-1]), 1e-30)
    error = abs(values[-1] - values[-2]) / reference
    status = "converged" if error <= tolerance else "not_converged"
    return NumericalVerificationResult(
        name, status, error, float(tolerance), values,
        "successive-point relative change")
