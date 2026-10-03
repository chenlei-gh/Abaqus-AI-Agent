"""R2: Comprehensive Mesh Engineering Gate.

Validates element families across continuum, shell, and beam discretizations,
extracts and evaluates native Abaqus shape quality metrics, and enforces fail-closed
mesh convergence & quality gatekeepers before solver submission.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import math

from .contracts.mesh_quality import (
    ABAQUS_NATIVE_SHAPE_METRICS,
    MeshQualityPolicy,
    MeshQualityResult,
)
from .numerical_verification import verify_richardson


ELEMENT_FAMILIES = {
    "CONTINUUM_3D": ("C3D8", "C3D8R", "C3D8I", "C3D10", "C3D20", "C3D20R", "C3D4"),
    "CONTINUUM_2D": ("CPS4", "CPS4R", "CPE4", "CPE4R", "CPS3", "CPE3", "CAX4R"),
    "SHELL": ("S4", "S4R", "S3", "S3R", "S8R"),
    "BEAM_TRUSS": ("B31", "B32", "B21", "T3D2", "T2D2"),
}


@dataclass(frozen=True)
class ElementFamilyValidation:
    element_type: str
    family: str                              # "CONTINUUM_3D", "SHELL", "BEAM_TRUSS", etc.
    is_valid: bool
    is_reduced_integration: bool
    is_second_order: bool
    notes: Tuple[str, ...] = ()


def classify_element_type(element_type: str) -> ElementFamilyValidation:
    """Classify and validate an Abaqus element type against canonical element families."""
    elem = element_type.strip().upper()
    matched_family = "UNKNOWN"
    for fam, types in ELEMENT_FAMILIES.items():
        if elem in types:
            matched_family = fam
            break

    if matched_family == "UNKNOWN":
        return ElementFamilyValidation(
            element_type=elem,
            family="UNKNOWN",
            is_valid=False,
            is_reduced_integration=False,
            is_second_order=False,
            notes=(f"Element type '{elem}' is not recognized in supported families.",),
        )

    is_reduced = elem.endswith("R")
    is_2nd = any(k in elem for k in ("10", "20", "8R", "32"))
    notes: List[str] = []
    if is_reduced:
        notes.append("Reduced integration: watch for hourglassing modes in coarse meshes.")
    if is_2nd:
        notes.append("Second-order formulation: higher accuracy for bending and curved boundaries.")

    return ElementFamilyValidation(
        element_type=elem,
        family=matched_family,
        is_valid=True,
        is_reduced_integration=is_reduced,
        is_second_order=is_2nd,
        notes=tuple(notes),
    )


@dataclass(frozen=True)
class MeshGateEvaluation:
    """Evaluation verdict of mesh quality against engineering gate criteria."""
    status: str                              # "PASS", "WARNING", "BLOCKED"
    passed: bool
    metrics: Dict[str, float]
    violations: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    diagnostics: Tuple[str, ...] = ()


def evaluate_mesh_quality_gate(
    metrics: Dict[str, float],
    policy: Optional[MeshQualityPolicy] = None,
) -> MeshGateEvaluation:
    """Evaluate native Abaqus mesh quality metrics against strict engineering boundaries.

    Fail-closed policy:
    - Negative Jacobian or inverted element (min_jacobian <= 0.0) -> BLOCKED.
    - Extreme aspect ratio (> 50.0) -> BLOCKED.
    - Extreme corner angles (< 5 deg or > 175 deg) -> BLOCKED.
    - Moderate distortions -> WARNING.
    """
    pol = policy or MeshQualityPolicy(
        max_aspect_ratio=20.0,
        min_jacobian=0.1,
        min_angle=10.0,
        max_angle=170.0,
    )

    violations: List[str] = []
    warnings: List[str] = []
    diagnostics: List[str] = []

    # 1. Critical Negative Jacobian / Inverted Elements
    min_jac = metrics.get("min_jacobian")
    if min_jac is not None:
        if min_jac <= 0.0:
            violations.append(f"Inverted element detected: min_jacobian={min_jac} <= 0.0")
            diagnostics.append("Solver will abort due to negative Jacobian / severe geometric inversion.")
        elif pol.min_jacobian is not None and min_jac < pol.min_jacobian:
            warnings.append(f"Low Jacobian: min_jacobian={min_jac} < policy threshold {pol.min_jacobian}")

    # 2. Aspect Ratio Check
    ar = metrics.get("max_aspect_ratio")
    if ar is not None:
        if ar > 50.0:
            violations.append(f"Excessive aspect ratio: max_aspect_ratio={ar} > 50.0")
            diagnostics.append("Extreme element elongation degrades matrix conditioning and bending accuracy.")
        elif pol.max_aspect_ratio is not None and ar > pol.max_aspect_ratio:
            warnings.append(f"High aspect ratio: max_aspect_ratio={ar} > policy limit {pol.max_aspect_ratio}")

    # 3. Corner Angles
    min_ang = metrics.get("min_angle")
    max_ang = metrics.get("max_angle")
    if min_ang is not None and min_ang < 5.0:
        violations.append(f"Acute corner angle: min_angle={min_ang} deg < 5.0 deg")
        diagnostics.append("Severely pinched corner angles cause shear locking.")
    elif min_ang is not None and pol.min_angle is not None and min_ang < pol.min_angle:
        warnings.append(f"Acute interior angle: {min_ang} deg < {pol.min_angle} deg")

    if max_ang is not None and max_ang > 175.0:
        violations.append(f"Obtuse corner angle: max_angle={max_ang} deg > 175.0 deg")
        diagnostics.append("Flat elements near 180 deg violate shape consistency.")
    elif max_ang is not None and pol.max_angle is not None and max_ang > pol.max_angle:
        warnings.append(f"Obtuse interior angle: {max_ang} deg > {pol.max_angle} deg")

    # Determine gate status
    if violations:
        status = "BLOCKED"
        passed = False
    elif warnings:
        status = "WARNING"
        passed = True
    else:
        status = "PASS"
        passed = True

    return MeshGateEvaluation(
        status=status,
        passed=passed,
        metrics=dict(metrics),
        violations=tuple(violations),
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
    )


@dataclass(frozen=True)
class MeshConvergenceGateResult:
    status: str                              # "CONVERGED", "MONOTONIC_CONVERGENT", "UNCONVERGED", "INVALID"
    passed: bool
    observed_order: Optional[float]
    gci_fine: Optional[float]
    relative_change: float
    tolerance: float
    details: Dict[str, Any] = field(default_factory=dict)


def evaluate_mesh_convergence_gate(
    mesh_sizes: Sequence[float],
    responses: Sequence[float],
    tolerance: float = 0.02,
) -> MeshConvergenceGateResult:
    """Evaluate grid convergence index (GCI) and relative change across refinement levels."""
    if len(mesh_sizes) != len(responses) or len(responses) < 2:
        return MeshConvergenceGateResult(
            status="INVALID",
            passed=False,
            observed_order=None,
            gci_fine=None,
            relative_change=float("inf"),
            tolerance=tolerance,
            details={"error": "At least 2 mesh sizes and corresponding responses required."},
        )

    # Sort from coarse (largest size) to fine (smallest size)
    paired = sorted(zip(mesh_sizes, responses), key=lambda x: x[0], reverse=True)
    sorted_sizes = [p[0] for p in paired]
    sorted_vals = [p[1] for p in paired]

    ref_val = max(abs(sorted_vals[-1]), 1e-12)
    rel_change = abs(sorted_vals[-1] - sorted_vals[-2]) / ref_val

    # If 3 or more levels, evaluate Richardson / Roache GCI
    obs_order = None
    gci_fine = None
    if len(sorted_vals) >= 3:
        r21 = sorted_sizes[-3] / sorted_sizes[-2]
        r32 = sorted_sizes[-2] / sorted_sizes[-1]
        # Check if refinement ratio is approximately uniform (within 5%)
        if abs(r21 - r32) / r21 <= 0.05:
            res_richardson = verify_richardson(
                name="mesh_convergence",
                values=sorted_vals,
                refinement_ratio=r32,
                tolerance=tolerance,
            )
            if res_richardson.status == "converged":
                gci_fine = res_richardson.error
                obs_order = float(res_richardson.message.split("observed_order=")[-1].split()[0]) if "observed_order=" in res_richardson.message else None

    passed = (rel_change <= tolerance)
    if passed and gci_fine is not None and gci_fine <= tolerance:
        status = "CONVERGED"
    elif passed:
        status = "MONOTONIC_CONVERGENT"
    else:
        status = "UNCONVERGED"

    return MeshConvergenceGateResult(
        status=status,
        passed=passed,
        observed_order=obs_order,
        gci_fine=gci_fine,
        relative_change=rel_change,
        tolerance=tolerance,
        details={
            "levels_evaluated": len(sorted_vals),
            "sizes": sorted_sizes,
            "responses": sorted_vals,
        },
    )
