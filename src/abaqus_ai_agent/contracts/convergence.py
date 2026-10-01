from dataclasses import dataclass
from typing import Optional, Tuple
import math


@dataclass(frozen=True)
class MeshConvergencePoint:
    mesh_size: float
    result_value: float


@dataclass(frozen=True)
class MeshConvergencePolicy:
    tolerance: float
    minimum_points: int = 3
    relative: bool = True
    required_consecutive: int = 1

    def __post_init__(self):
        if self.tolerance < 0:
            raise ValueError("tolerance must be >= 0")
        if self.minimum_points < 2:
            raise ValueError("minimum_points must be >= 2")
        if self.required_consecutive < 1:
            raise ValueError("required_consecutive must be >= 1")


@dataclass(frozen=True)
class MeshConvergenceResult:
    status: str
    points: Tuple[MeshConvergencePoint, ...]
    final_change: Optional[float]
    converged: bool
    warnings: Tuple[str, ...] = ()


def evaluate_mesh_convergence(points, policy):
    ordered = tuple(sorted(points, key=lambda x: x.mesh_size, reverse=True))
    if any(x.mesh_size <= 0 or not math.isfinite(x.mesh_size) or not math.isfinite(x.result_value) for x in ordered):
        return MeshConvergenceResult("invalid_data", ordered, None, False, ("mesh_size_and_result_must_be_finite",))
    if len(ordered) < policy.minimum_points:
        return MeshConvergenceResult(
            "insufficient_data", ordered, None, False,
            ("minimum_points_not_reached",))
    changes = []
    window = ordered[-(policy.required_consecutive + 1):]
    for a, b in zip(window, window[1:]):
        denominator = max(abs(b.result_value), 1e-30)
        change = abs(b.result_value - a.result_value)
        if policy.relative: change = change / denominator
        changes.append(change)
    change = changes[-1]
    converged = all(value <= policy.tolerance for value in changes)
    warnings = () if converged else ("consecutive_refinement_changes_exceed_tolerance",)
    return MeshConvergenceResult("converged" if converged else "not_converged", ordered, change, converged, warnings)
