import math

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


def verify_richardson(name, values, refinement_ratio, tolerance, safety_factor=1.25):
    """Estimate observed order and fine-grid GCI from three refinements.

    Values must be ordered coarse -> medium -> fine and correspond to a
    constant mesh/time refinement ratio. This is numerical evidence only; it
    does not decide whether a mesh is physically adequate or whether a
    singularity invalidates the convergence interpretation.
    """
    values = tuple(float(v) for v in values)
    ratio = float(refinement_ratio)
    tolerance = float(tolerance)
    safety_factor = float(safety_factor)
    if ratio <= 1.0:
        raise ValueError("refinement_ratio must be > 1")
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    if safety_factor <= 0:
        raise ValueError("safety_factor must be > 0")
    if len(values) < 3:
        return NumericalVerificationResult(
            name=name,
            status="insufficient_data",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="richardson_gci",
            message="three refinement levels are required",
        )

    coarse, medium, fine = values[-3:]
    d21 = medium - coarse
    d32 = fine - medium
    if abs(d21) <= 1e-30 or abs(d32) <= 1e-30:
        return NumericalVerificationResult(
            name=name,
            status="invalid_convergence",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="richardson_gci",
            message="zero difference between refinement levels",
        )

    quotient = abs(d32 / d21)
    if quotient <= 0.0:
        return NumericalVerificationResult(
            name=name,
            status="invalid_convergence",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="richardson_gci",
            message="invalid refinement difference ratio",
        )

    observed_order = -math.log(quotient) / math.log(ratio)
    if observed_order <= 0.0 or not math.isfinite(observed_order):
        return NumericalVerificationResult(
            name=name,
            status="invalid_convergence",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="richardson_gci",
            message="observed order is not positive",
            observed_order=observed_order,
        )

    denominator = ratio ** observed_order - 1.0
    if abs(denominator) <= 1e-30:
        return NumericalVerificationResult(
            name=name,
            status="invalid_convergence",
            error=float("inf"),
            tolerance=tolerance,
            points=values,
            method="richardson_gci",
            message="GCI denominator is zero",
            observed_order=observed_order,
        )

    reference = max(abs(fine), 1e-30)
    extrapolated = fine + (fine - medium) / denominator
    gci = safety_factor * abs((fine - medium) / reference) / abs(denominator)
    status = "converged" if gci <= tolerance else "not_converged"
    return NumericalVerificationResult(
        name=name,
        status=status,
        error=gci,
        tolerance=tolerance,
        points=values,
        method="richardson_gci",
        message="observed_order=%g gci=%g" % (observed_order, gci),
        observed_order=observed_order,
        extrapolated_value=extrapolated,
        gci=gci,
    )
