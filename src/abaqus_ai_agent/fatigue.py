"""Deterministic fatigue post-processing for scalar Abaqus stress histories."""

from math import exp, isfinite, log
from typing import Iterable, List, Sequence, Tuple


def stress_range_and_amplitude(stress_a: float, stress_b: float) -> Tuple[float, float]:
    a, b = float(stress_a), float(stress_b)
    if not isfinite(a) or not isfinite(b):
        raise ValueError("stress values must be finite")
    r = abs(b - a)
    return r, r / 2.0


def reversals_to_reversals(points: Sequence[float]) -> Tuple[float, ...]:
    values = tuple(float(x) for x in points)
    if any(not isfinite(x) for x in values):
        raise ValueError("stress history values must be finite")
    if not values:
        return ()
    out = [values[0]]
    for value in values[1:]:
        if value != out[-1]:
            out.append(value)
    if len(out) < 3:
        return tuple(out)
    turning = [out[0]]
    for i in range(1, len(out) - 1):
        if (out[i] - out[i - 1]) * (out[i + 1] - out[i]) < 0:
            turning.append(out[i])
    turning.append(out[-1])
    return tuple(turning)


def rainflow_count(stress_history: Sequence[float]) -> Tuple[Tuple[float, float, float], ...]:
    """Return (range, mean, count); count is 1.0 full or 0.5 half cycle."""
    points = reversals_to_reversals(stress_history)
    if len(points) < 2:
        return ()
    stack: List[float] = []
    cycles = []
    for point in points:
        stack.append(point)
        while len(stack) >= 3:
            x, y, z = stack[-3:]
            r1, r2 = abs(y - x), abs(z - y)
            if r2 < r1:
                break
            cycles.append((r1, (x + y) / 2.0, 0.5 if len(stack) == 3 else 1.0))
            del stack[-3:-1]
    for i in range(len(stack) - 1):
        r, _ = stress_range_and_amplitude(stack[i], stack[i + 1])
        if r > 0:
            cycles.append((r, (stack[i] + stack[i + 1]) / 2.0, 0.5))
    return tuple(cycles)


def goodman_corrected_amplitude(amplitude: float, mean_stress: float, ultimate_strength: float) -> float:
    """Goodman correction for tensile mean stress; non-positive mean is unchanged."""
    sa, sm, sut = map(float, (amplitude, mean_stress, ultimate_strength))
    if not all(isfinite(x) for x in (sa, sm, sut)) or sa < 0 or sut <= 0:
        raise ValueError("amplitude must be non-negative and ultimate strength positive")
    if sm <= 0:
        return sa
    if sm >= sut:
        raise ValueError("positive mean stress must be below ultimate strength")
    return sa / (1.0 - sm / sut)


def reduce_multiaxial_history(history: Iterable[dict], measure: str = "von_mises") -> Tuple[float, ...]:
    """Reduce explicit stress records to a declared scalar fatigue measure."""
    measure = str(measure).lower()
    result = []
    for item in history:
        if not isinstance(item, dict):
            raise ValueError("multiaxial history entries must be mappings")
        key = "mises" if measure == "von_mises" else "normal" if measure == "normal" else None
        if key is None:
            raise ValueError("unsupported multiaxial fatigue measure: %s" % measure)
        if key not in item:
            raise ValueError("%s measure requires '%s'" % (measure, key))
        value = float(item[key])
        if not isfinite(value):
            raise ValueError("stress history values must be finite")
        result.append(value)
    return tuple(result)


def sn_life(alternating_stress: float, material_curve: Sequence[Tuple[float, float]]) -> float:
    """Log-log interpolate cycles to failure within a declared S-N curve."""
    target = float(alternating_stress)
    if not isfinite(target) or target <= 0 or len(material_curve) < 2:
        raise ValueError("positive stress and at least two S-N points are required")
    curve = sorted((float(s), float(n)) for s, n in material_curve)
    if any(s <= 0 or n <= 0 for s, n in curve):
        raise ValueError("S-N curve values must be positive")
    if target < curve[0][0] or target > curve[-1][0]:
        raise ValueError("stress is outside the supplied S-N curve")
    for (s1, n1), (s2, n2) in zip(curve, curve[1:]):
        if s1 <= target <= s2:
            if s1 == s2:
                return n1
            ratio = (target - s1) / (s2 - s1)
            return exp(log(n1) + ratio * (log(n2) - log(n1)))
    return curve[-1][1]
