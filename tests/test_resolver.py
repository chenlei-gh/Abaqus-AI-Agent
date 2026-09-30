from abaqus_ai_agent.contracts.geometry import ImagePoint
from abaqus_ai_agent.grounding.resolver import resolve_image_point


def test_resolver_uses_projection_evidence():
    probe = {"faces": [{"instance": "P-1", "index": 3, "centroid": (0,0,0), "normal": (0,0,1), "size": 4, "screen": (0.5,0.5)}]}
    result = resolve_image_point("fixed-1", ImagePoint(0.5,0.5), probe)
    assert result.selected.index == 3
    assert result.confidence > 0.0
