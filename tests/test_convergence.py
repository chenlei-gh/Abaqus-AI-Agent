import math
import pytest

from abaqus_ai_agent.contracts.convergence import MeshConvergencePoint, MeshConvergencePolicy, evaluate_mesh_convergence


def test_mesh_convergence_uses_refinement_direction_and_qoi_change():
    points = tuple(MeshConvergencePoint(size, value) for size, value in ((4.0, 100.0), (2.0, 101.0), (1.0, 101.4)))
    result = evaluate_mesh_convergence(points, MeshConvergencePolicy(0.01))
    assert result.status == "converged"
    assert result.converged
    assert result.final_change == pytest.approx((101.4 - 101.0) / 101.4)


def test_mesh_convergence_rejects_nonfinite_mesh_data():
    points = (MeshConvergencePoint(2.0, 1.0), MeshConvergencePoint(1.0, math.nan))
    result = evaluate_mesh_convergence(points, MeshConvergencePolicy(0.01))
    assert result.status == "invalid_data"
    assert not result.converged


def test_mesh_convergence_can_require_consecutive_stable_refinements():
    points = tuple(MeshConvergencePoint(size, value) for size, value in ((8.0, 100.0), (4.0, 101.0), (2.0, 101.5), (1.0, 101.6)))
    result = evaluate_mesh_convergence(points, MeshConvergencePolicy(0.01, required_consecutive=2))
    assert result.status == "converged"


def test_mesh_convergence_requires_enough_points_for_consecutive_window():
    points = tuple(MeshConvergencePoint(size, value) for size, value in ((4.0, 100.0), (2.0, 101.0), (1.0, 101.1)))
    result = evaluate_mesh_convergence(points, MeshConvergencePolicy(0.01, required_consecutive=3))
    assert not result.converged
    assert result.status == "insufficient_data"
