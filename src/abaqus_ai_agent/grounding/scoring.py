from typing import Tuple
import math


def weighted_score(distance: float, visual: float, topology: float,
                   weights: Tuple[float, float, float] = (0.4, 0.4, 0.2)) -> float:
    """Combine normalized evidence channels into one score."""
    values = (distance, visual, topology)
    if any(value < 0.0 or value > 1.0 for value in values):
        raise ValueError("scores must be in [0, 1]")
    if abs(sum(weights) - 1.0) > 1e-9:
        raise ValueError("weights must sum to 1")
    return round(math.fsum(value * weight for value, weight in zip(values, weights)), 12)
