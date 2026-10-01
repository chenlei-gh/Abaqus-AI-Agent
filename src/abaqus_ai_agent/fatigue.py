"""Deterministic fatigue post-processing for existing Abaqus stress histories.

This module does not run a fatigue solver. It consumes an already extracted
stress history and an explicit S-N curve and returns a traceable Miner-damage
estimate.
"""
import math

from .contracts.fatigue import FatigueAnalysisIntent, FatigueResult


def _turning_points(values):
    values = tuple(float(v) for v in values)
    if len(values) < 2:
        raise ValueError("stress history requires at least two values")
    points = [values[0]]
    for value in values[1:-1]:
        if value != points[-1]:
            points.append(value)
    if values[-1] != points[-1]:
        points.append(values[-1])
    if len(points) < 2:
        raise ValueError("stress history has no variation")
    return tuple(points)


def stress_ranges(stress_history):
    """Return deterministic adjacent turning-point stress ranges.

    This is a conservative range-counting primitive, not a claim of full
    ASTM rainflow implementation.
    """
    points = _turning_points(stress_history)
    return tuple(abs(points[i + 1] - points[i]) for i in range(len(points) - 1) if points[i + 1] != points[i])


def _sn_life(stress_range, curve):
    points = sorted((float(n), float(s)) for n, s in curve if n > 0 and s > 0)
    if len(points) < 2:
        raise ValueError("material_curve requires at least two positive points")
    stress = float(stress_range)
    if stress <= 0:
        return math.inf
    points_by_stress = sorted(((s, n) for n, s in points), key=lambda item: item[0])
    if stress >= points_by_stress[-1][0]:
        return points_by_stress[-1][1]
    if stress <= points_by_stress[0][0]:
        return points_by_stress[0][1]
    for (s0, n0), (s1, n1) in zip(points_by_stress, points_by_stress[1:]):
        if s0 <= stress <= s1:
            x0, x1 = math.log10(s0), math.log10(s1)
            y0, y1 = math.log10(n0), math.log10(n1)
            y = y0 + (math.log10(stress) - x0) * (y1 - y0) / (x1 - x0)
            return 10.0 ** y
    raise ValueError("stress range is outside S-N curve")


def evaluate_fatigue_history(intent, stress_history, cycles_per_range=1.0, source=""):
    """Evaluate Miner damage from an explicit existing stress history."""
    if not isinstance(intent, FatigueAnalysisIntent):
        raise TypeError("intent must be FatigueAnalysisIntent")
    if intent.method.upper() != "S_N":
        raise ValueError("only S_N post-processing is currently implemented")
    if intent.mean_stress_correction:
        raise ValueError("mean_stress_correction is not implemented; fail closed")
    if cycles_per_range <= 0:
        raise ValueError("cycles_per_range must be positive")
    ranges = stress_ranges(stress_history)
    damage = 0.0
    for stress_range in ranges:
        life = _sn_life(stress_range, intent.material_curve)
        if math.isfinite(life):
            damage += float(cycles_per_range) / life
    evaluated = float(len(ranges)) * float(cycles_per_range)
    predicted_life = math.inf if damage == 0 else evaluated / damage
    if intent.cycles is not None:
        predicted_life = min(predicted_life, float(intent.cycles))
    return FatigueResult(
        name=intent.name,
        cycles_evaluated=evaluated,
        damage=damage,
        predicted_life_cycles=predicted_life,
        method=intent.method.upper(),
        damage_model=intent.damage_model.upper(),
        source=source,
    )
