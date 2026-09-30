import pytest
from abaqus_ai_agent.contracts.geometry import ViewProjection
from abaqus_ai_agent.grounding.projection import project_point


def test_parallel_projection_center():
    view = ViewProjection("v", "PARALLEL", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0))
    p = project_point((0, 0, 0), view, 2.0, 2.0)
    assert p.x == pytest.approx(0.5)
    assert p.y == pytest.approx(0.5)


def test_parallel_projection_right_and_up():
    view = ViewProjection("v", "PARALLEL", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0))
    right = project_point((1, 0, 0), view, 2.0, 2.0)
    up = project_point((0, 1, 0), view, 2.0, 2.0)
    assert right.x == pytest.approx(1.0)
    assert right.y == pytest.approx(0.5)
    assert up.x == pytest.approx(0.5)
    assert up.y == pytest.approx(0.0)


def test_perspective_is_not_claimed_supported_yet():
    view = ViewProjection("v", "PERSPECTIVE", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0))
    with pytest.raises(NotImplementedError):
        project_point((0, 0, 0), view, 2.0, 2.0)
