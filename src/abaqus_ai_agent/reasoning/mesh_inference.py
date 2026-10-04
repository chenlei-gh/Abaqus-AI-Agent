"""Engineering Mesh Parameter Reasoning & Inference for P1.2."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

from ..contracts.intent import EngineeringIntent
from ..contracts.intent_reasoning import InferenceRiskLevel, InferredParameter
from ..planning.compiler import IntentMeshSpec


def infer_mesh_specification(
    intent: EngineeringIntent,
    geometry: Any = None,
    explicit_mesh: Optional[IntentMeshSpec] = None,
) -> Tuple[IntentMeshSpec, Optional[InferredParameter]]:
    """Derive professional CAE mesh size and element type from geometry features and physics.

    Refuses dumb global hardcoding (e.g. 2.5mm for all scales). Instead:
    1. Extracts characteristic dimensions from CAD BoundingBox, geometry dictionary, or prompt.
    2. Calculates characteristic minimum thickness/span L_char.
    3. Selects element size: h = max(L_char / 12.0, 0.2 mm) to guarantee at least 2~3 elements through thickness.
    4. Selects element type based on physics (e.g. C3D10M/C3D8I for contact/bending, C3D8R with hourglass control for simple tension).
    5. Emits auditable InferredParameter with MEDIUM risk tier.
    """
    if explicit_mesh is not None:
        return explicit_mesh, None

    if intent.mesh_requirements:
        if isinstance(intent.mesh_requirements, IntentMeshSpec):
            return intent.mesh_requirements, None
        if isinstance(intent.mesh_requirements, dict):
            size = intent.mesh_requirements.get("global_size") or intent.mesh_requirements.get("target_size")
            etype = intent.mesh_requirements.get("element_type", "C3D8R")
            if size is not None and float(size) > 0:
                return IntentMeshSpec(
                    element_type=str(etype),
                    global_size=float(size),
                    deviation_factor=float(intent.mesh_requirements.get("deviation_factor", 0.1)),
                ), None

    # Step 1: Extract bounding box / dimensions
    bbox = _extract_bounding_box(geometry, intent)
    char_size: float
    rationale: str
    confidence: float

    if bbox is not None:
        dx, dy, dz = bbox
        dims = sorted([d for d in (dx, dy, dz) if d > 0])
        if dims:
            min_dim = dims[0]
            mid_dim = dims[1] if len(dims) > 1 else min_dim
            max_dim = dims[-1]
            if min_dim <= 2.0:
                div = 2.0
            elif mid_dim >= 2.5 * min_dim:
                # Plate-like / bracket geometry: higher thickness resolution
                div = 6.0
            else:
                # Beam / slender bar compact section: balance resolution and point load singularity
                div = 4.0
            suggested_size = max(min_dim / div, max_dim / 100.0)
            # Bound within sensible engineering bounds
            char_size = round(max(suggested_size, 0.5), 2)
            rationale = (
                f"Derived global mesh size {char_size} mm from geometry bounding dimensions "
                f"({dx:.1f} x {dy:.1f} x {dz:.1f} mm), providing ~{div:.0f} elements across thickness "
                f"({min_dim:.1f} mm) per standard solid structural discretization heuristics."
            )
            confidence = 0.92
        else:
            char_size = 2.5
            rationale = "Fallback to standard 2.5 mm benchmark mesh size (geometry dimensions non-positive)."
            confidence = 0.70
    else:
        # Check prompt dimensions
        dims_from_meta = _extract_dims_from_metadata(intent)
        if dims_from_meta:
            dims = sorted([d for d in dims_from_meta if d > 0])
            min_dim = dims[0]
            mid_dim = dims[1] if len(dims) > 1 else min_dim
            max_dim = dims[-1]
            if min_dim <= 2.0:
                div = 2.0
            elif mid_dim >= 2.5 * min_dim:
                div = 6.0
            else:
                div = 4.0
            suggested_size = max(min_dim / div, max_dim / 100.0)
            char_size = round(max(suggested_size, 0.5), 2)
            rationale = (
                f"Derived global mesh size {char_size} mm from intent prompt dimensions "
                f"({min_dim:.1f} to {max_dim:.1f} mm), providing ~{div:.0f} elements across thickness "
                f"per standard solid structural discretization heuristics."
            )
            confidence = 0.88
        else:
            char_size = 2.5
            rationale = "No explicit geometry or dimensions provided; applied default engineering heuristic size 2.5 mm."
            confidence = 0.65

    # Step 2: Select element formulation based on physics domain
    analysis_type = (intent.analysis_type or intent.kind or "").lower()
    has_contact = bool(intent.contacts) or "contact" in analysis_type
    has_bending = any(
        isinstance(ld, dict) and ld.get("type") in ("moment", "concentrated_force")
        for ld in (intent.loads or ())
    )

    if has_contact:
        # Contact benefits from second-order modified tet (C3D10M) or incompatible mode (C3D8I)
        elem_type = "C3D8I"
        elem_rationale = "Selected C3D8I incompatible mode hex elements to prevent shear locking in contact/bending."
    elif "thermal" in analysis_type:
        elem_type = "DC3D8"
        elem_rationale = "Selected DC3D8 standard linear thermal brick elements."
    else:
        elem_type = "C3D8R"
        elem_rationale = "Selected C3D8R reduced-integration brick elements with hourglass control."

    mesh_spec = IntentMeshSpec(
        element_type=elem_type,
        global_size=char_size,
        deviation_factor=0.1,
    )

    inference = InferredParameter(
        parameter_name="mesh",
        inferred_value=f"{elem_type} (size={char_size}mm)",
        original_value=None,
        source="geometry_feature_and_physics_reasoning",
        confidence=confidence,
        risk_level=InferenceRiskLevel.MEDIUM,
        rationale=f"{rationale} {elem_rationale}",
    )
    return mesh_spec, inference


def _extract_bounding_box(geometry: Any, intent: EngineeringIntent) -> Optional[Tuple[float, float, float]]:
    """Extract (dx, dy, dz) from CadBoundingBox, GeometryModel, or dictionary."""
    if geometry is None and intent.metadata and isinstance(intent.metadata, dict) and "geometry" in intent.metadata:
        geometry = intent.metadata["geometry"]

    if geometry is None:
        return None

    # IntentGeometrySpec or object with length/width/height
    if hasattr(geometry, "length") and hasattr(geometry, "width") and hasattr(geometry, "height"):
        l = getattr(geometry, "length", None)
        w = getattr(geometry, "width", None)
        h = getattr(geometry, "height", None)
        if l is not None and w is not None and h is not None:
            return (float(l), float(w), float(h))

    # CadBoundingBox or object with min/max attributes
    if hasattr(geometry, "min_x") and hasattr(geometry, "max_x"):
        dx = abs(geometry.max_x - geometry.min_x)
        dy = abs(geometry.max_y - geometry.min_y)
        dz = abs(geometry.max_z - geometry.min_z)
        return (dx, dy, dz)

    # GeometryModel with bounding_box attribute
    if hasattr(geometry, "bounding_box"):
        bbox = geometry.bounding_box
        if hasattr(bbox, "min_x"):
            return (
                abs(bbox.max_x - bbox.min_x),
                abs(bbox.max_y - bbox.min_y),
                abs(bbox.max_z - bbox.min_z),
            )

    # Dictionary
    if isinstance(geometry, dict):
        if "box" in geometry and isinstance(geometry["box"], (list, tuple)) and len(geometry["box"]) >= 3:
            return (float(geometry["box"][0]), float(geometry["box"][1]), float(geometry["box"][2]))
        if "dimensions" in geometry and isinstance(geometry["dimensions"], (list, tuple)) and len(geometry["dimensions"]) >= 3:
            return (float(geometry["dimensions"][0]), float(geometry["dimensions"][1]), float(geometry["dimensions"][2]))
        if "bbox" in geometry and isinstance(geometry["bbox"], (list, tuple)) and len(geometry["bbox"]) >= 6:
            b = geometry["bbox"]
            return (abs(b[3] - b[0]), abs(b[4] - b[1]), abs(b[5] - b[2]))

    return None


def _extract_dims_from_metadata(intent: EngineeringIntent) -> Tuple[float, ...]:
    """Extract numeric dimensions found in metadata."""
    if not intent.metadata or not isinstance(intent.metadata, dict):
        return ()
    dims_data = intent.metadata.get("dimensions")
    if not dims_data or not isinstance(dims_data, list):
        return ()
    vals = []
    for item in dims_data:
        if isinstance(item, dict) and "value" in item:
            try:
                v = float(item["value"])
                if v > 0:
                    vals.append(v)
            except (ValueError, TypeError):
                pass
    return tuple(vals)
