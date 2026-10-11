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
        if not isfinite(self.tolerance) or self.tolerance < 0:
            raise ValueError("tolerance must be a non-negative finite value")
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
    abs_displacement_tolerance: float = 1e-6,
    min_levels: int = 3,
) -> MultiLevelConvergenceResult:
    """Assess mathematical and physics convergence across 3+ mesh refinement levels.

    Args:
        probes: Ordered sequence of extraction probe dicts from coarsest to finest.
        stress_key: Field key for stress measure (e.g. "peak_s11", "max_mises"). Strict match required.
        displacement_key: Field key for displacement measure (e.g. "max_u1", "max_displacement"). Strict match required.
        theory_peak: Optional theoretical reference value for analytical error calculation. Must be finite if provided.
        tolerance: Final relative stress delta threshold for strict convergence (default 5.0%).
        displacement_tolerance: Final relative displacement delta threshold (default 1.0%).
        rf_tolerance_pct: Maximum allowed reaction force balance error percentage (default 0.01%).
        abs_displacement_tolerance: Absolute displacement threshold for microscopic near-zero deformation in solver length units (e.g. 1e-6 mm = 1 nm under MM_N_MPA).
        min_levels: Minimum number of distinct mesh refinement levels required for convergence certification (default 3).
    """
    for name, val in [
        ("tolerance", tolerance),
        ("displacement_tolerance", displacement_tolerance),
        ("rf_tolerance_pct", rf_tolerance_pct),
        ("abs_displacement_tolerance", abs_displacement_tolerance),
    ]:
        if not isfinite(val) or val < 0.0:
            raise ValueError(f"Convergence threshold '{name}' must be a non-negative finite float, got {val}")
    if min_levels < 2:
        raise ValueError(f"min_levels must be >= 2, got {min_levels}")
    if theory_peak is not None and not isfinite(theory_peak):
        raise ValueError(f"theory_peak must be a finite float if provided, got {theory_peak}")

    diagnostics: List[str] = []
    missing_evidence = False
    invalid_data = False

    stresses: List[float] = []
    displacements: List[float] = []
    rf_errors: List[float] = []
    mesh_metrics: List[Tuple[Optional[float], Optional[int]]] = []

    for idx, p in enumerate(probes):
        # 1. Strict stress evidence extraction (P0-1: strict key match, no quantity mixing fallback)
        raw_s = p.get(stress_key)
        if raw_s is None:
            missing_evidence = True
            diagnostics.append(
                f"Level {idx + 1} missing required stress evidence key '{stress_key}'; "
                "fallback across different quantities is strictly prohibited."
            )
        else:
            try:
                s_val = float(raw_s)
                if not isfinite(s_val):
                    missing_evidence = True
                    diagnostics.append(f"Level {idx + 1} non-finite stress value {s_val}.")
                elif abs(s_val) < 1e-12:
                    missing_evidence = True
                    diagnostics.append(f"Level {idx + 1} stress magnitude is zero; cannot evaluate relative sensitivity.")
                else:
                    stresses.append(s_val)
            except (ValueError, TypeError):
                missing_evidence = True
                diagnostics.append(f"Level {idx + 1} non-numeric stress value {raw_s}.")

        # 2. Strict displacement evidence extraction (P0-1: strict key match, no fallback)
        raw_u = p.get(displacement_key)
        if raw_u is None:
            missing_evidence = True
            diagnostics.append(
                f"Level {idx + 1} missing required displacement evidence key '{displacement_key}'; "
                "fallback across different quantities is strictly prohibited."
            )
        else:
            try:
                u_val = float(raw_u)
                if not isfinite(u_val):
                    missing_evidence = True
                    diagnostics.append(f"Level {idx + 1} non-finite displacement value {u_val}.")
                else:
                    displacements.append(u_val)
            except (ValueError, TypeError):
                missing_evidence = True
                diagnostics.append(f"Level {idx + 1} non-numeric displacement value {raw_u}.")

        # 3. Strict reaction force equilibrium evidence extraction (no default zero fallback, non-negative)
        raw_rf = p.get("rf_error_pct")
        if raw_rf is None:
            raw_rf = p.get("rf_error")
        if raw_rf is None:
            missing_evidence = True
            diagnostics.append(f"Level {idx + 1} missing reaction force equilibrium error metric ('rf_error_pct').")
        else:
            try:
                rf_val = float(raw_rf)
                if not isfinite(rf_val) or rf_val < 0.0:
                    missing_evidence = True
                    diagnostics.append(f"Level {idx + 1} invalid reaction force error {rf_val}; must be non-negative finite value.")
                else:
                    rf_errors.append(rf_val)
            except (ValueError, TypeError):
                missing_evidence = True
                diagnostics.append(f"Level {idx + 1} non-numeric reaction force error {raw_rf}.")

        # 4. Physical mesh refinement evidence extraction (P0-1 & P0-2: strict metric extraction, no masking or float truncation)
        size_key_found = None
        for k in ("seed_size", "mesh_size", "global_size"):
            if k in p:
                size_key_found = k
                break

        ext_size: Optional[float] = None
        if size_key_found is not None:
            raw_size = p[size_key_found]
            if raw_size is not None:
                if isinstance(raw_size, bool):
                    invalid_data = True
                    diagnostics.append(
                        f"Level {idx + 1} mesh size '{size_key_found}' is boolean; must be a positive finite number."
                    )
                else:
                    try:
                        s_val = float(raw_size)
                        if not isfinite(s_val) or s_val <= 0.0:
                            invalid_data = True
                            diagnostics.append(
                                f"Level {idx + 1} mesh size '{size_key_found}' has invalid non-positive or non-finite value {raw_size}."
                            )
                        else:
                            ext_size = s_val
                    except (ValueError, TypeError):
                        invalid_data = True
                        diagnostics.append(
                            f"Level {idx + 1} mesh size '{size_key_found}' has non-numeric value {raw_size}."
                        )

        count_key_found = None
        for k in ("total_elements", "total_nodes"):
            if k in p:
                count_key_found = k
                break

        ext_count: Optional[int] = None
        if count_key_found is not None:
            raw_count = p[count_key_found]
            if raw_count is not None:
                if isinstance(raw_count, bool) or not isinstance(raw_count, int):
                    invalid_data = True
                    diagnostics.append(
                        f"Level {idx + 1} mesh count '{count_key_found}' must be a strict positive integer, got {type(raw_count).__name__} ({raw_count})."
                    )
                elif raw_count <= 0:
                    invalid_data = True
                    diagnostics.append(
                        f"Level {idx + 1} mesh count '{count_key_found}' must be > 0, got {raw_count}."
                    )
                else:
                    ext_count = raw_count

        if ext_size is None and ext_count is None and not invalid_data:
            missing_evidence = True
            diagnostics.append(
                f"Level {idx + 1} missing physical mesh refinement evidence ('seed_size', 'mesh_size', 'global_size', 'total_elements', or 'total_nodes')."
            )
        mesh_metrics.append((ext_size, ext_count))

    if invalid_data:
        return MultiLevelConvergenceResult(
            status="INVALID_DATA",
            converged=False,
            stress_levels=tuple(round(s, 4) for s in stresses),
            deltas_pct=(),
            final_delta_pct=100.0,
            is_monotonic=False,
            diminishing_increment=False,
            displacement_levels=tuple(round(u, 5) for u in displacements),
            displacement_deltas_pct=(),
            displacement_converged=False,
            reaction_force_equilibrium_ok=False,
            diagnostics=tuple(diagnostics),
        )

    if missing_evidence or len(stresses) != len(probes) or len(displacements) != len(probes) or len(rf_errors) != len(probes) or len(mesh_metrics) != len(probes):
        return MultiLevelConvergenceResult(
            status="INCOMPLETE_EVIDENCE",
            converged=False,
            stress_levels=tuple(round(s, 4) for s in stresses),
            deltas_pct=(),
            final_delta_pct=100.0,
            is_monotonic=False,
            diminishing_increment=False,
            displacement_levels=tuple(round(u, 5) for u in displacements),
            displacement_deltas_pct=(),
            displacement_converged=False,
            reaction_force_equilibrium_ok=False,
            diagnostics=tuple(diagnostics),
        )

    # P0-2: Require minimum levels for convergence certification
    if len(probes) < min_levels:
        diagnostics.append(
            f"Insufficient refinement levels ({len(probes)} provided, minimum {min_levels} strictly required for asymptotic convergence certification)."
        )
        return MultiLevelConvergenceResult(
            status="UNCONVERGED",
            converged=False,
            stress_levels=tuple(round(s, 4) for s in stresses),
            deltas_pct=(),
            final_delta_pct=100.0,
            is_monotonic=False,
            diminishing_increment=False,
            displacement_levels=tuple(round(u, 5) for u in displacements),
            displacement_deltas_pct=(),
            displacement_converged=False,
            reaction_force_equilibrium_ok=False,
            diagnostics=tuple(diagnostics),
        )

    # P0-1: Consistent metric sequence validation across levels (cannot mix sizes and counts)
    sizes = [m[0] for m in mesh_metrics]
    counts = [m[1] for m in mesh_metrics]

    has_full_sizes = all(s is not None for s in sizes)
    has_full_counts = all(c is not None for c in counts)

    if not has_full_sizes and not has_full_counts:
        diagnostics.append(
            "Mesh refinement evidence across levels is inconsistent: levels must consistently provide either "
            "a complete mesh size metric sequence ('seed_size', 'mesh_size', 'global_size') or "
            "a complete element/node count metric sequence ('total_elements', 'total_nodes'). "
            "Mixed or incomplete metric types across levels cannot certify asymptotic refinement."
        )
        return MultiLevelConvergenceResult(
            status="INVALID_DATA",
            converged=False,
            stress_levels=tuple(round(s, 4) for s in stresses),
            deltas_pct=(),
            final_delta_pct=100.0,
            is_monotonic=False,
            diminishing_increment=False,
            displacement_levels=tuple(round(u, 5) for u in displacements),
            displacement_deltas_pct=(),
            displacement_converged=False,
            reaction_force_equilibrium_ok=False,
            diagnostics=tuple(diagnostics),
        )

    if has_full_sizes:
        if not all(sizes[i] > sizes[i + 1] for i in range(len(sizes) - 1)):
            diagnostics.append(
                f"Mesh sizes across levels {sizes} do not exhibit strictly decreasing refinement sequence."
            )
            return MultiLevelConvergenceResult(
                status="INVALID_DATA",
                converged=False,
                stress_levels=tuple(round(s, 4) for s in stresses),
                deltas_pct=(),
                final_delta_pct=100.0,
                is_monotonic=False,
                diminishing_increment=False,
                displacement_levels=tuple(round(u, 5) for u in displacements),
                displacement_deltas_pct=(),
                displacement_converged=False,
                reaction_force_equilibrium_ok=False,
                diagnostics=tuple(diagnostics),
            )

    if has_full_counts:
        if not all(counts[i] < counts[i + 1] for i in range(len(counts) - 1)):
            diagnostics.append(
                f"Mesh element/node counts across levels {counts} do not exhibit strictly increasing refinement sequence."
            )
            return MultiLevelConvergenceResult(
                status="INVALID_DATA",
                converged=False,
                stress_levels=tuple(round(s, 4) for s in stresses),
                deltas_pct=(),
                final_delta_pct=100.0,
                is_monotonic=False,
                diminishing_increment=False,
                displacement_levels=tuple(round(u, 5) for u in displacements),
                displacement_deltas_pct=(),
                displacement_converged=False,
                reaction_force_equilibrium_ok=False,
                diagnostics=tuple(diagnostics),
            )

    # P1-1: Strict classification of non-negative stress invariants vs signed stress quantities.
    # Only mathematically non-negative equivalent stress invariants skip sign reversal checks.
    # Signed quantities like normal stresses (S11, S22), shear stresses, pressure, and hydrostatic stress must check sign consistency.
    non_negative_invariants = ("mises", "tresca", "octahedral", "vm")
    is_non_negative_invariant = any(inv in stress_key.lower() for inv in non_negative_invariants)
    if not is_non_negative_invariant:
        sign_reversal = any((stresses[i] * stresses[i + 1]) < 0.0 for i in range(len(stresses) - 1))
    else:
        sign_reversal = False

    # Calculate stress deltas
    stress_deltas: List[float] = []
    for i in range(len(stresses) - 1):
        s_prev, s_curr = stresses[i], stresses[i + 1]
        denom = max(abs(s_curr), 1e-12)
        stress_deltas.append(abs(s_curr - s_prev) / denom)

    # P0-4 & P1: Calculate displacement deltas with explicit absolute tolerance contract
    u_deltas: List[float] = []
    for i in range(len(displacements) - 1):
        u_prev, u_curr = displacements[i], displacements[i + 1]
        abs_diff = abs(u_curr - u_prev)
        if (abs(u_curr) < abs_displacement_tolerance and abs(u_prev) < abs_displacement_tolerance) or (abs_diff < abs_displacement_tolerance):
            u_deltas.append(0.0)
        else:
            denom = max(abs(u_curr), 1e-9)
            u_deltas.append(abs_diff / denom)

    final_delta = stress_deltas[-1] if stress_deltas else 1.0
    final_u_delta = u_deltas[-1] if u_deltas else 1.0

    # Monotonicity check on stress magnitudes: strictly increasing or strictly decreasing towards limit
    abs_stresses = [abs(s) for s in stresses]
    is_strictly_inc = all(abs_stresses[i] < abs_stresses[i + 1] for i in range(len(abs_stresses) - 1))
    is_strictly_dec = all(abs_stresses[i] > abs_stresses[i + 1] for i in range(len(abs_stresses) - 1))
    is_monotonic = is_strictly_inc or is_strictly_dec

    # Diminishing increments check: delta_{k+1} < delta_k
    diminishing_increment = False
    if len(stress_deltas) >= 2:
        diminishing_increment = all(stress_deltas[i] > stress_deltas[i + 1] for i in range(len(stress_deltas) - 1))
    elif len(stress_deltas) == 1:
        diminishing_increment = True

    u_converged = final_u_delta <= displacement_tolerance
    rf_ok = all(0.0 <= rf_val <= rf_tolerance_pct for rf_val in rf_errors)

    # Theory error if theory_peak is provided
    theory_errors: Optional[Tuple[float, ...]] = None
    if theory_peak is not None and abs(theory_peak) > 1e-12:
        theory_errors = tuple(round(abs(s - theory_peak) / abs(theory_peak) * 100.0, 2) for s in stresses)
        if (theory_peak * stresses[-1]) < 0.0:
            diagnostics.append("Theoretical reference value has opposite sign to measured stress response.")

    # Status adjudication
    if sign_reversal:
        status = "SIGN_REVERSAL"
        converged = False
        diagnostics.append("Signed stress component reversed sign across refinement levels; asymptotic convergence cannot be claimed.")
    elif is_strictly_inc and len(stress_deltas) >= 2 and not diminishing_increment and final_delta > tolerance:
        status = "SINGULARITY_SUSPECTED"
        converged = False
        diagnostics.append("Stress diverges with non-diminishing increments; suspected stress singularity (sharp reentrant corner or point load).")
    elif final_delta <= tolerance:
        if not is_monotonic:
            status = "OSCILLATORY_APPROACH"
            converged = False
            diagnostics.append("Stress variations exhibit non-monotonic oscillation; asymptotic convergence cannot be claimed.")
        elif not diminishing_increment:
            status = "NON_DIMINISHING_DELTA"
            converged = False
            diagnostics.append("Stress deltas do not diminish monotonically across refinement levels; asymptotic convergence cannot be claimed.")
        else:
            # Stress sensitivity criteria strictly met within asymptotic regime
            if u_converged and rf_ok:
                status = "CONVERGED"
                converged = True
                diagnostics.append(f"Strict mesh independence achieved: final stress sensitivity {round(final_delta * 100.0, 2)}% <= {round(tolerance * 100.0, 2)}%.")
            elif not u_converged and not rf_ok:
                status = "PHYSICS_UNCONVERGED"
                converged = False
            elif not u_converged:
                status = "DISPLACEMENT_UNCONVERGED"
                converged = False
            else:
                status = "EQUILIBRIUM_UNCONVERGED"
                converged = False
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
        converged=converged,
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
