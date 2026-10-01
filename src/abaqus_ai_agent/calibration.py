"""Bounded deterministic parameter identification; no Abaqus model mutation."""
import math
from .contracts.calibration import CalibrationObservation, CalibrationResult, ParameterBound

def _objective(observations, model, parameters):
    residuals, total = [], 0.0
    for observation in observations:
        predicted = float(model(dict(parameters), observation.inputs))
        residual = predicted - float(observation.measured)
        if not math.isfinite(predicted) or not math.isfinite(residual):
            raise ValueError("model returned a non-finite prediction")
        weight = 1.0 / float(observation.uncertainty) ** 2 if observation.uncertainty else 1.0
        total += weight * residual * residual
        residuals.append(residual)
    return total, tuple(residuals)

def identify_parameters(observations, model, bounds, max_iterations=100, tolerance=1e-12):
    if not callable(model): raise TypeError("model must be callable")
    observations, bounds = tuple(observations), tuple(bounds)
    if not observations: raise ValueError("at least one calibration observation is required")
    if not all(isinstance(x, CalibrationObservation) for x in observations): raise TypeError("observations must contain CalibrationObservation")
    if not bounds: raise ValueError("at least one parameter bound is required")
    if not all(isinstance(x, ParameterBound) for x in bounds): raise TypeError("bounds must contain ParameterBound")
    if len({x.name for x in bounds}) != len(bounds): raise ValueError("parameter names must be unique")
    if len(observations) < len(bounds): raise ValueError("observations must be at least as numerous as parameters")
    if int(max_iterations) < 1 or tolerance <= 0: raise ValueError("invalid optimization controls")
    parameters = {x.name: float(x.initial) for x in bounds}
    steps = {x.name: float(x.step) for x in bounds}
    objective, residuals = _objective(observations, model, parameters)
    for iteration in range(1, int(max_iterations)+1):
        improved = False
        for bound in bounds:
            name, current = bound.name, parameters[bound.name]
            for candidate in (max(bound.lower, current-steps[name]), min(bound.upper, current+steps[name])):
                trial = dict(parameters); trial[name] = candidate
                value, trial_residuals = _objective(observations, model, trial)
                if value + tolerance < objective:
                    parameters, objective, residuals = trial, value, trial_residuals
                    improved = True; break
        if not improved:
            if max(steps.values()) <= tolerance:
                return CalibrationResult(dict(parameters), objective, iteration, True, "converged", residuals, ({"method":"coordinate_pattern_search"},))
            for name in steps: steps[name] *= 0.5
    return CalibrationResult(dict(parameters), objective, int(max_iterations), False, "iteration_limit", residuals,
        ({"method":"coordinate_pattern_search"}, {"warning":"local_search_only"}))
