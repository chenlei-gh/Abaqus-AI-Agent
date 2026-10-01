import pytest
from abaqus_ai_agent.contracts.mesh_strategy import MeshRefinementRequest
from abaqus_ai_agent.planning.mesh_strategy import plan_geometry_mesh

def test_face_refinement_is_partition_candidate():
    plan = plan_geometry_mesh({"faces": [], "edges": []}, 10.0, (
        {"target": "faces[3:4]", "entity_type": "Face", "target_size": 3.0, "reason": "load_introduction"},
    ))
    assert plan.refinements[0].method == "partition_then_seed"
    assert plan.requires_partition

def test_small_feature_is_review_only():
    plan = plan_geometry_mesh({"edges": [{"index": 4, "size": 2.0}], "faces": []}, 4.0)
    assert plan.feature_reviews[0].method == "virtual_topology_review"
    assert plan.warnings

def test_edge_refinement_uses_local_seed():
    plan = plan_geometry_mesh({"edges": [], "faces": []}, 10.0, (
        {"target": "part.edges[3:4]", "entity_type": "Edge", "reason": "fillet_resolution"},
    ))
    assert plan.refinements[0].method == "local_seed"
    assert not plan.refinements[0].requires_partition

def test_invalid_request():
    with pytest.raises(ValueError):
        MeshRefinementRequest("Edge[1]", "Edge", 0.0, "x")
