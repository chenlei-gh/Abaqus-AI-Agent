import pytest

from abaqus_ai_agent.contracts.geometry import GeometryCandidate, ImagePoint


def test_candidate_score_is_normalized():
    candidate = GeometryCandidate("Face", None, 1, None, None, None, 1.0, 1.0, 1.0)
    assert candidate.total_score == 1.0


def test_candidate_rejects_out_of_range_evidence():
    with pytest.raises(ValueError):
        GeometryCandidate("Face", None, 1, None, None, None, 1.1, 0.0, 0.0)


def test_image_point_rejects_out_of_range():
    with pytest.raises(ValueError):
        ImagePoint(1.01, 0.5)
