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


def test_batch_executor_keeps_live_session_boundary_explicit():
    executor = BatchExecutor(launcher="abaqus", workdir=".")
    assert executor.launcher == "abaqus"
    assert executor.workdir == "."
