from abaqus_ai_agent.contracts.geometry import GeometryCandidate, ImagePoint
from abaqus_ai_agent.grounding.matching import point_in_polygon, polygon_distance_score


def test_point_in_polygon():
    polygon = ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9))
    assert point_in_polygon(ImagePoint(0.5, 0.5), polygon)
    assert not point_in_polygon(ImagePoint(0.95, 0.5), polygon)


def test_polygon_score_prefers_containment():
    polygon = ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9))
    assert polygon_distance_score(ImagePoint(0.5, 0.5), polygon) == 1.0


def test_candidate_accepts_projected_polygon():
    candidate = GeometryCandidate(
        entity_type="Face", name="PART-1-1", index=3,
        centroid=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0),
        area=1.0, distance_score=1.0, visual_score=0.0,
        topology_score=0.0,
        screen_polygon=((0.1, 0.1), (0.2, 0.1), (0.2, 0.2)),
    )
    assert candidate.total_score == 0.4
