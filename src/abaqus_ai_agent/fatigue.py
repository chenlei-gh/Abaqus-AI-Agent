"""Deterministic fatigue post-processing for existing scalar Abaqus stress histories.

Scope is deliberately narrow: Rainflow counting, explicit range/amplitude/mean
semantics, optional Goodman correction, log-log S-N interpolation, and
Palmgren-Miner damage. Multiaxial critical-plane criteria are not implemented.
"""

import math
from typing import Iterable, Sequence

from .contracts.fatigue import FatigueAnalysisIntent, FatigueCycle, FatigueResult


def turning_points(values: Iterable[float]):
    values = tuple(float(v) for v in values)
    if not values:
        raise ValueError("stress history must not be empty")
    if any(not math.isfinite(v) for v in values):
        raise ValueError("stress history must contain finite values")
    points = []
    for value in values:
        if not points or value != points[-1]:
            points.append(value)
    if len(points) < 2:
        raise ValueError("stress history must contain at least two distinct values")
    reversals = [points[0]]
    for i in range(1, len(points) - 1):
        prev, cur, nxt = points[i - 1], points[i], points[i + 1]
        if (cur - prev) * (nxt - cur) < 0:
            reversals.append(cur)
    reversals.append(points[-1])
    return tuple(reversals)


def rainflow_count(values: Iterable[float]):
    """ASTM-style four-point stack counting with explicit half/full weights."""
    rev = turning_points(values)
    stack = []
    cycles = []
    for point in rev:
        stack.append(point)
        while len(stack) >= 3:
            x, y, z = stack[-3:]
            r1, r2 = abs(y - x), abs(z - y)
            if r2 < r1:
                break
            if len(stack) == 3:
                cycles.append((x, y, 0.5))
                stack.pop(0)
            else:
                cycles.append((x, y, 1.0))
                del stack[-3:-1]
    for i in range(len(stack) - 1):
        cycles.append((stack[i], stack[i + 1], 0.5))
    return tuple(cycles)


def _goodman(amplitude, mean, ultimate_strength):
    amplitude = float(amplitude)
    mean = float(mean)
    ultimate_strength = float(ultimate_strength)
    if not math.isfinite(amplitude) or not math.isfinite(mean) or not math.isfinite(ultimate_strength):
        raise ValueError("Goodman inputs must be finite")
    if amplitude <= 0:
        raise ValueError("Goodman amplitude must be positive")
    if ultimate_strength <= 0:
        raise ValueError("ultimate_strength must be positive")

    # fe-safe's measured-signal S-N Goodman implementation uses the normal
    # Goodman line for tensile mean stress and extends the line into the
    # compressive region with half the original slope.
    slope_factor = 1.0 if mean >= 0.0 else 0.5
    denominator = 1.0 - mean / (slope_factor * ultimate_strength)
    if denominator <= 0:
        raise ValueError(
            "Goodman correction is undefined for mean stress at or above "
            "ultimate strength"
        )
    return amplitude / denominator



def mean_stress_corrected_amplitude(amplitude, minimum, maximum, method,
                                    ultimate_strength=None, yield_strength=None,
                                    walker_gamma=None):
    """Convert a cycle to a declared fully-reversed equivalent amplitude."""
    amplitude, minimum, maximum = map(float, (amplitude, minimum, maximum))
    method = (method or "NONE").upper()
    if amplitude <= 0 or not all(math.isfinite(x) for x in (amplitude, minimum, maximum)):
        raise ValueError("cycle stresses must be finite and amplitude must be positive")
    if maximum < minimum:
        minimum, maximum = maximum, minimum
    mean = (maximum + minimum) / 2.0
    if method == "NONE":
        return amplitude
    if method == "GOODMAN":
        return _goodman(amplitude, mean, float(ultimate_strength))
    if method == "GERBER":
        uts = float(ultimate_strength)
        if uts <= 0:
            raise ValueError("ultimate_strength must be positive")
        denominator = 1.0 - (mean / uts) ** 2
        if denominator <= 0:
            raise ValueError("Gerber correction is undefined at or beyond UTS")
        return amplitude / denominator
    if method == "SODERBERG":
        ys = float(yield_strength)
        if ys <= 0:
            raise ValueError("yield_strength must be positive")
        denominator = 1.0 - mean / ys
        if denominator <= 0:
            raise ValueError("Soderberg correction is undefined at or above yield strength")
        return amplitude / denominator
    if method == "WALKER":
        gamma = float(walker_gamma)
        if not 0.0 <= gamma <= 1.0:
            raise ValueError("walker_gamma must be between 0 and 1")
        if maximum <= 0:
            raise ValueError("Walker correction requires positive maximum stress")
        ratio = minimum / maximum
        if ratio >= 1.0:
            raise ValueError("Walker stress ratio must be below 1")
        return amplitude * (2.0 / (1.0 - ratio)) ** (1.0 - gamma)
    raise ValueError("unsupported mean-stress correction: %s" % method)

