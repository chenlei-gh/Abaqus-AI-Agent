from abaqus_ai_agent.contracts.convergence import (
    MeshConvergencePoint, MeshConvergencePolicy, evaluate_mesh_convergence
)
from abaqus_ai_agent.execution.batch import BatchExecutor


def test_mesh_convergence_is_deterministic():
    policy = MeshConvergencePolicy(tolerance=0.01, minimum_points=3)
    points = (
        MeshConvergencePoint(10.0, 100.0),
        MeshConvergencePoint(7.0, 101.0),
        MeshConvergencePoint(5.0, 101.4),
    )
    result = evaluate_mesh_convergence(points, policy)
    assert result.converged is True
    assert result.status == "converged"


def test_local_convergence_can_target_critical_region():
    policy = MeshConvergencePolicy(tolerance=0.01, refinement_target="hole_region")
    points = (
        MeshConvergencePoint(4.0, 100.0, "hole_region"),
        MeshConvergencePoint(3.0, 99.5, "hole_region"),
        MeshConvergencePoint(2.0, 99.3, "hole_region"),
        MeshConvergencePoint(2.0, 150.0, "other_region"),
    )
    result = evaluate_mesh_convergence(points, policy)
    assert len(result.points) == 3
    assert result.points[-1].refinement_target == "hole_region"
    assert result.converged


def test_convergence_rejects_duplicate_mesh_sizes():
    points = (
        MeshConvergencePoint(4.0, 100.0, "region"),
        MeshConvergencePoint(3.0, 99.5, "region"),
        MeshConvergencePoint(3.0, 99.4, "region"),
    )
    result = evaluate_mesh_convergence(points, MeshConvergencePolicy(tolerance=0.01))
    assert result.status == "invalid_data"
    assert "duplicate_mesh_size" in result.warnings


def test_convergence_quality_gate_is_evidence_not_convergence():
    policy = MeshConvergencePolicy(
        tolerance=0.01, refinement_target="region", require_quality_pass=True
    )
    points = (
        MeshConvergencePoint(4.0, 100.0, "region", quality_status="pass"),
        MeshConvergencePoint(3.0, 99.5, "region", quality_status="warning"),
        MeshConvergencePoint(2.0, 99.3, "region", quality_status="pass"),
    )
    result = evaluate_mesh_convergence(points, policy)
    assert result.status == "quality_gate_failed"
    assert not result.converged
    assert result.quality_gate_passed is False


def test_batch_executor_keeps_live_session_boundary_explicit():
    executor = BatchExecutor(launcher="abaqus", workdir=".")
    assert executor.launcher == "abaqus"
    assert executor.workdir == "."
