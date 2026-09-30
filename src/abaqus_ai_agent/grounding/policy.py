from typing import Sequence
from ..contracts.geometry import GeometryCandidate, GroundingResult
from .ranking import confidence_from_ranked, rank_candidates

DEFAULT_CONFIRMATION_THRESHOLD = 0.80


def resolve(intent_id: str, candidates: Sequence[GeometryCandidate],
            confirmation_threshold: float = DEFAULT_CONFIRMATION_THRESHOLD) -> GroundingResult:
    if not 0.0 <= confirmation_threshold <= 1.0:
        raise ValueError("confirmation threshold must be in [0, 1]")
    ranked = rank_candidates(candidates)
    confidence = confidence_from_ranked(ranked)
    selected = ranked[0] if ranked else None
    return GroundingResult(
        intent_id=intent_id,
        candidates=list(ranked),
        selected=selected,
        confidence=confidence,
        requires_confirmation=(selected is None or confidence < confirmation_threshold),
        evidence=(("ranked_geometry_evidence",) if ranked else ("no_geometry_candidate",)),
    )
