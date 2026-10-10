"""Mesh-convergence evidence contracts and deterministic evaluation."""

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class MeshConvergencePoint:
    mesh_size: float
    result_value: float
    refinement_target: Optional[str] = None
    quantity: Optional[str] = None
    source: Optional[str] = None
    quality_status: Optional[str] = None
    singularity_suspected: bool = False

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
    singularity_suspected: bool = False


def evaluate_mesh_convergence(points, policy):
    selected = tuple(
        p for p in points
        if policy.refinement_target is None
        or p.refinement_target == policy.refinement_target
    )
    ordered = tuple(sorted(selected, key=lambda x: x.mesh_size, reverse=True))
    singularity_suspected = any(p.singularity_suspected for p in ordered)

    if len(ordered) < policy.minimum_points:
        warnings = ["minimum_points_not_reached"]
        if singularity_suspected:
            warnings.append("stress_singularity_suspected")
        return MeshConvergenceResult(
            "insufficient_data", ordered, None, False,
            tuple(warnings),
            ("convergence_points:%d" % len(ordered),),
            None, singularity_suspected,
        )

    sizes = tuple(p.mesh_size for p in ordered)
    if len(set(sizes)) != len(sizes):
        warnings = ["duplicate_mesh_size"]
        if singularity_suspected:
            warnings.append("stress_singularity_suspected")
        return MeshConvergenceResult(
            "invalid_data", ordered, None, False,
            tuple(warnings),
            ("convergence_points:%d" % len(ordered),),
            None, singularity_suspected,
        )

    quality_gate = None
    warnings = []
    if singularity_suspected:
        warnings.append("stress_singularity_suspected")
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
    if singularity_suspected:
        evidence.append("stress_singularity_suspected")

    converged = change <= policy.tolerance
    if policy.require_quality_pass and not quality_gate:
        converged = False
        status = "quality_gate_failed"
    elif converged and singularity_suspected:
        status = "converged_with_singularity_warning"
    elif not converged and singularity_suspected:
        status = "singularity_limited"
    else:
        status = "converged" if converged else "not_converged"

    return MeshConvergenceResult(
        status, ordered, change, converged,
        tuple(warnings), tuple(evidence), quality_gate, singularity_suspected,
    )


@dataclass(frozen=True)
class MultiLevelConvergenceResult:
    """Rich multi-level convergence assessment across 3+ refinement levels."""
    status: str                                  # "CONVERGED", "ASYMPTOTIC_APPROACHING", "UNCONVERGED", "SINGULARITY_SUSPECTED"
    converged: bool
    stress_levels: Tuple[float, ...]
    deltas_pct: Tuple[float, ...]
    final_delta_pct: float
    is_monotonic: bool
    diminishing_increment: bool
    displacement_levels: Tuple[float, ...]
    displacement_deltas_pct: Tuple[float, ...]
    displacement_converged: bool
    reaction_force_equilibrium_ok: bool
    theory_error_pct: Optional[Tuple[float, ...]] = None
    diagnostics: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "converged": self.converged,
            "stress_levels": list(self.stress_levels),
            "deltas_pct": list(self.deltas_pct),
            "final_delta_pct": self.final_delta_pct,
            "is_monotonic": self.is_monotonic,
            "diminishing_increment": self.diminishing_increment,
            "displacement_levels": list(self.displacement_levels),
            "displacement_deltas_pct": list(self.displacement_deltas_pct),
            "displacement_converged": self.displacement_converged,
            "reaction_force_equilibrium_ok": self.reaction_force_equilibrium_ok,
            "theory_error_pct": list(self.theory_error_pct) if self.theory_error_pct is not None else None,
            "diagnostics": list(self.diagnostics),
        }


