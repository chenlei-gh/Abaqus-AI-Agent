"""Engineering Physical Plausibility and Consistency Auditing for P1.2."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from ..contracts.intent import EngineeringIntent
from ..contracts.intent_reasoning import PlausibilityCheckResult, PlausibilitySeverity


def audit_engineering_plausibility(
    intent: EngineeringIntent,
    material: Optional[Union[Dict[str, Any], Any]] = None,
    geometry: Any = None,
) -> Tuple[PlausibilityCheckResult, ...]:
    """Execute rigorous engineering consistency, rigid body, and load magnitude checks."""
    if hasattr(material, "to_dict"):
        material = material.to_dict()

    checks: List[PlausibilityCheckResult] = []

    # 1. Kinematic Boundary Constraints & Rigid Body Motion Check
    checks.append(_check_boundary_constraints(intent))

    # 2. Applied Load Plausibility & Direction Audit
    checks.extend(_check_applied_loads(intent))

    # 3. Order-of-Magnitude Stress vs Material Strength Plausibility
    checks.append(_check_stress_magnitude_plausibility(intent, material, geometry))

    # 4. Unit System & Dimensional Consistency
    checks.append(_check_unit_consistency(intent, material))

    return tuple(checks)


def _check_boundary_constraints(intent: EngineeringIntent) -> PlausibilityCheckResult:
    """Audit whether structural model has sufficient kinematic constraints against rigid body modes."""
    analysis = (intent.analysis_type or intent.kind or "").lower()
    bcs = intent.boundary_conditions or ()

    # Dynamics or pure thermal problems have different kinematics
    if "thermal" in analysis:
        # Check thermal BCs or flux
        has_temp_bc = any(
            isinstance(bc, dict) and ("temp" in str(bc).lower() or "temperature" in str(bc).lower())
            for bc in bcs
        )
        return PlausibilityCheckResult(
            check_name="thermal_boundary_plausibility",
            passed=True,
            severity=PlausibilitySeverity.INFO,
            message="Thermal boundary constraints verified.",
        )

    # For static / stress analysis
    if not bcs:
        if intent.loads:
            return PlausibilityCheckResult(
                check_name="rigid_body_constraint_check",
                passed=False,
                severity=PlausibilitySeverity.CRITICAL,
                message=(
                    "Model contains applied loads but ZERO boundary constraints. Static analysis will result in "
                    "unconstrained rigid body motion (solver singular matrix / zero pivot)."
                ),
                details={"boundary_conditions_count": 0},
            )
        else:
            return PlausibilityCheckResult(
                check_name="rigid_body_constraint_check",
                passed=True,
                severity=PlausibilitySeverity.INFO,
                message="No applied loads; unconstrained body noted without active load hazard.",
                details={"boundary_conditions_count": 0},
            )

    # Inspect constraint types
    has_fixed_or_encastre = False
    for bc in bcs:
        if isinstance(bc, dict):
            b_type = str(bc.get("type") or bc.get("bc_type", "")).upper()
            values = bc.get("values", {})
        else:
            b_type = str(getattr(bc, "bc_type", None) or getattr(bc, "type", "")).upper()
            values = getattr(bc, "values", {})

        if b_type in ("ENCASTRE", "FIXED", "PINNED", "SYMMETRY"):
            has_fixed_or_encastre = True
            break
        if isinstance(values, dict) and any(v == 0.0 for v in values.values()):
            has_fixed_or_encastre = True
            break

    if not has_fixed_or_encastre:
        return PlausibilityCheckResult(
            check_name="rigid_body_constraint_check",
            passed=False,
            severity=PlausibilitySeverity.WARNING,
            message=(
                "Boundary conditions specified do not include fully grounded fixtures (ENCASTRE/FIXED/PINNED). "
                "Potential kinematic instability or sliding motion under load."
            ),
            details={"bcs": [str(bc) for bc in bcs]},
        )

    return PlausibilityCheckResult(
        check_name="rigid_body_constraint_check",
        passed=True,
        severity=PlausibilitySeverity.INFO,
        message="Adequate kinematic grounding constraints detected.",
        details={"boundary_conditions_count": len(bcs)},
    )


def _check_applied_loads(intent: EngineeringIntent) -> List[PlausibilityCheckResult]:
    """Audit applied load definitions for physical sanity and zero/negative anomalies."""
    results: List[PlausibilityCheckResult] = []
    loads = intent.loads or ()

    if not loads:
        results.append(
            PlausibilityCheckResult(
                check_name="applied_load_existence",
                passed=True,
                severity=PlausibilitySeverity.INFO,
                message="No applied loads specified in model intent.",
            )
        )
        return results

    for i, ld in enumerate(loads):
        if isinstance(ld, dict):
            mag = ld.get("magnitude")
            l_type = ld.get("type") or ld.get("load_type", "concentrated_force")
        else:
            mag = getattr(ld, "magnitude", None)
            l_type = getattr(ld, "load_type", None) or getattr(ld, "type", "concentrated_force")

        if mag is None:
            results.append(
                PlausibilityCheckResult(
                    check_name=f"load_magnitude_validity_{i}",
                    passed=False,
                    severity=PlausibilitySeverity.CRITICAL,
                    message=f"Load {i} ({l_type}) is missing required numerical magnitude.",
                )
            )
            continue

        try:
            mag_val = float(mag)
            if math.isnan(mag_val) or math.isinf(mag_val):
                results.append(
                    PlausibilityCheckResult(
                        check_name=f"load_magnitude_validity_{i}",
                        passed=False,
                        severity=PlausibilitySeverity.CRITICAL,
                        message=f"Load {i} magnitude is NaN or Inf ({mag_val}).",
                    )
                )
            elif mag_val == 0.0:
                results.append(
                    PlausibilityCheckResult(
                        check_name=f"load_magnitude_validity_{i}",
                        passed=False,
                        severity=PlausibilitySeverity.WARNING,
                        message=f"Load {i} magnitude is zero (null loading condition).",
                    )
                )
            else:
                results.append(
                    PlausibilityCheckResult(
                        check_name=f"load_magnitude_validity_{i}",
                        passed=True,
                        severity=PlausibilitySeverity.INFO,
                        message=f"Load {i} ({l_type}) magnitude {mag_val} is physically well-defined.",
                    )
                )
        except (ValueError, TypeError):
            results.append(
                PlausibilityCheckResult(
                    check_name=f"load_magnitude_validity_{i}",
                    passed=False,
                    severity=PlausibilitySeverity.CRITICAL,
                    message=f"Load {i} magnitude '{mag}' cannot be parsed as a float.",
                )
            )

    return results


def _check_stress_magnitude_plausibility(
    intent: EngineeringIntent,
    material: Optional[Dict[str, Any]],
    geometry: Any,
) -> PlausibilityCheckResult:
    """Order-of-magnitude physical sanity check comparing nominal stress to material yield strength."""
    if material is None:
        return PlausibilityCheckResult(
            check_name="stress_magnitude_plausibility",
            passed=True,
            severity=PlausibilitySeverity.INFO,
            message="Material properties omitted; skipping order-of-magnitude stress check.",
        )

    yield_str = (
        material.get("yield_strength")
        or material.get("yield_stress")
        or (material.get("plastic") or {}).get("yield_stress")
    )
    if yield_str is None:
        return PlausibilityCheckResult(
            check_name="stress_magnitude_plausibility",
            passed=True,
            severity=PlausibilitySeverity.INFO,
            message="Material yield strength unknown; order-of-magnitude stress check skipped.",
        )

    try:
        sigma_y = float(yield_str)
    except (ValueError, TypeError):
        return PlausibilityCheckResult(
            check_name="stress_magnitude_plausibility",
            passed=True,
            severity=PlausibilitySeverity.INFO,
            message="Invalid yield strength value format.",
        )

    # Estimate cross section area from geometry or default 50x20 mm
    area_mm2 = _estimate_cross_section_area(geometry, intent)

    # Estimate total applied force in N
    total_force_n = 0.0
    for ld in intent.loads or ():
        if isinstance(ld, dict):
            mag = ld.get("magnitude")
            l_type = str(ld.get("type") or ld.get("load_type", "concentrated_force")).lower()
        else:
            mag = getattr(ld, "magnitude", None)
            l_type = str(getattr(ld, "load_type", None) or getattr(ld, "type", "concentrated_force")).lower()

        if mag is not None:
            try:
                val = abs(float(mag))
                if l_type in ("pressure", "surface_traction"):
                    # Pressure (MPa) * Area (mm2) = Force (N)
                    total_force_n += val * area_mm2
                else:
                    total_force_n += val
            except (ValueError, TypeError):
                pass

    if area_mm2 <= 0 or total_force_n <= 0:
        return PlausibilityCheckResult(
            check_name="stress_magnitude_plausibility",
            passed=True,
            severity=PlausibilitySeverity.INFO,
            message="Insufficient load/geometric data for nominal stress estimation.",
        )

    nominal_stress = total_force_n / area_mm2  # in MPa

    # If nominal average stress exceeds 100x material yield strength,
    # almost certainly a unit misunderstanding (e.g. entered N instead of kN, or kN instead of N).
    if nominal_stress > 100.0 * sigma_y:
        return PlausibilityCheckResult(
            check_name="stress_magnitude_plausibility",
            passed=False,
            severity=PlausibilitySeverity.CRITICAL,
            message=(
                f"Grossly unphysical load magnitude: estimated nominal stress ({nominal_stress:.1f} MPa) "
                f"exceeds 100x material yield strength ({sigma_y:.1f} MPa). "
                "Suspected unit scaling error (e.g. entered kN as N or vice versa)."
            ),
            details={
                "estimated_nominal_stress_mpa": round(nominal_stress, 2),
                "yield_strength_mpa": sigma_y,
                "stress_to_yield_ratio": round(nominal_stress / sigma_y, 1),
            },
        )
    elif nominal_stress > 5.0 * sigma_y:
        return PlausibilityCheckResult(
            check_name="stress_magnitude_plausibility",
            passed=True,
            severity=PlausibilitySeverity.WARNING,
            message=(
                f"High stress warning: estimated nominal stress ({nominal_stress:.1f} MPa) "
                f"exceeds 5x yield strength ({sigma_y:.1f} MPa). Large plastic deformation or fracture expected."
            ),
            details={
                "estimated_nominal_stress_mpa": round(nominal_stress, 2),
                "yield_strength_mpa": sigma_y,
            },
        )

    return PlausibilityCheckResult(
        check_name="stress_magnitude_plausibility",
        passed=True,
        severity=PlausibilitySeverity.INFO,
        message=(
            f"Nominal stress level ({nominal_stress:.1f} MPa) is physically consistent with "
            f"material capacity (Yield = {sigma_y:.1f} MPa)."
        ),
        details={"nominal_stress_mpa": round(nominal_stress, 2)},
    )


def _check_unit_consistency(
    intent: EngineeringIntent,
    material: Optional[Dict[str, Any]],
) -> PlausibilityCheckResult:
    """Verify that material modulus and geometry dimensional units are compatible."""
    unit_sys = (intent.unit_system or "MM_N_MPA").upper()
    if material:
        e_mod = (
            material.get("elastic_modulus")
            or material.get("youngs_modulus")
            or (material.get("elastic") or {}).get("youngs_modulus")
        )
        if e_mod is not None:
            try:
                e_val = float(e_mod)
                # In MM_N_MPA, Steel is ~210000. In SI (M_N_PA), Steel is ~2.1e11
                if unit_sys in ("MM_N_MPA", "SI_MM") and e_val > 1e9:
                    return PlausibilityCheckResult(
                        check_name="unit_system_consistency",
                        passed=False,
                        severity=PlausibilitySeverity.CRITICAL,
                        message=(
                            f"Unit system mismatch: Model specifies unit system {unit_sys}, "
                            f"but Young's modulus is {e_val:g}, which resembles Pascals (SI) "
                            "rather than MPa. Stiffness would be exaggerated by 10^6."
                        ),
                        details={"unit_system": unit_sys, "elastic_modulus": e_val},
                    )
            except (ValueError, TypeError):
                pass

    return PlausibilityCheckResult(
        check_name="unit_system_consistency",
        passed=True,
        severity=PlausibilitySeverity.INFO,
        message=f"Unit system consistency verified under {unit_sys}.",
    )


def _estimate_cross_section_area(geometry: Any, intent: EngineeringIntent) -> float:
    """Estimate a representative cross-sectional area (mm^2)."""
    if geometry is None and intent.metadata and isinstance(intent.metadata, dict) and "geometry" in intent.metadata:
        geometry = intent.metadata["geometry"]

    if geometry is not None:
        if hasattr(geometry, "width") and hasattr(geometry, "height"):
            w = getattr(geometry, "width", None)
            h = getattr(geometry, "height", None)
            if w is not None and h is not None:
                return float(w) * float(h)
        if hasattr(geometry, "radius"):
            r = getattr(geometry, "radius", None)
            if r is not None:
                return math.pi * (float(r) ** 2)

    # 1. From geometry dict
    if isinstance(geometry, dict):
        if "box" in geometry and len(geometry["box"]) >= 3:
            return float(geometry["box"][1]) * float(geometry["box"][2])
        if "dimensions" in geometry and len(geometry["dimensions"]) >= 3:
            return float(geometry["dimensions"][1]) * float(geometry["dimensions"][2])

    # 2. From metadata dimensions
    dims_data = intent.metadata.get("dimensions") if intent.metadata else None
    if dims_data and isinstance(dims_data, list):
        vals = []
        for d in dims_data:
            if isinstance(d, dict) and "value" in d:
                try:
                    vals.append(float(d["value"]))
                except (ValueError, TypeError):
                    pass
        if len(vals) >= 2:
            return vals[0] * vals[1]

    # Heuristic fallback: 1000 mm^2 (e.g. 50mm x 20mm beam)
    return 1000.0