def goodman_corrected_amplitude(amplitude, mean, ultimate_strength):
    """Return zero-mean-equivalent amplitude using the declared UTS.

    For mean >= 0, this is the conventional Goodman relation:
        Sa0 = Sa / (1 - Sm / UTS)

    For compressive mean stress, the fe-safe measured-signal S-N method
    extends the Goodman line with half the original slope:
        Sa0 = Sa / (1 - Sm / (0.5 * UTS))
    """
    return _goodman(float(amplitude), float(mean), float(ultimate_strength))


def stress_cycle_statistics(minimum, maximum, weight=1.0):
    minimum, maximum, weight = float(minimum), float(maximum), float(weight)
    if maximum < minimum:
        minimum, maximum = maximum, minimum
    if weight not in (0.5, 1.0):
        raise ValueError("cycle weight must be 0.5 or 1.0")
    rng = maximum - minimum
    return (minimum, maximum, (maximum + minimum) / 2.0, rng, rng / 2.0, weight)


def sn_cycles_to_failure(amplitude, material_curve):
    """Log10(stress amplitude) -> Log10(cycles) interpolation."""
    amplitude = float(amplitude)
    curve = sorted((float(s), float(n)) for s, n in material_curve)
    if amplitude <= 0 or len(curve) < 2:
        raise ValueError("positive amplitude and at least two S-N points are required")
    if any(s <= 0 or n <= 0 for s, n in curve):
        raise ValueError("S-N points must be positive")
    for (s1, _), (s2, _) in zip(curve, curve[1:]):
        if s2 <= s1:
            raise ValueError("S-N stress points must be strictly increasing")
    if amplitude > curve[-1][0] or amplitude < curve[0][0]:
        raise ValueError("stress amplitude is outside the declared S-N range")
    for (s1, n1), (s2, n2) in zip(curve, curve[1:]):
        if s1 <= amplitude <= s2:
            x1, x2 = math.log10(s1), math.log10(s2)
            y1, y2 = math.log10(n1), math.log10(n2)
            x = math.log10(amplitude)
            if x2 == x1:
                return n1
            return 10 ** (y1 + (x - x1) * (y2 - y1) / (x2 - x1))
    raise ValueError("unable to interpolate S-N curve")


def evaluate_fatigue_history(values: Sequence[float], intent: FatigueAnalysisIntent, ultimate_strength=None, yield_strength=None, walker_gamma=None):
    """Count cycles, apply declared mean-stress correction, and accumulate Miner damage."""
    if not isinstance(intent, FatigueAnalysisIntent):
        raise TypeError("intent must be FatigueAnalysisIntent")
    raw_cycles = rainflow_count(values)
    if not intent.material_curve:
        raise ValueError("material_curve is required for S-N fatigue")
    correction = (intent.mean_stress_correction or "NONE").upper()
    if correction == "GOODMAN" and ultimate_strength is None:
        raise ValueError("ultimate_strength is required for Goodman correction")
    result_cycles = []
    damage = 0.0
    for index, (a, b, weight) in enumerate(raw_cycles):
        minimum, maximum, mean, rng, amplitude, weight = stress_cycle_statistics(a, b, weight)
        corrected = amplitude
        if correction != "NONE":
            corrected = mean_stress_corrected_amplitude(
                amplitude, minimum, maximum, correction,
                ultimate_strength if ultimate_strength is not None else intent.ultimate_strength,
                yield_strength if yield_strength is not None else intent.yield_strength,
                walker_gamma if walker_gamma is not None else intent.walker_gamma,
            )
        nf = sn_cycles_to_failure(corrected, intent.material_curve)
        damage += weight / nf
        result_cycles.append(FatigueCycle(
            index=index,
            weight=weight,
            minimum=minimum,
            maximum=maximum,
            mean=mean,
            range=rng,
            amplitude=amplitude,
            corrected_amplitude=corrected,
            source_variable=intent.stress_variable.upper(),
        ))
    life = (1.0 / damage) if damage > 0 else None
    return FatigueResult(
        cycles=tuple(result_cycles),
        damage=damage,
        life=life,
        stress_variable=intent.stress_variable.upper(),
        stress_semantics=intent.stress_semantics,
        correction=correction,
        damage_model=intent.damage_model.upper(),
        evidence=(
            {"kind": "cycle_counting", "method": "rainflow", "cycle_count": len(result_cycles)},
            {"kind": "stress_semantics", "variable": intent.stress_variable.upper(), "semantics": intent.stress_semantics},
            {"kind": "damage", "model": intent.damage_model.upper(), "damage": damage},
        ),
        passed=True,
    )
