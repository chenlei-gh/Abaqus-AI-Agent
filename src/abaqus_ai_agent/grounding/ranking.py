from typing import Sequence
from ..contracts.geometry import GeometryCandidate


def _rank_key(candidate):
    # Screen containment is already encoded in total_score. When multiple
    # faces occupy the same projected region, prefer a face whose normal points
    # toward the camera, then the nearer camera depth. These are tie-breakers,
    # not additional probability.
    facing = candidate.facing_score
    depth = candidate.camera_depth
    return (
        candidate.total_score,
        facing if facing is not None else -1.0,
        -depth if depth is not None else float("-inf"),
    )


def rank_candidates(candidates: Sequence[GeometryCandidate]) -> list:
    """Return candidates in descending deterministic evidence order."""
    return sorted(candidates, key=_rank_key, reverse=True)


def confidence_from_ranked(candidates: Sequence[GeometryCandidate]) -> float:
    """Convert ranking strength into a policy signal, not proof."""
    if not candidates:
        return 0.0

    ranked = rank_candidates(candidates)
    top = max(0.0, min(1.0, ranked[0].total_score))
    if len(ranked) == 1:
        return top

    second = max(0.0, min(1.0, ranked[1].total_score))
    separation = max(0.0, min(1.0, top - second))
    return max(0.0, min(1.0, 0.75 * top + 0.25 * separation))
