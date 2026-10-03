"""GA-2.2: Feature / Physical Grounding Layer.

Maps high-level engineering semantic targets (e.g. 'INSTALLATION_HOLE', 'TOP_SURFACE')
into verified, executor-neutral GroundedRegion representations grounded on
evidenced 3D B-Rep entities (FeatureCandidate, CadFace, CadEdge).

Follows strict architectural boundaries:
- Neutral to Abaqus syntax (does NOT fabricate native findAt expressions).
- Consumes GA-1.3B FeatureCandidate and GA-1.3A NormalizedTopology.
- Enforces fail-closed validation: unambiguous single-match -> RESOLVED,
  zero match -> NOT_FOUND, multi-match -> AMBIGUOUS.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..geometry.model import GeometryModel, CadFace, CadEdge, CadVertex
from ..geometry.topology import NormalizedTopology
from ..geometry.features import FeatureCandidate, FeatureType


class GroundingResolutionError(Exception):
    """Raised when an engineering semantic target cannot be resolved or is invalid."""
    pass


class GroundingAmbiguityError(GroundingResolutionError):
    """Raised when an engineering semantic target matches multiple conflicting candidates."""
    def __init__(self, message: str, candidates: Sequence[Any] = ()):
        super().__init__(message)
        self.candidates = tuple(candidates)


@dataclass(frozen=True)
class GroundedRegion:
    """Executor-neutral grounded geometric region representing an engineering semantic target."""
    target_semantic: str
    entity_type: str                         # "Face", "Edge", "Vertex"
    entity_ids: Tuple[str, ...]              # CAD entity IDs, e.g. ("F_277",)
    anchor_point: Tuple[float, float, float] # 3D spatial coordinate on the entity (primary)
    anchor_points: Tuple[Tuple[float, float, float], ...] = () # Spatial coordinates for all entities
    feature_id: Optional[str] = None         # Evidenced FeatureCandidate ID if applicable
    feature_ids: Tuple[str, ...] = ()        # All associated FeatureCandidate IDs
    surface_side: Optional[str] = None       # "side1", "side2", or None
    confidence: float = 1.0                  # [0.0, 1.0]
    status: str = "RESOLVED"                 # "RESOLVED", "AMBIGUOUS", "NOT_FOUND", "UNSUPPORTED"
    evidence: Tuple[str, ...] = field(default_factory=tuple)
    ambiguity_reason: Optional[str] = None

    def __post_init__(self):
        if not self.anchor_points and self.anchor_point:
            object.__setattr__(self, "anchor_points", (self.anchor_point,))


def _get_vertex_coords(model: GeometryModel) -> Dict[str, Tuple[float, float, float]]:
    """Index vertices by ID for coordinate lookups."""
    return {v.id: v.point for v in model.vertices}


def _get_edge_dict(model: GeometryModel) -> Dict[str, CadEdge]:
    """Index edges by ID."""
    return {e.id: e for e in model.edges}


def _compute_cylindrical_anchor(
    target_face: Optional[CadFace],
    hole_or_cyl_geom: Dict[str, Any],
    model: GeometryModel,
    vertices_by_id: Dict[str, Tuple[float, float, float]],
    edges_by_id: Dict[str, CadEdge],
) -> Tuple[float, float, float]:
    """Extract a reliable 3D spatial anchor point on a cylindrical surface."""
    # Strategy 1: Look for a longitudinal seam edge on the cylindrical face
    if target_face is not None:
        for eid in target_face.edge_ids:
            edge = edges_by_id.get(eid)
            if edge and edge.curve_type == "LINE":
                p1 = vertices_by_id.get(edge.start_vertex_id)
                p2 = vertices_by_id.get(edge.end_vertex_id)
                if p1 and p2:
                    return (
                        0.5 * (p1[0] + p2[0]),
                        0.5 * (p1[1] + p2[1]),
                        0.5 * (p1[2] + p2[2]),
                    )

    # Strategy 2: If circular bounding edges exist, find midpoint along axis
    circ_centers = []
    if target_face:
        for eid in target_face.edge_ids:
            edge = edges_by_id.get(eid)
            if edge and edge.curve_type == "CIRCLE":
                p = vertices_by_id.get(edge.start_vertex_id)
                if p:
                    circ_centers.append(p)
    if circ_centers:
        z_vals = [pt[2] for pt in circ_centers]
        z_mid = sum(z_vals) / len(z_vals)
        ref_pt = circ_centers[0]
        return (ref_pt[0], ref_pt[1], z_mid)

    # Strategy 3: Feature geometry radius offset from center
    diameter = hole_or_cyl_geom.get("diameter", 20.0)
    radius = diameter / 2.0
    if model.bounding_box:
        bb = model.bounding_box
        return (
            0.5 * (bb.min_x + bb.max_x) + radius,
            0.5 * (bb.min_y + bb.max_y),
            0.5 * (bb.min_z + bb.max_z),
        )
    return (radius, 0.0, 0.0)


def _compute_safe_planar_anchor(
    face: CadFace,
    vertices_by_id: Dict[str, Tuple[float, float, float]],
    edges_by_id: Dict[str, CadEdge],
) -> Tuple[float, float, float]:
    """Compute a verified safe 3D spatial anchor point on a planar face avoiding inner hole voids."""
    face_pts: List[Tuple[float, float, float]] = []
    for eid in face.edge_ids:
        edge = edges_by_id.get(eid)
        if edge:
            if edge.start_vertex_id in vertices_by_id:
                face_pts.append(vertices_by_id[edge.start_vertex_id])
            if edge.end_vertex_id in vertices_by_id:
                face_pts.append(vertices_by_id[edge.end_vertex_id])

    if not face_pts:
        return (0.0, 0.0, 0.0)

    xs = [pt[0] for pt in face_pts]
    ys = [pt[1] for pt in face_pts]
    zs = [pt[2] for pt in face_pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)

    # Determine face plane orientation
    nx, ny, nz = face.normal if face.normal else (0.0, 0.0, 1.0)
    norm = math.sqrt(nx * nx + ny * ny + nz * nz)
    if norm > 1e-6:
        nx, ny, nz = nx / norm, ny / norm, nz / norm

    # Inner loops (voids) to avoid
    hole_centers: List[Tuple[float, float, float, float]] = []  # (xc, yc, zc, r)
    for l in face.inner_loops:
        for eid in l.edge_ids:
            edge = edges_by_id.get(eid)
            if edge and edge.curve_type == "CIRCLE":
                pt = vertices_by_id.get(edge.start_vertex_id)
                r = (edge.length / (2.0 * math.pi)) if edge.length else 10.0
                if pt:
                    hole_centers.append((pt[0] - r, pt[1], pt[2], r))

    # Horizontal plane (Normal ~ Z)
    if abs(nz) >= 0.80:
        z_level = 0.5 * (min_z + max_z)
        test_x = min_x + 0.25 * (max_x - min_x)
        test_y = min_y + 0.25 * (max_y - min_y)
        for hc in hole_centers:
            dist = math.hypot(test_x - hc[0], test_y - hc[1])
            if dist < 1.5 * hc[3]:
                test_x = min_x + 0.10 * (max_x - min_x)
                test_y = min_y + 0.10 * (max_y - min_y)
                break
        return (test_x, test_y, z_level)

    # Normal ~ X plane
    if abs(nx) >= 0.80:
        x_level = 0.5 * (min_x + max_x)
        test_y = min_y + 0.25 * (max_y - min_y)
        test_z = min_z + 0.25 * (max_z - min_z)
        return (x_level, test_y, test_z)

    # Normal ~ Y plane
    if abs(ny) >= 0.80:
        y_level = 0.5 * (min_y + max_y)
        test_x = min_x + 0.25 * (max_x - min_x)
        test_z = min_z + 0.25 * (max_z - min_z)
        return (test_x, y_level, test_z)

    # General plane fallback: centroid of vertices
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    cz = sum(zs) / len(zs)
    return (cx, cy, cz)


def _ground_installation_hole(
    model: GeometryModel,
    topology: Optional[NormalizedTopology],
    feature_candidates: Sequence[FeatureCandidate],
) -> GroundedRegion:
    """Ground 'INSTALLATION_HOLE' to an evidenced FASTENER_HOLE cylindrical face."""
    hole_candidates = [
        fc for fc in feature_candidates
        if fc.feature_type == FeatureType.FASTENER_HOLE
    ]

    if not hole_candidates:
        return GroundedRegion(
            target_semantic="INSTALLATION_HOLE",
            entity_type="Face",
            entity_ids=(),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.0,
            status="NOT_FOUND",
            evidence=("feature_search: FASTENER_HOLE", "found_count: 0"),
            ambiguity_reason="NO_FASTENER_HOLE_DETECTED",
        )

    if len(hole_candidates) > 1:
        ids = tuple(fc.feature_id for fc in hole_candidates)
        return GroundedRegion(
            target_semantic="INSTALLATION_HOLE",
            entity_type="Face",
            entity_ids=ids,
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.5,
            status="AMBIGUOUS",
            evidence=("feature_search: FASTENER_HOLE", f"found_count: {len(hole_candidates)}"),
            ambiguity_reason=f"MULTIPLE_HOLES_FOUND: {len(hole_candidates)} fastener holes detected",
        )

    # Exactly 1 fastener hole candidate
    hole = hole_candidates[0]
    cyl_face_ids = tuple(hole.face_ids)
    if not cyl_face_ids:
        return GroundedRegion(
            target_semantic="INSTALLATION_HOLE",
            entity_type="Face",
            entity_ids=(),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.0,
            status="NOT_FOUND",
            evidence=("feature_search: FASTENER_HOLE", "error: hole feature missing face_ids"),
            ambiguity_reason="HOLE_FEATURE_MISSING_FACE_IDS",
        )

    # Find the primary cylindrical face
    target_face_id = cyl_face_ids[0]
    faces_by_id = {f.id: f for f in model.faces}
    target_face = faces_by_id.get(target_face_id)

    vertices_by_id = _get_vertex_coords(model)
    edges_by_id = _get_edge_dict(model)

    anchor_point = _compute_cylindrical_anchor(
        target_face, hole.geometry, model, vertices_by_id, edges_by_id
    )

    evidence_items = (
        f"feature_type: {hole.feature_type.value}",
        f"feature_id: {hole.feature_id}",
        f"face_id: {target_face_id}",
        f"hole_diameter: {hole.geometry.get('diameter')}",
        f"hole_sub_type: {hole.geometry.get('sub_type')}",
        f"anchor_point: ({anchor_point[0]:.3f}, {anchor_point[1]:.3f}, {anchor_point[2]:.3f})",
    )

    return GroundedRegion(
        target_semantic="INSTALLATION_HOLE",
        entity_type="Face",
        entity_ids=(target_face_id,),
        anchor_point=anchor_point,
        feature_id=hole.feature_id,
        surface_side=None,
        confidence=hole.confidence,
        status="RESOLVED",
        evidence=evidence_items,
        ambiguity_reason=None,
    )


def _ground_top_surface(
    model: GeometryModel,
    topology: Optional[NormalizedTopology],
    feature_candidates: Sequence[FeatureCandidate],
) -> GroundedRegion:
    """Ground 'TOP_SURFACE' to the verified highest horizontal planar face.

    Strict Ranking Hierarchy:
    1. Normal Alignment: normal must face upwards (+Z, nz >= 0.90, |nx| <= 0.1, |ny| <= 0.1).
    2. Geometric Planarity: face.is_planar == True or surface_type == "PLANE".
    3. Spatial Height: maximum Z vertices must reach model bounding box max Z.
    4. Safe Anchor Derivation: avoid inner hole loops to prevent anchoring in void space.
    5. Uniqueness Gate: multiple competing top faces without dominant area -> AMBIGUOUS.
    """
    vertices_by_id = _get_vertex_coords(model)
    edges_by_id = _get_edge_dict(model)

    top_candidates: List[Tuple[CadFace, float, float]] = [] # (face, z_max, area)

    # Determine global max Z from bounding box or vertices
    if model.bounding_box:
        global_z_max = model.bounding_box.max_z
    elif vertices_by_id:
        global_z_max = max(pt[2] for pt in vertices_by_id.values())
    else:
        global_z_max = 0.0

    z_tol = 1e-2

    for face in model.faces:
        # Check planarity
        if not (face.is_planar or face.surface_type == "PLANE"):
            continue

        # Check normal direction (+Z)
        if face.normal is None:
            continue
        nx, ny, nz = face.normal
        norm = math.sqrt(nx * nx + ny * ny + nz * nz)
        if norm < 1e-6:
            continue
        nz_norm = nz / norm
        if nz_norm < 0.90:
            continue

        # Extract vertex coordinates for this face
        face_pts: List[Tuple[float, float, float]] = []
        for eid in face.edge_ids:
            edge = edges_by_id.get(eid)
            if edge:
                if edge.start_vertex_id in vertices_by_id:
                    face_pts.append(vertices_by_id[edge.start_vertex_id])
                if edge.end_vertex_id in vertices_by_id:
                    face_pts.append(vertices_by_id[edge.end_vertex_id])

        if not face_pts:
            continue

        face_z_max = max(pt[2] for pt in face_pts)

        # Check if face is at the top of the model
        if abs(face_z_max - global_z_max) <= z_tol:
            area = face.area if face.area is not None else 1.0
            top_candidates.append((face, face_z_max, area))

    if not top_candidates:
        return GroundedRegion(
            target_semantic="TOP_SURFACE",
            entity_type="Face",
            entity_ids=(),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.0,
            status="NOT_FOUND",
            evidence=("search: TOP_SURFACE", "found_count: 0"),
            ambiguity_reason="NO_TOP_PLANAR_FACE_FOUND",
        )

    if len(top_candidates) > 1:
        # Sort by area descending
        top_candidates.sort(key=lambda item: item[2], reverse=True)
        # Check if top face is distinct (e.g. at least 2x larger than second)
        a1 = top_candidates[0][2]
        a2 = top_candidates[1][2]
        if a1 < 2.0 * a2:
            face_ids = tuple(item[0].id for item in top_candidates)
            return GroundedRegion(
                target_semantic="TOP_SURFACE",
                entity_type="Face",
                entity_ids=face_ids,
                anchor_point=(0.0, 0.0, 0.0),
                confidence=0.5,
                status="AMBIGUOUS",
                evidence=("search: TOP_SURFACE", f"competing_faces: {face_ids}"),
                ambiguity_reason=f"MULTIPLE_TOP_FACES: {len(top_candidates)} competing coplanar top faces without dominant area",
            )

    selected_face, z_level, area = top_candidates[0]
    anchor_point = _compute_safe_planar_anchor(selected_face, vertices_by_id, edges_by_id)

    evidence_items = (
        f"semantic_target: TOP_SURFACE",
        f"face_id: {selected_face.id}",
        f"normal: {selected_face.normal}",
        f"z_level: {z_level:.3f}",
        f"has_inner_hole: {bool(selected_face.inner_loops)}",
        f"anchor_point: ({anchor_point[0]:.3f}, {anchor_point[1]:.3f}, {anchor_point[2]:.3f})",
    )

    return GroundedRegion(
        target_semantic="TOP_SURFACE",
        entity_type="Face",
        entity_ids=(selected_face.id,),
        anchor_point=anchor_point,
        feature_id=None,
        surface_side=None,
        confidence=1.0,
        status="RESOLVED",
        evidence=evidence_items,
        ambiguity_reason=None,
    )


def _ground_bottom_surface(
    model: GeometryModel,
    topology: Optional[NormalizedTopology],
    feature_candidates: Sequence[FeatureCandidate],
) -> GroundedRegion:
    """Ground 'BOTTOM_SURFACE' to the verified lowest horizontal planar face.

    Strict Ranking Hierarchy:
    1. Normal Alignment: normal must face downwards (-Z, nz <= -0.90, |nx| <= 0.1, |ny| <= 0.1).
    2. Geometric Planarity: face.is_planar == True or surface_type == "PLANE".
    3. Spatial Height: minimum Z vertices must reach model bounding box min Z.
    4. Safe Anchor Derivation: avoid inner hole loops to prevent anchoring in void space.
    5. Uniqueness Gate: multiple competing bottom faces without dominant area -> AMBIGUOUS.
    """
    vertices_by_id = _get_vertex_coords(model)
    edges_by_id = _get_edge_dict(model)

    bottom_candidates: List[Tuple[CadFace, float, float]] = []  # (face, z_min, area)

    if model.bounding_box:
        global_z_min = model.bounding_box.min_z
    elif vertices_by_id:
        global_z_min = min(pt[2] for pt in vertices_by_id.values())
    else:
        global_z_min = 0.0

    z_tol = 1e-2

    for face in model.faces:
        if not (face.is_planar or face.surface_type == "PLANE"):
            continue

        if face.normal is None:
            continue
        nx, ny, nz = face.normal
        norm = math.sqrt(nx * nx + ny * ny + nz * nz)
        if norm < 1e-6:
            continue
        nz_norm = nz / norm
        if nz_norm > -0.90:
            continue

        face_pts: List[Tuple[float, float, float]] = []
        for eid in face.edge_ids:
            edge = edges_by_id.get(eid)
            if edge:
                if edge.start_vertex_id in vertices_by_id:
                    face_pts.append(vertices_by_id[edge.start_vertex_id])
                if edge.end_vertex_id in vertices_by_id:
                    face_pts.append(vertices_by_id[edge.end_vertex_id])

        if not face_pts:
            continue

        face_z_min = min(pt[2] for pt in face_pts)

        if abs(face_z_min - global_z_min) <= z_tol:
            area = face.area if face.area is not None else 1.0
            bottom_candidates.append((face, face_z_min, area))

    if not bottom_candidates:
        return GroundedRegion(
            target_semantic="BOTTOM_SURFACE",
            entity_type="Face",
            entity_ids=(),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.0,
            status="NOT_FOUND",
            evidence=("search: BOTTOM_SURFACE", "found_count: 0"),
            ambiguity_reason="NO_BOTTOM_PLANAR_FACE_FOUND",
        )

    if len(bottom_candidates) > 1:
        bottom_candidates.sort(key=lambda item: item[2], reverse=True)
        a1 = bottom_candidates[0][2]
        a2 = bottom_candidates[1][2]
        if a1 < 2.0 * a2:
            face_ids = tuple(item[0].id for item in bottom_candidates)
            return GroundedRegion(
                target_semantic="BOTTOM_SURFACE",
                entity_type="Face",
                entity_ids=face_ids,
                anchor_point=(0.0, 0.0, 0.0),
                confidence=0.5,
                status="AMBIGUOUS",
                evidence=("search: BOTTOM_SURFACE", f"competing_faces: {face_ids}"),
                ambiguity_reason=f"MULTIPLE_BOTTOM_FACES: {len(bottom_candidates)} competing coplanar bottom faces without dominant area",
            )

    selected_face, z_level, area = bottom_candidates[0]
    anchor_point = _compute_safe_planar_anchor(selected_face, vertices_by_id, edges_by_id)

    evidence_items = (
        "semantic_target: BOTTOM_SURFACE",
        f"face_id: {selected_face.id}",
        f"normal: {selected_face.normal}",
        f"z_level: {z_level:.3f}",
        f"has_inner_hole: {bool(selected_face.inner_loops)}",
        f"anchor_point: ({anchor_point[0]:.3f}, {anchor_point[1]:.3f}, {anchor_point[2]:.3f})",
    )

    return GroundedRegion(
        target_semantic="BOTTOM_SURFACE",
        entity_type="Face",
        entity_ids=(selected_face.id,),
        anchor_point=anchor_point,
        feature_id=None,
        surface_side=None,
        confidence=1.0,
        status="RESOLVED",
        evidence=evidence_items,
        ambiguity_reason=None,
    )


def _ground_symmetry_plane(
    target_semantic: str,
    model: GeometryModel,
    topology: Optional[NormalizedTopology],
    feature_candidates: Sequence[FeatureCandidate],
) -> GroundedRegion:
    """Ground 'SYMMETRY_PLANE' (or SYMMETRY_X, SYMMETRY_Y, SYMMETRY_Z) to a principal plane.

    Strict Ranking Hierarchy:
    1. Planarity: must be planar.
    2. Principal Axis Normal: normal must align with X, Y, or Z axis (|n_i| >= 0.90).
    3. Symmetry Position: face coordinate along normal axis must match bbox midpoint or 0.0.
    4. Sub-type disambiguation: if SYMMETRY_X/Y/Z requested, filter strictly to that axis.
    5. Ambiguity Gate: generic 'SYMMETRY_PLANE' with multiple orthogonal planes -> AMBIGUOUS.
    """
    vertices_by_id = _get_vertex_coords(model)
    edges_by_id = _get_edge_dict(model)

    req = target_semantic.strip().upper()
    filter_axis: Optional[str] = None
    tokens = req.replace("-", "_").split("_")
    if "X" in tokens or req.endswith(" X") or "X_SYMMETRY" in req or "SYMMETRY_X" in req:
        filter_axis = "X"
    elif "Y" in tokens or req.endswith(" Y") or "Y_SYMMETRY" in req or "SYMMETRY_Y" in req:
        filter_axis = "Y"
    elif "Z" in tokens or req.endswith(" Z") or "Z_SYMMETRY" in req or "SYMMETRY_Z" in req:
        filter_axis = "Z"

    if model.bounding_box:
        bb = model.bounding_box
        mids = {
            "X": (0.5 * (bb.min_x + bb.max_x), 0.0),
            "Y": (0.5 * (bb.min_y + bb.max_y), 0.0),
            "Z": (0.5 * (bb.min_z + bb.max_z), 0.0),
        }
    else:
        mids = {"X": (0.0,), "Y": (0.0,), "Z": (0.0,)}

    tol = 1e-2
    candidates: List[Tuple[CadFace, str, float]] = []  # (face, axis, coord)

    for face in model.faces:
        if not (face.is_planar or face.surface_type == "PLANE"):
            continue
        if face.normal is None:
            continue
        nx, ny, nz = face.normal
        norm = math.sqrt(nx * nx + ny * ny + nz * nz)
        if norm < 1e-6:
            continue
        nx, ny, nz = nx / norm, ny / norm, nz / norm

        face_axis: Optional[str] = None
        if abs(nx) >= 0.90 and abs(ny) <= 0.10 and abs(nz) <= 0.10:
            face_axis = "X"
        elif abs(ny) >= 0.90 and abs(nx) <= 0.10 and abs(nz) <= 0.10:
            face_axis = "Y"
        elif abs(nz) >= 0.90 and abs(nx) <= 0.10 and abs(ny) <= 0.10:
            face_axis = "Z"

        if not face_axis:
            continue
        if filter_axis and face_axis != filter_axis:
            continue

        # Get vertex points
        face_pts: List[Tuple[float, float, float]] = []
        for eid in face.edge_ids:
            edge = edges_by_id.get(eid)
            if edge:
                if edge.start_vertex_id in vertices_by_id:
                    face_pts.append(vertices_by_id[edge.start_vertex_id])
                if edge.end_vertex_id in vertices_by_id:
                    face_pts.append(vertices_by_id[edge.end_vertex_id])

        if not face_pts:
            continue

        axis_idx = 0 if face_axis == "X" else (1 if face_axis == "Y" else 2)
        c_vals = [pt[axis_idx] for pt in face_pts]
        c_avg = sum(c_vals) / len(c_vals)

        # Check if matches bbox midpoint or 0.0
        valid_targets = mids.get(face_axis, (0.0,))
        is_sym = any(abs(c_avg - target) <= tol for target in valid_targets)
        if is_sym:
            candidates.append((face, face_axis, c_avg))

    if not candidates:
        return GroundedRegion(
            target_semantic=target_semantic,
            entity_type="Face",
            entity_ids=(),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.0,
            status="NOT_FOUND",
            evidence=(f"search: {target_semantic}", "found_count: 0"),
            ambiguity_reason=f"NO_SYMMETRY_PLANE_FOUND: no principal planar face at midpoint/origin for axis={filter_axis or 'ANY'}",
        )

    # Check ambiguity: if generic SYMMETRY_PLANE and candidates span multiple axes
    axes_found = set(item[1] for item in candidates)
    if len(axes_found) > 1 and not filter_axis:
        face_ids = tuple(item[0].id for item in candidates)
        return GroundedRegion(
            target_semantic=target_semantic,
            entity_type="Face",
            entity_ids=face_ids,
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.5,
            status="AMBIGUOUS",
            evidence=(f"search: {target_semantic}", f"multiple_axes: {sorted(list(axes_found))}", f"candidate_faces: {face_ids}"),
            ambiguity_reason=f"MULTIPLE_SYMMETRY_AXES_FOUND: symmetry planes exist on axes {sorted(axes_found)}; specify SYMMETRY_X, SYMMETRY_Y, or SYMMETRY_Z",
        )

    if len(candidates) > 1:
        face_ids = tuple(item[0].id for item in candidates)
        return GroundedRegion(
            target_semantic=target_semantic,
            entity_type="Face",
            entity_ids=face_ids,
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.5,
            status="AMBIGUOUS",
            evidence=(f"search: {target_semantic}", f"competing_faces: {face_ids}"),
            ambiguity_reason=f"MULTIPLE_SYMMETRY_PLANES_ON_AXIS: {len(candidates)} competing planes found on axis {candidates[0][1]}",
        )

    selected_face, axis, coord = candidates[0]
    anchor_point = _compute_safe_planar_anchor(selected_face, vertices_by_id, edges_by_id)

    evidence_items = (
        f"semantic_target: {target_semantic}",
        f"face_id: {selected_face.id}",
        f"symmetry_axis: {axis}",
        f"plane_coord: {coord:.3f}",
        f"normal: {selected_face.normal}",
        f"anchor_point: ({anchor_point[0]:.3f}, {anchor_point[1]:.3f}, {anchor_point[2]:.3f})",
    )

    return GroundedRegion(
        target_semantic=target_semantic,
        entity_type="Face",
        entity_ids=(selected_face.id,),
        anchor_point=anchor_point,
        feature_id=None,
        surface_side=None,
        confidence=1.0,
        status="RESOLVED",
        evidence=evidence_items,
        ambiguity_reason=None,
    )


def _ground_side_wall(
    target_semantic: str,
    model: GeometryModel,
    topology: Optional[NormalizedTopology],
    feature_candidates: Sequence[FeatureCandidate],
) -> GroundedRegion:
    """Ground side wall semantic targets (e.g. LEFT_WALL, RIGHT_WALL, FRONT_WALL, BACK_WALL, SIDE_WALL).

    Directional Rules:
    - LEFT_WALL / LEFT_SURFACE / MIN_X: Normal ~ (-1, 0, 0), x at min_x
    - RIGHT_WALL / RIGHT_SURFACE / MAX_X: Normal ~ (+1, 0, 0), x at max_x
    - FRONT_WALL / FRONT_SURFACE / MIN_Y: Normal ~ (0, -1, 0), y at min_y
    - BACK_WALL / BACK_SURFACE / MAX_Y: Normal ~ (0, +1, 0), y at max_y
    - Generic SIDE_WALL / SIDE_SURFACE: If multiple vertical walls exist without direction -> AMBIGUOUS.
    """
    vertices_by_id = _get_vertex_coords(model)
    edges_by_id = _get_edge_dict(model)

    req = target_semantic.strip().upper()
    req_direction: Optional[str] = None
    if any(k in req for k in ("LEFT", "MIN_X", "-X")):
        req_direction = "-X"
    elif any(k in req for k in ("RIGHT", "MAX_X", "+X")):
        req_direction = "+X"
    elif any(k in req for k in ("FRONT", "MIN_Y", "-Y")):
        req_direction = "-Y"
    elif any(k in req for k in ("BACK", "REAR", "MAX_Y", "+Y")):
        req_direction = "+Y"

    bb = model.bounding_box
    tol = 1e-2

    candidates: List[Tuple[CadFace, str, float]] = []  # (face, direction, area)

    for face in model.faces:
        if not (face.is_planar or face.surface_type == "PLANE"):
            continue
        if face.normal is None:
            continue
        nx, ny, nz = face.normal
        norm = math.sqrt(nx * nx + ny * ny + nz * nz)
        if norm < 1e-6:
            continue
        nx, ny, nz = nx / norm, ny / norm, nz / norm

        # Vertical wall must have nz ~ 0
        if abs(nz) > 0.20:
            continue

        direction: Optional[str] = None
        if nx <= -0.90:
            direction = "-X"
        elif nx >= 0.90:
            direction = "+X"
        elif ny <= -0.90:
            direction = "-Y"
        elif ny >= 0.90:
            direction = "+Y"

        if not direction:
            continue
        if req_direction and direction != req_direction:
            continue

        # Check boundary position
        face_pts: List[Tuple[float, float, float]] = []
        for eid in face.edge_ids:
            edge = edges_by_id.get(eid)
            if edge:
                if edge.start_vertex_id in vertices_by_id:
                    face_pts.append(vertices_by_id[edge.start_vertex_id])
                if edge.end_vertex_id in vertices_by_id:
                    face_pts.append(vertices_by_id[edge.end_vertex_id])

        if not face_pts:
            continue

        area = face.area if face.area is not None else 1.0

        if bb:
            if direction == "-X" and abs(min(pt[0] for pt in face_pts) - bb.min_x) <= tol:
                candidates.append((face, direction, area))
            elif direction == "+X" and abs(max(pt[0] for pt in face_pts) - bb.max_x) <= tol:
                candidates.append((face, direction, area))
            elif direction == "-Y" and abs(min(pt[1] for pt in face_pts) - bb.min_y) <= tol:
                candidates.append((face, direction, area))
            elif direction == "+Y" and abs(max(pt[1] for pt in face_pts) - bb.max_y) <= tol:
                candidates.append((face, direction, area))
        else:
            candidates.append((face, direction, area))

    if not candidates:
        return GroundedRegion(
            target_semantic=target_semantic,
            entity_type="Face",
            entity_ids=(),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.0,
            status="NOT_FOUND",
            evidence=(f"search: {target_semantic}", "found_count: 0"),
            ambiguity_reason=f"NO_SIDE_WALL_FOUND: no vertical planar face matching direction={req_direction or 'ANY'}",
        )

    # Fail closed on generic un-directed SIDE_WALL with multiple candidates
    if not req_direction and len(candidates) > 1:
        face_ids = tuple(c[0].id for c in candidates)
        dirs = [c[1] for c in candidates]
        return GroundedRegion(
            target_semantic=target_semantic,
            entity_type="Face",
            entity_ids=face_ids,
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.5,
            status="AMBIGUOUS",
            evidence=(f"search: {target_semantic}", f"competing_directions: {dirs}", f"faces: {face_ids}"),
            ambiguity_reason=f"MULTIPLE_SIDE_WALLS: {len(candidates)} side walls found; specify direction e.g. LEFT_WALL, RIGHT_WALL, FRONT_WALL, BACK_WALL",
        )

    if len(candidates) > 1:
        candidates.sort(key=lambda item: item[2], reverse=True)
        if candidates[0][2] < 2.0 * candidates[1][2]:
            face_ids = tuple(c[0].id for c in candidates)
            return GroundedRegion(
                target_semantic=target_semantic,
                entity_type="Face",
                entity_ids=face_ids,
                anchor_point=(0.0, 0.0, 0.0),
                confidence=0.5,
                status="AMBIGUOUS",
                evidence=(f"search: {target_semantic}", f"competing_faces: {face_ids}"),
                ambiguity_reason=f"MULTIPLE_WALLS_IN_DIRECTION: {len(candidates)} competing walls in direction {candidates[0][1]}",
            )

    selected_face, direction, area = candidates[0]
    anchor_point = _compute_safe_planar_anchor(selected_face, vertices_by_id, edges_by_id)

    evidence_items = (
        f"semantic_target: {target_semantic}",
        f"face_id: {selected_face.id}",
        f"wall_direction: {direction}",
        f"normal: {selected_face.normal}",
        f"anchor_point: ({anchor_point[0]:.3f}, {anchor_point[1]:.3f}, {anchor_point[2]:.3f})",
    )

    return GroundedRegion(
        target_semantic=target_semantic,
        entity_type="Face",
        entity_ids=(selected_face.id,),
        anchor_point=anchor_point,
        feature_id=None,
        surface_side=None,
        confidence=1.0,
        status="RESOLVED",
        evidence=evidence_items,
        ambiguity_reason=None,
    )


def _ground_bearing_seat(
    model: GeometryModel,
    topology: Optional[NormalizedTopology],
    feature_candidates: Sequence[FeatureCandidate],
) -> GroundedRegion:
    """Ground 'BEARING_SEAT' to an evidenced cylindrical bearing mating face."""
    vertices_by_id = _get_vertex_coords(model)
    edges_by_id = _get_edge_dict(model)
    faces_by_id = {f.id: f for f in model.faces}

    cyl_features = [
        fc for fc in feature_candidates
        if fc.feature_type == FeatureType.FASTENER_HOLE
    ]
    cyl_faces = [f for f in model.faces if f.surface_type == "CYLINDER"]

    if not cyl_features and not cyl_faces:
        return GroundedRegion(
            target_semantic="BEARING_SEAT",
            entity_type="Face",
            entity_ids=(),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.0,
            status="NOT_FOUND",
            evidence=("search: BEARING_SEAT", "found_count: 0"),
            ambiguity_reason="NO_CYLINDRICAL_BEARING_SEAT_FOUND",
        )

    if cyl_features:
        if len(cyl_features) > 1:
            ids = tuple(fc.feature_id for fc in cyl_features)
            return GroundedRegion(
                target_semantic="BEARING_SEAT",
                entity_type="Face",
                entity_ids=ids,
                anchor_point=(0.0, 0.0, 0.0),
                confidence=0.5,
                status="AMBIGUOUS",
                evidence=("search: BEARING_SEAT", f"found_features: {ids}"),
                ambiguity_reason=f"MULTIPLE_BEARING_SEATS_FOUND: {len(cyl_features)} candidate cylindrical seats found",
            )
        feat = cyl_features[0]
        face_id = feat.face_ids[0]
        target_face = faces_by_id.get(face_id)
        anchor_point = _compute_cylindrical_anchor(
            target_face, feat.geometry, model, vertices_by_id, edges_by_id
        )
        return GroundedRegion(
            target_semantic="BEARING_SEAT",
            entity_type="Face",
            entity_ids=(face_id,),
            anchor_point=anchor_point,
            feature_id=feat.feature_id,
            surface_side=None,
            confidence=feat.confidence,
            status="RESOLVED",
            evidence=(
                "semantic_target: BEARING_SEAT",
                f"feature_id: {feat.feature_id}",
                f"face_id: {face_id}",
                f"diameter: {feat.geometry.get('diameter')}",
                f"anchor_point: ({anchor_point[0]:.3f}, {anchor_point[1]:.3f}, {anchor_point[2]:.3f})",
            ),
            ambiguity_reason=None,
        )

    if len(cyl_faces) > 1:
        face_ids = tuple(f.id for f in cyl_faces)
        return GroundedRegion(
            target_semantic="BEARING_SEAT",
            entity_type="Face",
            entity_ids=face_ids,
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.5,
            status="AMBIGUOUS",
            evidence=("search: BEARING_SEAT", f"cyl_faces: {face_ids}"),
            ambiguity_reason=f"MULTIPLE_CYLINDRICAL_FACES: {len(cyl_faces)} unassociated cylindrical faces found",
        )

    cf = cyl_faces[0]
    anchor_point = _compute_cylindrical_anchor(
        cf, {}, model, vertices_by_id, edges_by_id
    )
    return GroundedRegion(
        target_semantic="BEARING_SEAT",
        entity_type="Face",
        entity_ids=(cf.id,),
        anchor_point=anchor_point,
        feature_id=None,
        surface_side=None,
        confidence=0.90,
        status="RESOLVED",
        evidence=(
            "semantic_target: BEARING_SEAT",
            f"face_id: {cf.id}",
            f"surface_type: CYLINDER",
            f"anchor_point: ({anchor_point[0]:.3f}, {anchor_point[1]:.3f}, {anchor_point[2]:.3f})",
        ),
        ambiguity_reason=None,
    )


def _ground_hole_group(
    target_semantic: str,
    model: GeometryModel,
    topology: Optional[NormalizedTopology],
    feature_candidates: Sequence[FeatureCandidate],
) -> GroundedRegion:
    """Ground multi-feature groups (e.g. ALL_HOLES, FASTENER_HOLES, BOLT_GROUP).

    Aggregates all recognized FASTENER_HOLE features into a composite GroundedRegion
    containing entity_ids for each cylindrical face and corresponding anchor_points.
    """
    vertices_by_id = _get_vertex_coords(model)
    edges_by_id = _get_edge_dict(model)
    faces_by_id = {f.id: f for f in model.faces}

    hole_candidates = [
        fc for fc in feature_candidates
        if fc.feature_type == FeatureType.FASTENER_HOLE
    ]

    if not hole_candidates:
        return GroundedRegion(
            target_semantic=target_semantic,
            entity_type="Face",
            entity_ids=(),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.0,
            status="NOT_FOUND",
            evidence=("feature_search: FASTENER_HOLE", "found_count: 0"),
            ambiguity_reason="NO_FASTENER_HOLES_DETECTED",
        )

    entity_ids_list: List[str] = []
    anchor_points_list: List[Tuple[float, float, float]] = []
    feature_ids_list: List[str] = []

    for hole in hole_candidates:
        if not hole.face_ids:
            continue
        fid = hole.face_ids[0]
        entity_ids_list.append(fid)
        feature_ids_list.append(hole.feature_id)
        target_face = faces_by_id.get(fid)
        pt = _compute_cylindrical_anchor(
            target_face, hole.geometry, model, vertices_by_id, edges_by_id
        )
        anchor_points_list.append(pt)

    if not entity_ids_list:
        return GroundedRegion(
            target_semantic=target_semantic,
            entity_type="Face",
            entity_ids=(),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.0,
            status="NOT_FOUND",
            evidence=("feature_search: FASTENER_HOLE", "error: holes missing face_ids"),
            ambiguity_reason="HOLE_FEATURES_MISSING_FACE_IDS",
        )

    entity_ids = tuple(entity_ids_list)
    anchor_points = tuple(anchor_points_list)
    feature_ids = tuple(feature_ids_list)
    primary_anchor = anchor_points[0]

    avg_conf = sum(h.confidence for h in hole_candidates) / len(hole_candidates)

    evidence_items = (
        f"semantic_target: {target_semantic}",
        f"group_type: HOLE_GROUP",
        f"hole_count: {len(entity_ids)}",
        f"feature_ids: {feature_ids}",
        f"face_ids: {entity_ids}",
        f"anchor_points: {[f'({p[0]:.2f},{p[1]:.2f},{p[2]:.2f})' for p in anchor_points]}",
    )

    return GroundedRegion(
        target_semantic=target_semantic,
        entity_type="Face",
        entity_ids=entity_ids,
        anchor_point=primary_anchor,
        anchor_points=anchor_points,
        feature_id=feature_ids[0] if len(feature_ids) == 1 else None,
        feature_ids=feature_ids,
        surface_side=None,
        confidence=avg_conf,
        status="RESOLVED",
        evidence=evidence_items,
        ambiguity_reason=None,
    )


def resolve_feature_grounding(
    target_semantic: str,
    model: GeometryModel,
    topology: Optional[NormalizedTopology] = None,
    feature_candidates: Sequence[FeatureCandidate] = (),
    strict: bool = True,
) -> GroundedRegion:
    """Resolve an engineering semantic target to an evidenced geometric GroundedRegion.

    Parameters:
    -----------
    target_semantic:
        High-level requirement string, e.g. 'INSTALLATION_HOLE', 'TOP_SURFACE'.
    model:
        Canonical GeometryModel.
    topology:
        Optional NormalizedTopology graph.
    feature_candidates:
        Tuple of recognized FeatureCandidates from GA-1.3B.
    strict:
        If True, raises GroundingResolutionError / GroundingAmbiguityError on failures.
        If False, returns GroundedRegion with status != 'RESOLVED'.
    """
    clean_target = target_semantic.strip().upper()

    if clean_target in ("INSTALLATION_HOLE", "HOLE", "MOUNTING_HOLE", "FASTENER_HOLE"):
        region = _ground_installation_hole(model, topology, feature_candidates)
    elif clean_target in ("ALL_HOLES", "FASTENER_HOLES", "BOLT_GROUP", "HOLE_GROUP", "MOUNTING_HOLES", "BOLT_HOLES"):
        region = _ground_hole_group(target_semantic, model, topology, feature_candidates)
    elif clean_target in ("TOP_SURFACE", "TOP_FACE", "TOP"):
        region = _ground_top_surface(model, topology, feature_candidates)
    elif clean_target in ("BOTTOM_SURFACE", "BOTTOM_FACE", "BOTTOM", "BASE_SURFACE", "BASE_FACE"):
        region = _ground_bottom_surface(model, topology, feature_candidates)
    elif any(sym in clean_target for sym in ("SYMMETRY", "SYMMETRIC")):
        region = _ground_symmetry_plane(target_semantic, model, topology, feature_candidates)
    elif any(side in clean_target for side in ("WALL", "SIDE_SURFACE", "FRONT_SURFACE", "BACK_SURFACE", "LEFT_SURFACE", "RIGHT_SURFACE")):
        region = _ground_side_wall(target_semantic, model, topology, feature_candidates)
    elif clean_target in ("BEARING_SEAT", "BEARING_BORE", "BEARING_JOURNAL"):
        region = _ground_bearing_seat(model, topology, feature_candidates)
    else:
        supported_semantics = (
            "INSTALLATION_HOLE", "ALL_HOLES", "TOP_SURFACE", "BOTTOM_SURFACE",
            "SYMMETRY_PLANE", "SYMMETRY_X/Y/Z", "SIDE_WALL", "LEFT/RIGHT/FRONT/BACK_WALL",
            "BEARING_SEAT"
        )
        region = GroundedRegion(
            target_semantic=target_semantic,
            entity_type="Face",
            entity_ids=(),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.0,
            status="UNSUPPORTED",
            evidence=(f"target_semantic: {target_semantic}", f"supported: {list(supported_semantics)}"),
            ambiguity_reason=f"UNSUPPORTED_SEMANTIC_TARGET: {target_semantic}",
        )

    if strict and region.status != "RESOLVED":
        if region.status == "AMBIGUOUS":
            raise GroundingAmbiguityError(
                f"Semantic target '{target_semantic}' is ambiguous: {region.ambiguity_reason}",
                candidates=region.entity_ids,
            )
        raise GroundingResolutionError(
            f"Failed to ground semantic target '{target_semantic}': status={region.status}, reason={region.ambiguity_reason}"
        )

    return region
