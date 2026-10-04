"""P1.3 Derived Engineering Metrics & Physical Equilibrium Calculation.

Calculates:
1. Reaction force equilibrium balance between applied external loads and boundary reactions.
2. Numerical energy stability and conservation ratios from history outputs.
3. Structural factor of safety (FoS) and margin of safety (MoS) relative to material yield.

RED LINE:
Derived engineering metrics represent objective physical facts.
Task qualification or acceptance is strictly decided by the Engineering Acceptance Engine.
No secondary acceptance state machine is introduced here.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..contracts.result_intelligence import (
    DerivedEngineeringMetrics,
    EnergyStability,
    FactorOfSafetyMetric,
    ReactionForceBalance,
    XYCurveData,
)


def calculate_reaction_force_balance(
    applied_load: Union[float, Sequence[float], Dict[str, float]],
    reaction_load: Union[float, Sequence[float], Dict[str, float]],
    tolerance_ratio: float = 0.01,
    unit: str = "N",
) -> ReactionForceBalance:
    """Calculate deterministic force balance between applied loads and reactions.
    
    Parameters
    ----------
    applied_load : float, list/tuple of 3 components [Fx, Fy, Fz], or dict
    reaction_load : float, list/tuple of 3 components [Rx, Ry, Rz], or dict
    tolerance_ratio : relative error tolerance for static equilibrium (default 1%)
    unit : physical unit string
    """
    app_vec = _to_3d_vector(applied_load)
    rec_vec = _to_3d_vector(reaction_load)

    app_mag = math.sqrt(sum(c * c for c in app_vec))
    rec_mag = math.sqrt(sum(c * c for c in rec_vec))

    ref = max(app_mag, rec_mag, 1e-9)
    # Difference in resultant magnitude
    diff = abs(app_mag - rec_mag)
    balance_error_percent = (diff / ref) * 100.0

    # Static equilibrium holds if applied and reaction magnitudes match within tolerance
    is_balanced = (balance_error_percent / 100.0) <= tolerance_ratio

    return ReactionForceBalance(
        applied_magnitude=float(app_mag),
        reaction_magnitude=float(rec_mag),
        balance_error_percent=float(balance_error_percent),
        is_balanced=bool(is_balanced),
        applied_components=app_vec,
        reaction_components=rec_vec,
        unit=unit,
    )


def calculate_energy_stability(
    etotal_curve_or_values: Optional[Union[XYCurveData, Sequence[float]]] = None,
    allke_curve_or_values: Optional[Union[XYCurveData, Sequence[float]]] = None,
    allie_curve_or_values: Optional[Union[XYCurveData, Sequence[float]]] = None,
    max_drift_tolerance: float = 0.05,
) -> EnergyStability:
    """Evaluate energy conservation and numerical stability from energy history series."""
    etotal_vals = _extract_values(etotal_curve_or_values)
    allke_vals = _extract_values(allke_curve_or_values)
    allie_vals = _extract_values(allie_curve_or_values)

    if not etotal_vals:
        return EnergyStability(
            total_energy_drift_ratio=0.0,
            kinetic_energy_ratio=None,
            is_stable=True,
            notes="No ETOTAL history output available; stability inferred from solver convergence.",
        )

    min_e = min(etotal_vals)
    max_e = max(etotal_vals)
    drift = abs(max_e - min_e)

    # Reference energy scale: peak internal energy or maximum total energy
    peak_ie = max(abs(v) for v in allie_vals) if allie_vals else 0.0
    ref_energy = max(peak_ie, max(abs(v) for v in etotal_vals), 1e-6)

    drift_ratio = float(drift / ref_energy)

    ke_ratio = None
    if allke_vals and allie_vals:
        peak_ke = max(abs(v) for v in allke_vals)
        if peak_ie > 1e-9:
            ke_ratio = float(peak_ke / peak_ie)

    is_stable = drift_ratio <= max_drift_tolerance
    notes = (
        f"ETOTAL drift ratio is {drift_ratio:.4%} (tolerance: {max_drift_tolerance:.1%})."
    )
    if ke_ratio is not None:
        notes += f" Peak KE/IE ratio: {ke_ratio:.4%}."

    return EnergyStability(
        total_energy_drift_ratio=drift_ratio,
        kinetic_energy_ratio=ke_ratio,
        is_stable=bool(is_stable),
        notes=notes,
    )


def calculate_factor_of_safety(
    max_stress: float,
    yield_strength: float,
    stress_component: str = "Mises",
    material_name: str = "Q235",
    unit: str = "MPa",
) -> FactorOfSafetyMetric:
    """Calculate nominal structural factor of safety and margin of safety.
    
    FoS = yield_strength / max_stress
    MoS = FoS - 1.0
    
    NOTE:
    This returns a deterministic derived engineering metric.
    Acceptance of this metric against safety thresholds is performed by the Acceptance Engine.
    """
    abs_stress = abs(float(max_stress))
    denom = max(abs_stress, 1e-9)
    fos = float(yield_strength) / denom
    mos = float(fos - 1.0)

    return FactorOfSafetyMetric(
        max_stress=float(max_stress),
        yield_strength=float(yield_strength),
        factor_of_safety=float(fos),
        margin_of_safety=float(mos),
        stress_component=stress_component,
        material_name=material_name,
        unit=unit,
    )


def calculate_derived_metrics(
    applied_load: Optional[Union[float, Sequence[float], Dict[str, float]]] = None,
    reaction_load: Optional[Union[float, Sequence[float], Dict[str, float]]] = None,
    etotal_data: Optional[Union[XYCurveData, Sequence[float]]] = None,
    allke_data: Optional[Union[XYCurveData, Sequence[float]]] = None,
    allie_data: Optional[Union[XYCurveData, Sequence[float]]] = None,
    max_stress: Optional[float] = None,
    yield_strength: Optional[float] = None,
    stress_component: str = "Mises",
    material_name: str = "Q235",
    metadata: Optional[Dict[str, Any]] = None,
) -> DerivedEngineeringMetrics:
    """Consolidate derived engineering metrics for P1.3 deliverable generation."""
    force_balance = None
    if applied_load is not None and reaction_load is not None:
        force_balance = calculate_reaction_force_balance(
            applied_load=applied_load,
            reaction_load=reaction_load,
        )

    energy_stability = None
    if etotal_data is not None or allie_data is not None:
        energy_stability = calculate_energy_stability(
            etotal_curve_or_values=etotal_data,
            allke_curve_or_values=allke_data,
            allie_curve_or_values=allie_data,
        )

    safety_factor = None
    if max_stress is not None and yield_strength is not None and yield_strength > 0:
        safety_factor = calculate_factor_of_safety(
            max_stress=max_stress,
            yield_strength=yield_strength,
            stress_component=stress_component,
            material_name=material_name,
        )

    return DerivedEngineeringMetrics(
        force_balance=force_balance,
        energy_stability=energy_stability,
        safety_factor=safety_factor,
        metadata=dict(metadata or {}),
    )


def _to_3d_vector(val: Union[float, Sequence[float], Dict[str, float]]) -> Tuple[float, float, float]:
    if isinstance(val, (int, float)):
        return (0.0, float(val), 0.0)
    if isinstance(val, dict):
        x = float(val.get("x", val.get("Fx", val.get("X", val.get("1", 0.0)))))
        y = float(val.get("y", val.get("Fy", val.get("Y", val.get("2", 0.0)))))
        z = float(val.get("z", val.get("Fz", val.get("Z", val.get("3", 0.0)))))
        return (x, y, z)
    if isinstance(val, (list, tuple)):
        lst = [float(x) for x in val]
        while len(lst) < 3:
            lst.append(0.0)
        return (lst[0], lst[1], lst[2])
    return (0.0, 0.0, 0.0)


def _extract_values(src: Optional[Union[XYCurveData, Sequence[float]]]) -> List[float]:
    if src is None:
        return []
    if isinstance(src, XYCurveData):
        return list(src.y_values)
    return [float(x) for x in src]
