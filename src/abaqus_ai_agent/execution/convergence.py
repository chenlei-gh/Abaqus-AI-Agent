"""Execution-level mesh convergence evaluation adapters."""

from ..contracts.convergence import (
    MeshConvergencePoint,
    MeshConvergencePolicy,
    MeshConvergenceResult,
    MultiLevelConvergenceResult,
    evaluate_mesh_convergence,
    evaluate_multi_level_mesh_convergence,
)


def evaluate(points, policy):
    """Evaluate already collected mesh/result pairs without running Abaqus."""
    return evaluate_mesh_convergence(points, policy)


def evaluate_multi_level(
    probes,
    stress_key="peak_s11",
    displacement_key="max_u1",
    theory_peak=None,
    tolerance=0.05,
    displacement_tolerance=0.01,
    rf_tolerance_pct=0.01,
):
    """Evaluate multi-level convergence across successive mesh levels."""
    return evaluate_multi_level_mesh_convergence(
        probes=probes,
        stress_key=stress_key,
        displacement_key=displacement_key,
        theory_peak=theory_peak,
        tolerance=tolerance,
        displacement_tolerance=displacement_tolerance,
        rf_tolerance_pct=rf_tolerance_pct,
    )
