from abaqus_ai_agent.contracts.geometry import ImagePoint
from abaqus_ai_agent.grounding.matching import (
    candidates_from_projected_faces,
    screen_distance_score,
)


def test_screen_distance_score():
    target = ImagePoint(0.5, 0.5)
    assert screen_distance_score(target, (0.5, 0.5)) == 1.0
    assert screen_distance_score(target, (0.65, 0.5), radius=0.15) == 0.0


def test_candidates_keep_missing_evidence_zero():
    target = ImagePoint(0.5, 0.5)
    result = candidates_from_projected_faces(
        target,
        [{"instance": "PART-1-1", "index": 3, "centroid": (1, 2, 3), "screen": (0.5, 0.5)}],
    )
    assert len(result) == 1
    assert result[0].distance_score == 1.0
    assert result[0].visual_score == 0.0
    assert result[0].topology_score == 0.0
    assert result[0].total_score == 0.4
