from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class MeshConvergencePoint:
    mesh_size: float
    result_value: float


@dataclass(frozen=True)
class MeshConvergencePolicy:
    tolerance: float
    minimum_points: int = 3
    relative: bool = True

    def __post_init__(self):
        if self.tolerance < 0:
            raise ValueError("tolerance must be >= 0")
        if self.minimum_points < 2:
            raise ValueError("minimum_points must be >= 2")


@dataclass(frozen=True)
class MeshConvergenceResult:
    status: str
    points: Tuple[MeshConvergencePoint, ...]
    final_change: Optional[float]
    converged: bool
    warnings: Tuple[str, ...] = ()


def evaluate_mesh_convergence(points, policy):
    ordered = tuple(sorted(points, key=lambda x: x.mesh_size, reverse=True))
    if len(ordered) < policy.minimum_points:
        return MeshConvergenceResult(
            "insufficient_data", ordered, None, False,
            ("minimum_points_not_reached",))
    a, b = ordered[-2], ordered[-1]
    denominator = max(abs(b.result_value), 1e-30)
    change = abs(b.result_value - a.result_value)
    if policy.relative:
        change = change / denominator
    converged = change <= policy.tolerance
    return MeshConvergenceResult(
        "converged" if converged else "not_converged",
        ordered, change, converged)
