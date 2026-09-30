from abaqus_ai_agent.contracts.geometry import ImagePoint
from abaqus_ai_agent.grounding.resolver import resolve_image_point


def test_resolver_uses_projection_evidence():
    probe = {"faces": [{"instance": "P-1", "index": 3, "centroid": (0,0,0), "normal": (0,0,1), "size": 4, "screen": (0.5,0.5)}]}
    result = resolve_image_point("fixed-1", ImagePoint(0.5,0.5), probe)
    assert result.selected.index == 3
    assert result.confidence > 0.0



def test_region_expression_uses_point_not_integer_id():
    from abaqus_ai_agent.grounding.resolver import region_expression, target_reference
    from abaqus_ai_agent.contracts.geometry import GeometryCandidate
    candidate = GeometryCandidate(
        entity_type="Face", name="P-1", index=3,
        centroid=(1.0, 2.0, 3.0), normal=(0.0, 0.0, 1.0), area=1.0,
        distance_score=1.0, visual_score=0.5, topology_score=0.5)
    expression = region_expression(target_reference(candidate))
    assert expression == "instance.faces.findAt(((1.0, 2.0, 3.0),))"
    assert "[3]" not in expression


def test_grouped_selection_preserves_multiple_targets():
    from abaqus_ai_agent.grounding.resolver import selection_from_candidates, selection_expressions
    from abaqus_ai_agent.contracts.geometry import GeometryCandidate
    def make(index):
        return GeometryCandidate(
            entity_type="Face", name="P-1", index=index,
            centroid=(float(index), 2.0, 3.0), normal=(0.0, 0.0, 1.0), area=1.0,
            distance_score=1.0, visual_score=0.5, topology_score=0.5)
    selection = selection_from_candidates([make(1), make(2)])
    assert len(selection.targets) == 2
    assert selection_expressions(selection) == (
        "instance.faces.findAt(((1.0, 2.0, 3.0),))",
        "instance.faces.findAt(((2.0, 2.0, 3.0),))",
    )


def test_grouped_selection_rejects_mixed_entity_types():
    from abaqus_ai_agent.grounding.resolver import selection_from_candidates
    from abaqus_ai_agent.contracts.geometry import GeometryCandidate
    def make(entity_type):
        return GeometryCandidate(
            entity_type=entity_type, name="P-1", index=1,
            centroid=(1.0, 2.0, 3.0), normal=None, area=1.0,
            distance_score=1.0, visual_score=0.5, topology_score=0.5)
    try:
        selection_from_candidates([make("Face"), make("Edge")])
    except ValueError as exc:
        assert "mixed entity types" in str(exc)
    else:
        raise AssertionError("mixed entity types must be rejected")


def test_native_region_expression_groups_same_instance_targets():
    from abaqus_ai_agent.grounding.resolver import native_region_expression, selection_from_candidates
    from abaqus_ai_agent.contracts.geometry import GeometryCandidate
    def make(x):
        return GeometryCandidate(
            entity_type="Face", name="P-1", index=1,
            centroid=(float(x), 2.0, 3.0), normal=(0.0, 0.0, 1.0), area=1.0,
            distance_score=1.0, visual_score=0.5, topology_score=0.5)
    selection = selection_from_candidates([make(1), make(2)])
    assert native_region_expression(selection) == "instance.faces.findAt(((1.0, 2.0, 3.0),), ((2.0, 2.0, 3.0),))"


def test_native_region_expression_rejects_cross_instance_temporary_selection():
    from abaqus_ai_agent.grounding.resolver import native_region_expression
    from abaqus_ai_agent.contracts.geometry import GeometrySelection
    selection = GeometrySelection(
        targets=(
            {"instance": "A-1", "entity_type": "Face", "point": (1,2,3)},
            {"instance": "B-1", "entity_type": "Face", "point": (4,5,6)},
        ),
        entity_type="Face")
    try:
        native_region_expression(selection)
    except ValueError as exc:
        assert "cross-instance" in str(exc)
    else:
        raise AssertionError("cross-instance temporary region must be rejected")
