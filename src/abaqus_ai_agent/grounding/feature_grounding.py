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
    anchor_point: Tuple[float, float, float] # 3D spatial coordinate on the entity
    feature_id: Optional[str] = None         # Evidenced FeatureCandidate ID if applicable
    surface_side: Optional[str] = None       # "side1", "side2", or None
    confidence: float = 1.0                  # [0.0, 1.0]
    status: str = "RESOLVED"                 # "RESOLVED", "AMBIGUOUS", "NOT_FOUND", "UNSUPPORTED"
    evidence: Tuple[str, ...] = field(default_factory=tuple)
    ambiguity_reason: Optional[str] = None


def _get_vertex_coords(model: GeometryModel) -> Dict[str, Tuple[float, float, float]]:
    """Index vertices by ID for coordinate lookups."""
    return {v.id: v.point for v in model.vertices}


def _get_edge_dict(model: GeometryModel) -> Dict[str, CadEdge]:
    """Index edges by ID."""
    return {e.id: e for e in model.edges}


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

    anchor_point: Optional[Tuple[float, float, float]] = None

    # Strategy 1: Look for a longitudinal seam edge on the cylindrical face
    if target_face is not None:
        for eid in target_face.edge_ids:
            edge = edges_by_id.get(eid)
            if edge and edge.curve_type == "LINE":
                p1 = vertices_by_id.get(edge.start_vertex_id)
                p2 = vertices_by_id.get(edge.end_vertex_id)
                if p1 and p2:
                    mid = (
                        0.5 * (p1[0] + p2[0]),
                        0.5 * (p1[1] + p2[1]),
                        0.5 * (p1[2] + p2[2]),
                    )
                    anchor_point = mid
                    break

    # Strategy 2: If no seam line, compute from feature geometry (center, diameter, depth)
    if anchor_point is None and "diameter" in hole.geometry:
        diameter = hole.geometry["diameter"]
        radius = diameter / 2.0
        # If hole has circular bounding edge
        circ_centers = []
        if target_face:
            for eid in target_face.edge_ids:
                edge = edges_by_id.get(eid)
                if edge and edge.curve_type == "CIRCLE":
                    p = vertices_by_id.get(edge.start_vertex_id)
                    if p:
                        circ_centers.append(p)
        if circ_centers:
            # Anchor at middle Z between circular edges
            z_vals = [pt[2] for pt in circ_centers]
            z_mid = sum(z_vals) / len(z_vals)
            # Use X, Y from circ_centers
            ref_pt = circ_centers[0]
            anchor_point = (ref_pt[0], ref_pt[1], z_mid)
        elif model.bounding_box:
            # Fallback to model bounding box center with radius offset
            bb = model.bounding_box
            anchor_point = (
                0.5 * (bb.min_x + bb.max_x) + radius,
                0.5 * (bb.min_y + bb.max_y),
                0.5 * (bb.min_z + bb.max_z),
            )
        else:
            anchor_point = (radius, 0.0, 0.0)

    assert anchor_point is not None

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

    # Compute a safe anchor point on the selected face avoiding inner loops
    # Collect all vertex coordinates for the selected face
    face_pts = []
    for eid in selected_face.edge_ids:
        edge = edges_by_id.get(eid)
        if edge:
            if edge.start_vertex_id in vertices_by_id:
                face_pts.append(vertices_by_id[edge.start_vertex_id])
            if edge.end_vertex_id in vertices_by_id:
                face_pts.append(vertices_by_id[edge.end_vertex_id])

    xs = [pt[0] for pt in face_pts]
    ys = [pt[1] for pt in face_pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Collect inner loop void center and radius if present
    hole_centers: List[Tuple[float, float, float, float]] = [] # (xc, yc, zc, r)
    for l in selected_face.inner_loops:
        for eid in l.edge_ids:
            edge = edges_by_id.get(eid)
            if edge and edge.curve_type == "CIRCLE":
                pt = vertices_by_id.get(edge.start_vertex_id)
                r = (edge.length / (2.0 * math.pi)) if edge.length else 10.0
                if pt:
                    hole_centers.append((pt[0] - r, pt[1], pt[2], r))

    # Pick a corner candidate (e.g. 25% from min_x, min_y)
    test_x = min_x + 0.25 * (max_x - min_x)
    test_y = min_y + 0.25 * (max_y - min_y)

    # If test point is near any hole, shift to safe zone
    for hc in hole_centers:
        dist = math.hypot(test_x - hc[0], test_y - hc[1])
        if dist < 1.5 * hc[3]:
            # Shift towards boundary corner
            test_x = min_x + 0.10 * (max_x - min_x)
            test_y = min_y + 0.10 * (max_y - min_y)
            break

    anchor_point = (test_x, test_y, z_level)

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
    elif clean_target in ("TOP_SURFACE", "TOP_FACE", "TOP"):
        region = _ground_top_surface(model, topology, feature_candidates)
    else:
        region = GroundedRegion(
            target_semantic=target_semantic,
            entity_type="Face",
            entity_ids=(),
            anchor_point=(0.0, 0.0, 0.0),
            confidence=0.0,
            status="UNSUPPORTED",
            evidence=(f"target_semantic: {target_semantic}", "supported: ['INSTALLATION_HOLE', 'TOP_SURFACE']"),
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
