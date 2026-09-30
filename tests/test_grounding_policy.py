from abaqus_ai_agent.contracts.geometry import GeometryCandidate
from abaqus_ai_agent.grounding.policy import resolve


def candidate(d, v, t, index=1):
    return GeometryCandidate("Face", None, index, None, None, None, d, v, t)


def test_empty_candidates_require_confirmation():
    result = resolve("fix-1", [])
    assert result.selected is None
    assert result.requires_confirmation


def test_ambiguous_candidates_require_confirmation():
    result = resolve("fix-1", [candidate(.9,.8,.8), candidate(.89,.8,.8)])
    assert result.selected.index == 1
    assert result.requires_confirmation


def test_strong_single_candidate_can_clear_policy_threshold():
    result = resolve("fix-1", [candidate(1,1,1)])
    assert result.confidence == 1.0
    assert not result.requires_confirmation
