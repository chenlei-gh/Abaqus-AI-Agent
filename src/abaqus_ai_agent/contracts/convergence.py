"""Mesh-convergence evidence contracts and deterministic evaluation."""

from dataclasses import dataclass
from math import isfinite
from typing import Optional, Tuple


@dataclass(frozen=True)
class MeshConvergencePoint:
    mesh_size: float
    result_value: float
    refinement_target: Optional[str] = None
    quantity: Optional[str] = None
    source: Optional[str] = None
    quality_status: Optional[str] = None

    def __post_init__(self):
        if not isfinite(self.mesh_size) or self.mesh_size <= 0:
            raise ValueError("mesh_size must be a positive finite value")
        if not isfinite(self.result_value):
            raise ValueError("result_value must be finite")
        if self.quality_status is not None and self.quality_status not in (
            "unknown", "pass", "warning", "fail"
        ):
            raise ValueError("invalid quality_status")


@dataclass(frozen=True)
class MeshConvergencePolicy:
    tolerance: float
    minimum_points: int = 3
    relative: bool = True
    refinement_target: Optional[str] = None
    require_quality_pass: bool = False

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
    evidence: Tuple[str, ...] = ()
    quality_gate_passed: Optional[bool] = None


def evaluate_mesh_convergence(points, policy):
    selected = tuple(
        p for p in points
        if policy.refinement_target is None
        or p.refinement_target == policy.refinement_target
    )
    ordered = tuple(sorted(selected, key=lambda x: x.mesh_size, reverse=True))

    if len(ordered) < policy.minimum_points:
        return MeshConvergenceResult(
            "insufficient_data", ordered, None, False,
            ("minimum_points_not_reached",),
            ("convergence_points:%d" % len(ordered),),
            None,
        )

    sizes = tuple(p.mesh_size for p in ordered)
    if len(set(sizes)) != len(sizes):
        return MeshConvergenceResult(
            "invalid_data", ordered, None, False,
            ("duplicate_mesh_size",),
            ("convergence_points:%d" % len(ordered),),
            None,
        )

    quality_gate = None
    warnings = []
    if policy.require_quality_pass:
        quality_gate = all(p.quality_status == "pass" for p in ordered)
        if not quality_gate:
            warnings.append("mesh_quality_gate_not_passed")

    a, b = ordered[-2], ordered[-1]
    change = abs(b.result_value - a.result_value)
    if policy.relative:
        denominator = max(abs(a.result_value), 1e-30)
        change = change / denominator

    evidence = ["convergence_points:%d" % len(ordered)]
    for p in ordered:
        if p.source:
            evidence.append("source:%s" % p.source)
        if p.quantity:
            evidence.append("quantity:%s" % p.quantity)

    converged = change <= policy.tolerance
    if policy.require_quality_pass and not quality_gate:
        converged = False
        status = "quality_gate_failed"
    else:
        status = "converged" if converged else "not_converged"

    return MeshConvergenceResult(
        status, ordered, change, converged,
        tuple(warnings), tuple(evidence), quality_gate,
    )
