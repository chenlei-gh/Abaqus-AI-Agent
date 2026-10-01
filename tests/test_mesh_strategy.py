from abaqus_ai_agent.contracts.convergence import MeshConvergencePoint, MeshConvergencePolicy, evaluate_mesh_convergence
from abaqus_ai_agent.planning.mesh_strategy import local_seeds_from_geometry_plan
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


def test_geometry_plan_converts_edge_refinement_to_local_seed():
    plan = plan_geometry_mesh(
        {'edges': [{'index': 4, 'size': 8.0}]},
        10.0,
        critical_regions=({'target': 'edges[4]', 'entity_type': 'Edge', 'target_size': 3.0},),
    )
    seeds = local_seeds_from_geometry_plan(plan)
    assert len(seeds) == 1
    assert seeds[0].region_expression == 'edges[4]'
    assert seeds[0].size == 3.0


def test_face_refinement_is_not_silently_materialized_as_seed():
    plan = plan_geometry_mesh(
        {'faces': []},
        10.0,
        critical_regions=({'target': 'faces[2]', 'entity_type': 'Face', 'target_size': 3.0},),
    )
    assert plan.requires_partition
    assert local_seeds_from_geometry_plan(plan) == ()


def test_local_convergence_can_target_critical_region():
    policy = MeshConvergencePolicy(tolerance=0.01, refinement_target='hole_region')
    points = (
        MeshConvergencePoint(4.0, 100.0, 'hole_region'),
        MeshConvergencePoint(3.0, 99.5, 'hole_region'),
        MeshConvergencePoint(2.0, 99.3, 'hole_region'),
        MeshConvergencePoint(2.0, 150.0, 'other_region'),
    )
    result = evaluate_mesh_convergence(points, policy)
    assert len(result.points) == 3
    assert result.points[-1].refinement_target == 'hole_region'
    assert result.converged