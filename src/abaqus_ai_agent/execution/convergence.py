from ..contracts.convergence import evaluate_mesh_convergence


def evaluate(points, policy):
    """Evaluate already collected mesh/result pairs without running Abaqus."""
    return evaluate_mesh_convergence(points, policy)