def evaluate_multi_level_mesh_convergence(
    probes: Sequence[Dict[str, Any]],
    stress_key: str = "peak_s11",
    displacement_key: str = "max_u1",
    theory_peak: Optional[float] = None,
    tolerance: float = 0.05,
    displacement_tolerance: float = 0.01,
    rf_tolerance_pct: float = 0.01,
) -> MultiLevelConvergenceResult:
    """Assess mathematical and physics convergence across 3+ mesh refinement levels.

    Args:
        probes: Ordered sequence of extraction probe dicts from coarsest to finest.
        stress_key: Field key for stress measure (e.g. "peak_s11", "max_mises").
        displacement_key: Field key for displacement measure (e.g. "max_u1", "max_displacement").
        theory_peak: Optional theoretical reference value for analytical error calculation.
        tolerance: Final relative stress delta threshold for strict convergence (default 5.0%).
        displacement_tolerance: Final relative displacement delta threshold (default 1.0%).
        rf_tolerance_pct: Maximum allowed reaction force balance error percentage (default 0.01%).
    """
    if len(probes) < 2:
        return MultiLevelConvergenceResult(
            status="UNCONVERGED",
            converged=False,
            stress_levels=tuple(float(p.get(stress_key, 0.0)) for p in probes),
            deltas_pct=(),
            final_delta_pct=100.0,
            is_monotonic=False,
            diminishing_increment=False,
            displacement_levels=tuple(float(p.get(displacement_key, 0.0)) for p in probes),
            displacement_deltas_pct=(),
            displacement_converged=False,
            reaction_force_equilibrium_ok=False,
            diagnostics=("Insufficient refinement levels (minimum 2 required, 3+ recommended).",),
        )

    stresses = tuple(float(p.get(stress_key, p.get("max_stress", p.get("max_mises", 0.0)))) for p in probes)
    displacements = tuple(float(p.get(displacement_key, p.get("max_displacement", 0.0))) for p in probes)

    # Calculate stress deltas
    stress_deltas: List[float] = []
    for i in range(len(stresses) - 1):
        s_prev, s_curr = stresses[i], stresses[i + 1]
        denom = max(abs(s_curr), 1e-12)
        stress_deltas.append(abs(s_curr - s_prev) / denom)

    # Calculate displacement deltas
    u_deltas: List[float] = []
    for i in range(len(displacements) - 1):
        u_prev, u_curr = displacements[i], displacements[i + 1]
        denom = max(abs(u_curr), 1e-12)
        u_deltas.append(abs(u_curr - u_prev) / denom)

    final_delta = stress_deltas[-1] if stress_deltas else 1.0
    final_u_delta = u_deltas[-1] if u_deltas else 1.0

    # Monotonicity check: strictly increasing or strictly decreasing towards limit
    is_strictly_inc = all(stresses[i] < stresses[i + 1] for i in range(len(stresses) - 1))
    is_strictly_dec = all(stresses[i] > stresses[i + 1] for i in range(len(stresses) - 1))
    is_monotonic = is_strictly_inc or is_strictly_dec

    # Diminishing increments check: delta_{k+1} < delta_k
    diminishing_increment = False
    if len(stress_deltas) >= 2:
        diminishing_increment = all(stress_deltas[i] > stress_deltas[i + 1] for i in range(len(stress_deltas) - 1))
    elif len(stress_deltas) == 1:
        diminishing_increment = True

    u_converged = final_u_delta <= displacement_tolerance
    rf_ok = all(float(p.get("rf_error_pct", p.get("rf_error", 0.0))) <= rf_tolerance_pct for p in probes)

    # Theory error if theory_peak is provided
    theory_errors: Optional[Tuple[float, ...]] = None
    if theory_peak is not None and abs(theory_peak) > 1e-12:
        theory_errors = tuple(round(abs(s - theory_peak) / abs(theory_peak) * 100.0, 2) for s in stresses)

    diagnostics: List[str] = []
    # Check for suspected stress singularity: stress keeps exploding without diminishing delta
    if is_strictly_inc and len(stress_deltas) >= 2 and not diminishing_increment and final_delta > tolerance:
        status = "SINGULARITY_SUSPECTED"
        converged = False
        diagnostics.append("Stress diverges with non-diminishing increments; suspected stress singularity (sharp reentrant corner or point load).")
    elif final_delta <= tolerance:
        status = "CONVERGED"
        converged = True
        diagnostics.append(f"Strict mesh independence achieved: final stress sensitivity {round(final_delta * 100.0, 2)}% <= {round(tolerance * 100.0, 2)}%.")
    elif diminishing_increment and is_monotonic:
        status = "ASYMPTOTIC_APPROACHING"
        converged = False
        diagnostics.append(f"Asymptotic convergence regime detected (diminishing increments, delta={round(final_delta * 100.0, 2)}%), but exceeds tolerance {round(tolerance * 100.0, 2)}%.")
    else:
        status = "UNCONVERGED"
        converged = False
        diagnostics.append(f"Mesh sensitivity {round(final_delta * 100.0, 2)}% exceeds tolerance without asymptotic diminishing increments.")

    if not u_converged:
        diagnostics.append(f"Displacement sensitivity {round(final_u_delta * 100.0, 3)}% exceeds displacement threshold.")
    if not rf_ok:
        diagnostics.append("One or more refinement levels failed reaction force equilibrium check.")

    return MultiLevelConvergenceResult(
        status=status,
        converged=converged and u_converged and rf_ok,
        stress_levels=tuple(round(s, 4) for s in stresses),
        deltas_pct=tuple(round(d * 100.0, 2) for d in stress_deltas),
        final_delta_pct=round(final_delta * 100.0, 2),
        is_monotonic=is_monotonic,
        diminishing_increment=diminishing_increment,
        displacement_levels=tuple(round(u, 5) for u in displacements),
        displacement_deltas_pct=tuple(round(ud * 100.0, 3) for ud in u_deltas),
        displacement_converged=u_converged,
        reaction_force_equilibrium_ok=rf_ok,
        theory_error_pct=theory_errors,
        diagnostics=tuple(diagnostics),
    )
