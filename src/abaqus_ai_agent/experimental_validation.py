"""Deterministic comparison of measured and simulated quantities.

This is validation, not calibration: the module never changes a model,
identifies parameters, or invents measurement uncertainty.
"""

import math

from .contracts.experimental_validation import (
    ExperimentalObservation,
    ExperimentalValidationReport,
    ExperimentalValidationResult,
)


def validate_observations(observations):
    results = []
    for observation in observations:
        if not isinstance(observation, ExperimentalObservation):
            raise TypeError("observations must contain ExperimentalObservation")
        error = abs(float(observation.simulated) - float(observation.measured))
        denominator = abs(float(observation.measured))
        relative_error = error / denominator if denominator > 0.0 else None
        passed = error <= float(observation.tolerance)
        # Measurement uncertainty is recorded as evidence; it does not
        # silently relax the caller-declared acceptance tolerance.
        if not all(math.isfinite(value) for value in (
            float(observation.measured), float(observation.simulated), error
        )):
            passed = False
        results.append(ExperimentalValidationResult(
            name=observation.name,
            measured=float(observation.measured),
            simulated=float(observation.simulated),
            error=error,
            relative_error=relative_error,
            tolerance=float(observation.tolerance),
            passed=passed,
            unit=observation.unit,
            uncertainty=observation.uncertainty,
            source=observation.source,
        ))
    return ExperimentalValidationReport(tuple(results))


def observations_from_mappings(items):
    return tuple(
        ExperimentalObservation(
            name=item["name"],
            measured=item["measured"],
            simulated=item["simulated"],
            tolerance=item["tolerance"],
            unit=item.get("unit", ""),
            uncertainty=item.get("uncertainty"),
            source=item.get("source", ""),
        )
        for item in items
    )
