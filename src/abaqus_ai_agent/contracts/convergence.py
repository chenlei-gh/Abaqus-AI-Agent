from dataclasses import dataclass
from typing import Optional, Tuple
import math


_ALLOWED_QOI_TYPES = {
    "DISPLACEMENT", "REACTION_FORCE", "ENERGY", "STRESS",
    "AVERAGED_STRESS", "CONTACT_FORCE", "FAILURE_LOAD", "CUSTOM"
}


@dataclass(frozen=True)
class MeshConvergencePoint:
    mesh_size: float
    result_value: float
    qoi_type: str = "CUSTOM"
    qoi_name: str = "result_value"
    component: Optional[str] = None
    position: Optional[str] = None

    def __post_init__(self):
        qoi_type = str(self.qoi_type).upper()
        object.__setattr__(self, "qoi_type", qoi_type)
        if qoi_type not in _ALLOWED_QOI_TYPES:
            raise ValueError("unsupported mesh convergence QoI type")
        if not math.isfinite(self.mesh_size) or self.mesh_size <= 0:
            raise ValueError("mesh_size must be finite and > 0")
        if not math.isfinite(self.result_value):
            raise ValueError("result_value must be finite")
        if qoi_type == "CUSTOM" and not str(self.qoi_name).strip():
            raise ValueError("CUSTOM mesh convergence QoI requires qoi_name")


@dataclass(frozen=True)
class MeshConvergencePolicy:
    tolerance: float
    minimum_points: int = 3
    relative: bool = True
    required_consecutive: int = 1

    def __post_init__(self):
        if not math.isfinite(self.tolerance) or self.tolerance < 0:
            raise ValueError("tolerance must be finite and >= 0")
        if self.minimum_points < 2:
            raise ValueError("minimum_points must be >= 2")
        if self.required_consecutive < 1:
            raise ValueError("required_consecutive must be >= 1")
        if self.minimum_points < self.required_consecutive + 1:
            raise ValueError("minimum_points must cover required consecutive refinements")


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
    qoi_keys = {(x.qoi_type, x.qoi_name, x.component, x.position) for x in ordered}
    if len(qoi_keys) != 1:
        return MeshConvergenceResult(
            "invalid_data", ordered, None, False,
            ("convergence_points_must_share_same_qoi",))
    changes = []
    window = ordered[-(policy.required_consecutive + 1):]
    for a, b in zip(window, window[1:]):
        denominator = max(abs(b.result_value), 1e-30)
        change = abs(b.result_value - a.result_value)
        if policy.relative:
            change = change / denominator
        changes.append(change)
    change = changes[-1]
    converged = all(value <= policy.tolerance for value in changes)
    warnings = () if converged else ("consecutive_refinement_changes_exceed_tolerance",)
    return MeshConvergenceResult("converged" if converged else "not_converged", ordered, change, converged, warnings)
