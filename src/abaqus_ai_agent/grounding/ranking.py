from typing import Sequence
from ..contracts.geometry import GeometryCandidate


def rank_candidates(candidates: Sequence[GeometryCandidate]) -> list:
    return sorted(candidates, key=lambda c: c.total_score, reverse=True)


def confidence_from_ranked(candidates: Sequence[GeometryCandidate]) -> float:
    if not candidates:
        return 0.0
    ranked = rank_candidates(candidates)
    top = max(0.0, min(1.0, ranked[0].total_score / 3.0))
    if len(ranked) == 1:
        return top
    second = max(0.0, min(1.0, ranked[1].total_score / 3.0))
    separation = max(0.0, min(1.0, top - second))
    return max(0.0, min(1.0, 0.75 * top + 0.25 * separation))
