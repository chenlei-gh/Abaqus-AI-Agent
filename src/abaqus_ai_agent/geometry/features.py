"""Unified Feature Recognition Contracts and Fastener Hole Detection for Track GA-1.3B.

Establishes a canonical, reusable FeatureCandidate/FeatureEvidence contract across
all industrial engineering features (Holes, Fillets, Chamfers, Ribs, Contact Planes).
Implements multi-criteria Fastener Hole recognition differentiating:
- Through holes (dual planar penetration)
- Blind holes (flat or conical bottom termination)
- Counterbore holes (stepped coaxial cylindrical faces with planar seat)
- Countersink holes (conical chamfered entrance leading into cylindrical barrel)
- Generic cavities / non-fastener cylindrical voids (preventing false positives)

Zero duplicate CAD kernel rule: operates directly on GeometryModel and NormalizedTopology.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from ..capability_boundary import CapabilityStatus
from .model import CadFace, CadLoop, GeometryModel
from .topology import NormalizedTopology


class FeatureType(str, Enum):
    """Categorized engineering design and manufacturing feature classes."""
    FASTENER_HOLE = "FASTENER_HOLE"
    GENERIC_HOLE = "GENERIC_HOLE"
    CYLINDRICAL_CAVITY = "CYLINDRICAL_CAVITY"
    FILLET = "FILLET"
    CHAMFER = "CHAMFER"
    RIB = "RIB"
    CONTACT_PLANE = "CONTACT_PLANE"


class HoleSubType(str, Enum):
    """Structural morphology of hole features."""
    THROUGH = "THROUGH"
    BLIND = "BLIND"
    COUNTERBORE = "COUNTERBORE"
    COUNTERSINK = "COUNTERSINK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FeatureEvidence:
    """Auditable evidence item supporting a feature classification."""
    evidence_type: str
    source_entity_ids: Tuple[str, ...]
    rule: str
    measured_value: Optional[float] = None
    expected_relation: Optional[str] = None
    result: str = "PASS"

    def __post_init__(self):
        if not self.evidence_type:
            raise ValueError("evidence_type is required")
        if not self.rule:
            raise ValueError("rule description is required")


def _validate_canonical_primitive(val: Any, path: str = "") -> None:
    """Recursively enforce that geometry metadata contains only JSON-serializable canonical primitives."""
    if isinstance(val, (int, float, bool, str, type(None))):
        return
    elif isinstance(val, (tuple, list)):
        for idx, item in enumerate(val):
            _validate_canonical_primitive(item, f"{path}[{idx}]")
    elif isinstance(val, dict):
        for k, v in val.items():
            if not isinstance(k, str):
                raise TypeError(f"geometry dictionary keys must be str, got {type(k)} at {path}")
            _validate_canonical_primitive(v, f"{path}.{k}" if path else k)
    else:
        raise TypeError(
            f"geometry value at '{path}' must be a canonical primitive scalar or structure, got {type(val)}"
        )


@dataclass(frozen=True)
class FeatureCandidate:
    """Canonical feature candidate representation across the engineering chain."""
    feature_id: str
    feature_type: FeatureType
    status: CapabilityStatus
    confidence: float
    face_ids: Tuple[str, ...] = ()
    edge_ids: Tuple[str, ...] = ()
    vertex_ids: Tuple[str, ...] = ()
    geometry: Dict[str, Any] = field(default_factory=dict)
    evidence: Tuple[FeatureEvidence, ...] = ()

    def __post_init__(self):
        if not self.feature_id:
            raise ValueError("feature_id cannot be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        # Deep recursive guard: only canonical scalars, strings, and strictly nested collections
        for k, v in self.geometry.items():
            if not isinstance(k, str):
                raise TypeError(f"geometry key must be str, got {type(k)}")
            _validate_canonical_primitive(v, k)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize feature candidate for provenance and reporting."""
        return {
            "feature_id": self.feature_id,
            "feature_type": self.feature_type.value,
            "status": self.status.value,
            "confidence": self.confidence,
            "face_ids": list(self.face_ids),
            "edge_ids": list(self.edge_ids),
            "geometry": self.geometry,
            "evidence": [
                {
                    "evidence_type": e.evidence_type,
                    "entities": list(e.source_entity_ids),
                    "rule": e.rule,
                    "measured": e.measured_value,
                    "expected": e.expected_relation,
                    "result": e.result,
                }
                for e in self.evidence
            ],
        }


# ---------------------------------------------------------------------------
# Fastener Hole Detection Engine (GA-1.3B-2)
# ---------------------------------------------------------------------------

def detect_fastener_holes(
    model: GeometryModel,
    topology: NormalizedTopology,
    min_hole_diameter: float = 0.5,
    max_hole_diameter_ratio: float = 0.4,
) -> Tuple[FeatureCandidate, ...]:
    """Identify fastener hole candidates from normalized B-Rep topology.

    Evaluates:
    1. Cylindrical face candidates and associated circular bounding loops.
    2. Topological penetration into surrounding planar/support surfaces.
    3. Multi-surface compositions (Counterbore, Countersink).
    4. False-positive filtration: large cylindrical cavities without mounting
       penetrations are classified as GENERIC_HOLE / CYLINDRICAL_CAVITY with
       ASSISTED status.

    Guarantees:
    - 100% deterministic, idempotent candidate IDs based on sorted entity keys.
    """
    candidates: List[FeatureCandidate] = []
    face_by_id: Dict[str, CadFace] = {f.id: f for f in model.faces}

    # Model characteristic scale for false-positive filtering
    char_len = 100.0
    if model.bounding_box:
        char_len = max(model.bounding_box.diagonal, 1.0)
    max_fastener_diameter = char_len * max_hole_diameter_ratio

    # Step 1: Discover candidate cylindrical or conical surfaces
    # Either explicitly declared surface_type or inferred through circular loops
    cylindrical_faces: List[CadFace] = []
    for face in sorted(model.faces, key=lambda f: f.id):
        st = face.surface_type.upper()
        if "CYLIND" in st or "CONIC" in st:
            cylindrical_faces.append(face)

    # Also detect cylindrical barrels implied by inner loops of planar faces
    # E.g., a planar face with inner loops pointing to circular edges
    faces_with_inner_holes: Set[str] = set()
    for fid, in_loops in topology.face_to_inner_loops.items():
        if in_loops:
            faces_with_inner_holes.add(fid)

    visited_faces: Set[str] = set()

    for cyl_face in cylindrical_faces:
        if cyl_face.id in visited_faces:
            continue

        cid = cyl_face.id
        visited_faces.add(cid)

        adjacent_faces = topology.get_adjacent_faces(cid)
        cyl_edges = topology.face_to_edges.get(cid, ())

        evidence_items: List[FeatureEvidence] = [
            FeatureEvidence(
                evidence_type="SURFACE_CURVATURE",
                source_entity_ids=(cid,),
                rule="Face exhibits cylindrical or conical analytical curvature",
                result="PASS",
            )
        ]

        # Estimate geometric properties from metadata or edge lengths
        diameter = None
        depth = None
        is_counterbore = False
        is_countersink = False
        associated_faces = [cid]

        # Check for counterbore / countersink combinations in adjacent faces
        for adj_id in adjacent_faces:
            adj_face = face_by_id.get(adj_id)
            if not adj_face:
                continue

            adj_st = adj_face.surface_type.upper()
            if "CYLIND" in adj_st and adj_id not in visited_faces:
                # Stepped cylinder -> Counterbore candidate
                is_counterbore = True
                associated_faces.append(adj_id)
                visited_faces.add(adj_id)
                evidence_items.append(
                    FeatureEvidence(
                        evidence_type="STEPPED_CYLINDER_TOPOLOGY",
                        source_entity_ids=(cid, adj_id),
                        rule="Adjacent coaxial cylindrical faces indicate counterbore geometry",
                        result="PASS",
                    )
                )
            elif "CONIC" in adj_st and adj_id not in visited_faces:
                # Conical transition -> Countersink candidate
                is_countersink = True
                associated_faces.append(adj_id)
                visited_faces.add(adj_id)
                evidence_items.append(
                    FeatureEvidence(
                        evidence_type="CONICAL_ENTRANCE_TOPOLOGY",
                        source_entity_ids=(cid, adj_id),
                        rule="Adjacent conical chamfer face indicates countersink geometry",
                        result="PASS",
                    )
                )

        # Estimate diameter from edges if available
        for eid in cyl_edges:
            edge = next((e for e in model.edges if e.id == eid), None)
            if edge and edge.length and edge.length > 0:
                # If circular edge with circumference = pi * D -> D = C / pi
                est_d = edge.length / math.pi
                if est_d >= min_hole_diameter:
                    diameter = est_d
                    break

        if diameter is None:
            # Fallback estimation based on face area or nominal default
            if cyl_face.area and cyl_face.area > 0:
                diameter = math.sqrt(cyl_face.area / math.pi)
            else:
                diameter = 10.0  # nominal default indicator

        # Classify through vs blind hole based on planar boundary adjacencies
        planar_adjacencies = [
            fid for fid in adjacent_faces
            if face_by_id.get(fid) and face_by_id[fid].is_planar
        ]

        # Verify whether opposing planar faces are parallel/opposing boundary walls
        # (orthogonal faces meeting at a corner indicate a fillet/chamfer transition, not a through-hole)
        valid_through_pair = False
        is_corner_transition = False
        if len(planar_adjacencies) >= 2:
            p1 = face_by_id[planar_adjacencies[0]]
            p2 = face_by_id[planar_adjacencies[1]]
            if p1.normal and p2.normal and len(p1.normal) == 3 and len(p2.normal) == 3:
                dot_norm = sum(a * b for a, b in zip(p1.normal, p2.normal))
                # Opposing faces (dot ~ -1.0) or parallel faces (dot ~ 1.0)
                if abs(dot_norm) > 0.6:
                    valid_through_pair = True
                elif abs(dot_norm) < 0.8:
                    # Non-parallel corner meeting faces indicate a fillet transition, not a hole
                    is_corner_transition = True
            else:
                valid_through_pair = True

        if is_corner_transition and not is_counterbore and not is_countersink:
            # Cylindrical fillet transition bridging corner walls is not a hole or cavity
            continue

        hole_subtype = HoleSubType.UNKNOWN
        if is_counterbore:
            hole_subtype = HoleSubType.COUNTERBORE
        elif is_countersink:
            hole_subtype = HoleSubType.COUNTERSINK
        elif len(planar_adjacencies) >= 2 and valid_through_pair:
            hole_subtype = HoleSubType.THROUGH
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="DUAL_PLANAR_PENETRATION",
                    source_entity_ids=tuple(planar_adjacencies[:2]),
                    rule="Cylindrical barrel bounds two opposing planar boundary faces (through-hole)",
                    result="PASS",
                )
            )
        elif len(planar_adjacencies) == 1:
            hole_subtype = HoleSubType.BLIND
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="SINGLE_PLANAR_ENTRY",
                    source_entity_ids=(planar_adjacencies[0],),
                    rule="Cylindrical barrel penetrates single planar entrance with interior closure (blind-hole)",
                    result="PASS",
                )
            )
        else:
            hole_subtype = HoleSubType.UNKNOWN

        # False-positive rejection: if diameter is too large relative to model scale
        # or lacks mounting penetration evidence, downgrade to GENERIC_HOLE / CAVITY
        is_false_positive_fastener = False
        if diameter > max_fastener_diameter:
            is_false_positive_fastener = True
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="SCALE_OVERSIZED",
                    source_entity_ids=(cid,),
                    rule=f"Cylindrical diameter {diameter:.1f} exceeds fastener threshold {max_fastener_diameter:.1f}",
                    measured_value=diameter,
                    expected_relation=f"<= {max_fastener_diameter:.1f}",
                    result="FAIL",
                )
            )

        # Non-manifold edge presence on hole barrel strictly blocks automated fastener assumption
        has_non_manifold_defect = any(
            eid in topology.non_manifold_edges for eid in cyl_edges
        )

        if has_non_manifold_defect:
            status = CapabilityStatus.BLOCKED
            ftype = FeatureType.GENERIC_HOLE
            conf = 0.3
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="TOPOLOGICAL_INTEGRITY",
                    source_entity_ids=(cid,),
                    rule="Hole boundary edge contains non-manifold bifurcation",
                    result="FAIL",
                )
            )
        elif is_false_positive_fastener or hole_subtype == HoleSubType.UNKNOWN:
            status = CapabilityStatus.ASSISTED
            ftype = FeatureType.CYLINDRICAL_CAVITY
            conf = 0.6
        else:
            status = CapabilityStatus.SUPPORTED
            ftype = FeatureType.FASTENER_HOLE
            conf = 0.95 if hole_subtype in (HoleSubType.THROUGH, HoleSubType.COUNTERBORE) else 0.85

        # Deterministic feature ID based on lexicographically sorted face IDs
        sorted_face_ids = tuple(sorted(associated_faces))
        feat_id = f"FEAT_{ftype.value}_{sorted_face_ids[0]}"

        # Consolidate all edge IDs
        all_edges = set()
        for fid in sorted_face_ids:
            all_edges.update(topology.face_to_edges.get(fid, ()))

        candidate = FeatureCandidate(
            feature_id=feat_id,
            feature_type=ftype,
            status=status,
            confidence=conf,
            face_ids=sorted_face_ids,
            edge_ids=tuple(sorted(all_edges)),
            geometry={
                "sub_type": hole_subtype.value,
                "diameter": round(diameter, 3),
                "is_fastener_hole": (ftype == FeatureType.FASTENER_HOLE),
            },
            evidence=tuple(evidence_items),
        )
        candidates.append(candidate)

    # Sort all candidates deterministically by feature_id
    return tuple(sorted(candidates, key=lambda c: c.feature_id))


# ---------------------------------------------------------------------------
# Constant-Radius Cylindrical Fillet Recognition (GA-1.3B-3)
# ---------------------------------------------------------------------------

def detect_fillets(
    model: GeometryModel,
    topology: NormalizedTopology,
    max_fillet_radius_ratio: float = 0.25,
) -> Tuple[FeatureCandidate, ...]:
    """Identify constant-radius cylindrical fillet candidates.

    Evaluates:
    1. Cylindrical transitional faces connecting two distinct primary adjacent faces.
    2. Shared boundary edges anchoring the transition.
    3. Radius extraction/estimation within local transition thresholds.
    4. Honest continuity gating: if analytical G1 tangency vectors cannot be
       rigorously proven by model data, downgrade status to ASSISTED with
       INSUFFICIENT_SURFACE_CONTINUITY_EVIDENCE (zero synthetic G1 proofs).
    5. Non-manifold boundary edges fail-closed to BLOCKED.
    """
    candidates: List[FeatureCandidate] = []
    face_by_id: Dict[str, CadFace] = {f.id: f for f in model.faces}
    edge_by_id: Dict[str, CadEdge] = {e.id: e for e in model.edges}

    char_len = 100.0
    if model.bounding_box:
        dims = [d for d in model.bounding_box.dimensions if d > 0]
        char_len = min(dims) if dims else max(model.bounding_box.diagonal, 1.0)
    max_fillet_radius = char_len * max_fillet_radius_ratio

    for face in sorted(model.faces, key=lambda f: f.id):
        st = face.surface_type.upper()
        if "CYLIND" not in st:
            continue

        fid = face.id
        adjacent_faces = [af for af in topology.get_adjacent_faces(fid) if af in face_by_id]
        if len(adjacent_faces) < 2:
            # An isolated cylinder or cylinder with only 1 adjacent face is not a transition fillet
            continue

        primary_adjacencies: List[CadFace] = [face_by_id[af] for af in adjacent_faces]

        # Verify that adjacent faces meet at a corner angle (not parallel opposing walls of a hole barrel)
        n1 = primary_adjacencies[0].normal
        n2 = primary_adjacencies[1].normal
        if n1 and n2 and len(n1) == 3 and len(n2) == 3:
            dot_norm = sum(a * b for a, b in zip(n1, n2))
            if abs(dot_norm) > 0.8:
                # Parallel or opposing faces belong to a hole barrel or slab, not a corner fillet
                continue

        face_edges = topology.face_to_edges.get(fid, ())
        shared_boundary_edges: List[str] = [
            e for e in face_edges
            if len(topology.edge_to_adjacent_faces.get(e, ())) >= 2
        ]

        if len(shared_boundary_edges) < 2:
            # A true fillet must have at least two shared boundary rails anchoring it to the body
            continue

        # Estimate radius ONLY when real circular / arc edge geometry evidence exists
        radius = None
        has_arc_evidence = False
        for eid in face_edges:
            edge = edge_by_id.get(eid)
            if edge and edge.length and edge.length > 0:
                ct = edge.curve_type.upper()
                if "CIRCLE" in ct or "ARC" in ct:
                    radius = edge.length / (2.0 * math.pi)
                    has_arc_evidence = True
                    break

        # Rejection of oversized fillets applies when radius is provable
        if radius is not None and radius > max_fillet_radius:
            continue

        evidence_items: List[FeatureEvidence] = [
            FeatureEvidence(
                evidence_type="SURFACE_CURVATURE",
                source_entity_ids=(fid,),
                rule="Face exhibits analytical cylindrical curvature suitable for fillet transition",
                result="PASS",
            ),
            FeatureEvidence(
                evidence_type="TRANSITIONAL_TOPOLOGY",
                source_entity_ids=(fid, primary_adjacencies[0].id, primary_adjacencies[1].id),
                rule="Cylindrical face bridges two distinct primary adjacent faces via shared boundary rails",
                result="PASS",
            ),
        ]

        if has_arc_evidence and radius is not None:
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="LOCAL_SCALE_METRIC",
                    source_entity_ids=(fid,),
                    rule=f"Estimated radius {radius:.2f} is within local fillet limit {max_fillet_radius:.2f}",
                    measured_value=radius,
                    expected_relation=f"<= {max_fillet_radius:.2f}",
                    result="PASS",
                )
            )
        else:
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="LOCAL_SCALE_METRIC",
                    source_entity_ids=(fid,),
                    rule="Definitive fillet radius requires circular/arc boundary edge geometry evidence",
                    measured_value=None,
                    expected_relation="circle/arc edge presence",
                    result="INSUFFICIENT_EVIDENCE",
                )
            )

        has_non_manifold = any(e in topology.non_manifold_edges for e in face_edges)
        if has_non_manifold:
            status = CapabilityStatus.BLOCKED
            conf = 0.3
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="TOPOLOGICAL_INTEGRITY",
                    source_entity_ids=(fid,),
                    rule="Fillet transition edge contains non-manifold bifurcation",
                    result="FAIL",
                )
            )
            reason = "NON_MANIFOLD_TOPOLOGY_DEFECT"
            is_constant_radius = False
        else:
            # Honest surface continuity gating:
            # Model data lacks high-order analytical tangent vector fields for G1 proof
            status = CapabilityStatus.ASSISTED
            conf = 0.75 if has_arc_evidence else 0.65
            reason = (
                "INSUFFICIENT_SURFACE_CONTINUITY_EVIDENCE"
                if has_arc_evidence
                else "INSUFFICIENT_RADIUS_EVIDENCE"
            )
            is_constant_radius = True if has_arc_evidence else False
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="SURFACE_CONTINUITY",
                    source_entity_ids=(fid, primary_adjacencies[0].id, primary_adjacencies[1].id),
                    rule="Rigorous analytical G1 tangency across shared boundary requires CAD kernel continuity evaluation",
                    result="INSUFFICIENT_EVIDENCE",
                )
            )

        feat_id = f"FEAT_FILLET_{fid}"
        candidate = FeatureCandidate(
            feature_id=feat_id,
            feature_type=FeatureType.FILLET,
            status=status,
            confidence=conf,
            face_ids=(fid,),
            edge_ids=tuple(sorted(shared_boundary_edges)),
            geometry={
                "radius": round(radius, 3) if radius is not None else None,
                "is_constant_radius": is_constant_radius,
                "continuity_verified": False,
                "reason": reason,
            },
            evidence=tuple(evidence_items),
        )
        candidates.append(candidate)

    return tuple(sorted(candidates, key=lambda c: c.feature_id))


# ---------------------------------------------------------------------------
# Planar Chamfer Recognition (GA-1.3B-4)
# ---------------------------------------------------------------------------

def detect_chamfers(
    model: GeometryModel,
    topology: NormalizedTopology,
    max_chamfer_width_ratio: float = 0.15,
) -> Tuple[FeatureCandidate, ...]:
    """Identify planar chamfer transition candidates.

    Evaluates:
    1. Planar transitional face bounded by shared edges.
    2. Two primary adjacent faces that are non-coplanar.
    3. Dimensional width metric: local transition width <= threshold.
       Oversized sloped faces are rejected as primary sloped surfaces.
    4. Non-manifold boundary edges fail-closed to BLOCKED.
    """
    candidates: List[FeatureCandidate] = []
    face_by_id: Dict[str, CadFace] = {f.id: f for f in model.faces}
    edge_by_id: Dict[str, CadEdge] = {e.id: e for e in model.edges}

    char_len = 100.0
    if model.bounding_box:
        dims = [d for d in model.bounding_box.dimensions if d > 0]
        char_len = min(dims) if dims else max(model.bounding_box.diagonal, 1.0)
    max_chamfer_width = char_len * max_chamfer_width_ratio

    for face in sorted(model.faces, key=lambda f: f.id):
        if not face.is_planar and face.surface_type.upper() != "PLANE":
            continue

        fid = face.id
        adjacent_faces = [af for af in topology.get_adjacent_faces(fid) if af in face_by_id]
        # A chamfer transition ribbon bridges exactly 2 primary adjacent faces
        if len(adjacent_faces) != 2:
            continue

        primary_adjacencies = [face_by_id[af] for af in adjacent_faces]

        # Check non-coplanarity between the two primary neighbors if normals are available
        n1 = primary_adjacencies[0].normal
        n2 = primary_adjacencies[1].normal
        is_non_coplanar = True
        if n1 and n2 and len(n1) == 3 and len(n2) == 3:
            dot_product = sum(a * b for a, b in zip(n1, n2))
            if abs(dot_product) > 0.999:
                is_non_coplanar = False

        if not is_non_coplanar:
            continue

        face_edges = topology.face_to_edges.get(fid, ())
        shared_boundary_edges = [
            e for e in face_edges
            if len(topology.edge_to_adjacent_faces.get(e, ())) >= 2
        ]
        if len(shared_boundary_edges) < 2:
            continue

        # Estimate chamfer width:
        # 1. Non-shared transverse profile edges give direct transverse width measurement.
        # 2. Lower-bound scale rejection: if all boundary edges exceed threshold, it cannot be a local chamfer.
        non_shared_lengths = [
            edge_by_id[e].length for e in face_edges
            if e not in shared_boundary_edges and e in edge_by_id and edge_by_id[e].length and edge_by_id[e].length > 0
        ]
        all_lengths = [
            edge_by_id[e].length for e in face_edges
            if e in edge_by_id and edge_by_id[e].length and edge_by_id[e].length > 0
        ]

        if non_shared_lengths:
            chamfer_width = min(non_shared_lengths)
        elif all_lengths and min(all_lengths) > max_chamfer_width:
            # Lower-bound scale rejection: every boundary edge strictly exceeds chamfer threshold
            chamfer_width = min(all_lengths)
        else:
            chamfer_width = None

        # Reject oversized sloped face (primary sloped surface, not a local chamfer)
        if chamfer_width is not None and chamfer_width > max_chamfer_width:
            continue

        evidence_items: List[FeatureEvidence] = [
            FeatureEvidence(
                evidence_type="TRANSITIONAL_PLANAR_TOPOLOGY",
                source_entity_ids=(fid, primary_adjacencies[0].id, primary_adjacencies[1].id),
                rule="Planar face transitions between two distinct primary adjacent faces",
                result="PASS",
            ),
            FeatureEvidence(
                evidence_type="NON_COPLANAR_NEIGHBORS",
                source_entity_ids=(primary_adjacencies[0].id, primary_adjacencies[1].id),
                rule="Primary adjacent neighbors exhibit distinct non-coplanar spatial orientations",
                result="PASS",
            ),
        ]

        if chamfer_width is not None:
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="CHAMFER_DIMENSIONAL_METRIC",
                    source_entity_ids=(fid,),
                    rule=f"Chamfer transverse width {chamfer_width:.2f} is within local threshold {max_chamfer_width:.2f}",
                    measured_value=chamfer_width,
                    expected_relation=f"<= {max_chamfer_width:.2f}",
                    result="PASS",
                )
            )
        else:
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="CHAMFER_DIMENSIONAL_METRIC",
                    source_entity_ids=(fid,),
                    rule="Definitive chamfer width requires transverse boundary edge geometry evidence",
                    measured_value=None,
                    expected_relation="transverse edge presence",
                    result="INSUFFICIENT_EVIDENCE",
                )
            )

        has_non_manifold = any(e in topology.non_manifold_edges for e in face_edges)
        if has_non_manifold:
            status = CapabilityStatus.BLOCKED
            conf = 0.3
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="TOPOLOGICAL_INTEGRITY",
                    source_entity_ids=(fid,),
                    rule="Chamfer transition edge contains non-manifold bifurcation",
                    result="FAIL",
                )
            )
            reason = "NON_MANIFOLD_TOPOLOGY_DEFECT"
        else:
            # Planar transition topology is proven, but rigorous 3D spatial width verification
            # requires full CAD B-Rep kernel distance calculation -> ASSISTED
            status = CapabilityStatus.ASSISTED
            conf = 0.80 if chamfer_width is not None else 0.70
            reason = (
                "INSUFFICIENT_EXACT_SPATIAL_METRIC_EVIDENCE"
                if chamfer_width is not None
                else "INSUFFICIENT_CHAMFER_WIDTH_EVIDENCE"
            )

        feat_id = f"FEAT_CHAMFER_{fid}"
        candidate = FeatureCandidate(
            feature_id=feat_id,
            feature_type=FeatureType.CHAMFER,
            status=status,
            confidence=conf,
            face_ids=(fid,),
            edge_ids=tuple(sorted(shared_boundary_edges)),
            geometry={
                "width": round(chamfer_width, 3) if chamfer_width is not None else None,
                "is_planar": True,
                "reason": reason,
            },
            evidence=tuple(evidence_items),
        )
        candidates.append(candidate)

    return tuple(sorted(candidates, key=lambda c: c.feature_id))


# ---------------------------------------------------------------------------
# Rib Candidate Recognition (GA-1.3B-5)
# ---------------------------------------------------------------------------

def detect_ribs(
    model: GeometryModel,
    topology: NormalizedTopology,
    max_thickness_ratio: float = 0.20,
    min_slenderness: float = 1.5,
) -> Tuple[FeatureCandidate, ...]:
    """Identify structural rib/stiffener candidates from normalized topology.

    Evaluates:
    1. Opposing planar side walls (F1, F2) with approximately anti-parallel normals (n1 . n2 <= -0.80).
    2. Common base attachment topology: both side walls connect directly or via single-level transition
       to a shared primary base support face (attachment_depth <= 2).
    3. Cap closure / ridge topology: side walls share a common ridge edge or top cap ribbon face.
    4. Protrusion vs. Groove/Cavity Rejection:
       Stiffener ribs protrude outward from the base surface into ambient space.
       Inner grooves, slots, and cavities whose walls open inward without outward protrusion
       are conservatively rejected (protrusion evidence missing; zero groove misreporting).
    5. Primary slab and free-standing sheet rejection:
       Isolated flat slabs without supporting base or free-standing sheets are rejected.
    6. Dimensional scale metrics:
       Thickness and length extracted only when direct transverse boundary edge geometry evidence exists.
       Without direct edge evidence, thickness, length, and slenderness_ratio strictly degrade to None.
    7. Honest capability gating:
       All valid candidates converge to CapabilityStatus.ASSISTED (never SUPPORTED).
       Non-manifold defects fail-closed to CapabilityStatus.BLOCKED.
    """
    candidates: List[FeatureCandidate] = []
    face_by_id: Dict[str, CadFace] = {f.id: f for f in model.faces}
    edge_by_id: Dict[str, CadEdge] = {e.id: e for e in model.edges}

    char_len = 100.0
    if model.bounding_box:
        dims = [d for d in model.bounding_box.dimensions if d > 0]
        char_len = min(dims) if dims else max(model.bounding_box.diagonal, 1.0)
    max_rib_thickness = char_len * max_thickness_ratio

    # Identify planar faces with valid normals
    candidate_planar_faces: List[CadFace] = []
    for f in sorted(model.faces, key=lambda x: x.id):
        if (f.is_planar or f.surface_type.upper() == "PLANE") and f.normal and len(f.normal) == 3:
            candidate_planar_faces.append(f)

    processed_pairs: Set[Tuple[str, str]] = set()

    for i, f1 in enumerate(candidate_planar_faces):
        for f2 in candidate_planar_faces[i + 1:]:
            pair_key = (f1.id, f2.id)
            if pair_key in processed_pairs:
                continue

            n1 = f1.normal
            n2 = f2.normal
            dot_product = sum(a * b for a, b in zip(n1, n2))
            # Must be approximately anti-parallel opposing walls
            if dot_product > -0.80:
                continue

            # Check adjacency sets
            adj1 = set(topology.get_adjacent_faces(f1.id))
            adj2 = set(topology.get_adjacent_faces(f2.id))

            # Exclude pairs that are completely disconnected
            f1_edges = set(topology.face_to_edges.get(f1.id, ()))
            f2_edges = set(topology.face_to_edges.get(f2.id, ()))
            shared_edges = f1_edges & f2_edges
            common_neighbors = (adj1 & adj2) - {f1.id, f2.id}

            if not shared_edges and not common_neighbors:
                # Disconnected floating walls
                continue

            # Find base attachment face:
            # A common neighbor roughly perpendicular to both opposing walls (|n_wall . n_base| < 0.40)
            base_face_candidate: Optional[CadFace] = None
            cap_face_candidate: Optional[CadFace] = None

            for neighbor_id in sorted(common_neighbors):
                neighbor = face_by_id.get(neighbor_id)
                if not neighbor or not neighbor.normal or len(neighbor.normal) != 3:
                    continue
                # Base is roughly perpendicular to rib walls
                dot_base1 = abs(sum(a * b for a, b in zip(n1, neighbor.normal)))
                dot_base2 = abs(sum(a * b for a, b in zip(n2, neighbor.normal)))
                if dot_base1 < 0.40 and dot_base2 < 0.40:
                    # Distinguish base vs cap: base typically has larger area or connects to external boundary
                    if base_face_candidate is None:
                        base_face_candidate = neighbor
                    elif neighbor.area and base_face_candidate.area and neighbor.area > base_face_candidate.area:
                        # Swap: larger face is the base substrate
                        cap_face_candidate = base_face_candidate
                        base_face_candidate = neighbor
                    else:
                        cap_face_candidate = neighbor

            # Free-standing sheet / no base attachment support
            if base_face_candidate is None:
                continue

            # Cap closure or ridge topology:
            # Rib must have a top boundary: either a shared ridge edge, or a cap face
            has_ridge = len(shared_edges) > 0
            has_cap = cap_face_candidate is not None

            # Protrusion Evidence vs Groove / Pocket Rejection:
            # For a true rib, walls protrude outward from the base.
            # If walls form an internal groove or cavity without top ridge/cap closure,
            # or if the walls are carved into the substrate, protrusion evidence is lacking.
            if not has_ridge and not has_cap:
                # Open groove/pocket or lack of top closure -> reject
                continue

            # Groove rejection: if cap face exists, cap normal should point outward along extrusion direction
            # (i.e. dot(n_cap, n_base) should not be opposing, and cap face should be a narrow ribbon).
            if has_cap and cap_face_candidate:
                n_cap = cap_face_candidate.normal
                if n_cap and len(n_cap) == 3:
                    dot_cap_base = sum(a * b for a, b in zip(n_cap, base_face_candidate.normal))
                    if dot_cap_base < -0.5:
                        # Opposing cap normal indicates internal groove/recess floor -> reject
                        continue

            # Slab rejection: if the model consists essentially of only f1 and f2 as the primary walls
            # without significant structural differentiation, reject as main slab
            if len(model.faces) <= 6 and not has_cap and not has_ridge:
                continue

            # Measure thickness and length:
            # Look for transverse edges bridging f1 and f2, or narrow boundary edges on cap
            transverse_lengths: List[float] = []
            longitudinal_lengths: List[float] = []

            # Shared edges between f1/f2 (ridge edge) represent length
            for eid in shared_edges:
                edge = edge_by_id.get(eid)
                if edge and edge.length and edge.length > 0:
                    longitudinal_lengths.append(edge.length)

            # Cap edges
            if cap_face_candidate:
                cap_edges = topology.face_to_edges.get(cap_face_candidate.id, ())
                for eid in cap_edges:
                    edge = edge_by_id.get(eid)
                    if edge and edge.length and edge.length > 0:
                        if edge.length <= max_rib_thickness:
                            transverse_lengths.append(edge.length)
                        else:
                            longitudinal_lengths.append(edge.length)

            # Edges on f1/f2
            for eid in f1_edges | f2_edges:
                edge = edge_by_id.get(eid)
                if edge and edge.length and edge.length > 0:
                    if edge.length > max_rib_thickness:
                        longitudinal_lengths.append(edge.length)

            thickness: Optional[float] = None
            if transverse_lengths:
                thickness = min(transverse_lengths)

            length: Optional[float] = None
            if longitudinal_lengths:
                length = max(longitudinal_lengths)

            # Scale filtering: oversized thickness cannot be a rib
            if thickness is not None and thickness > max_rib_thickness:
                continue

            slenderness_ratio: Optional[float] = None
            if thickness is not None and length is not None and thickness > 0:
                slenderness_ratio = round(length / thickness, 2)
                if slenderness_ratio < min_slenderness:
                    # Too stocky to be a slender reinforcing rib
                    continue

            # Evidence compilation
            evidence_items: List[FeatureEvidence] = [
                FeatureEvidence(
                    evidence_type="OPPOSING_WALL_TOPOLOGY",
                    source_entity_ids=(f1.id, f2.id),
                    rule="Candidate rib walls exhibit anti-parallel opposing planar orientations",
                    measured_value=dot_product,
                    expected_relation="<= -0.80",
                    result="PASS",
                ),
                FeatureEvidence(
                    evidence_type="BASE_ATTACHMENT_TOPOLOGY",
                    source_entity_ids=(f1.id, f2.id, base_face_candidate.id),
                    rule="Both rib side walls anchor to a shared structural substrate base plane",
                    result="PASS",
                ),
            ]

            if has_ridge or has_cap:
                evidence_items.append(
                    FeatureEvidence(
                        evidence_type="TOP_CLOSURE_PROTRUSION",
                        source_entity_ids=(f1.id, f2.id) + ((cap_face_candidate.id,) if cap_face_candidate else ()),
                        rule="Rib walls terminate in outward protruding ridge or cap closure",
                        result="PASS",
                    )
                )

            if thickness is not None:
                evidence_items.append(
                    FeatureEvidence(
                        evidence_type="LOCAL_SCALE_METRIC",
                        source_entity_ids=(f1.id, f2.id),
                        rule=f"Measured transverse thickness {thickness:.2f} satisfies thin-wall threshold <= {max_rib_thickness:.2f}",
                        measured_value=thickness,
                        expected_relation=f"<= {max_rib_thickness:.2f}",
                        result="PASS",
                    )
                )
            else:
                evidence_items.append(
                    FeatureEvidence(
                        evidence_type="LOCAL_SCALE_METRIC",
                        source_entity_ids=(f1.id, f2.id),
                        rule="Definitive rib thickness requires transverse boundary edge geometry evidence",
                        measured_value=None,
                        expected_relation="transverse edge presence",
                        result="INSUFFICIENT_EVIDENCE",
                    )
                )

            # Check non-manifold defects
            involved_edges = f1_edges | f2_edges | (set(topology.face_to_edges.get(base_face_candidate.id, ())))
            has_non_manifold = any(e in topology.non_manifold_edges for e in involved_edges)

            if has_non_manifold:
                status = CapabilityStatus.BLOCKED
                conf = 0.3
                reason = "NON_MANIFOLD_TOPOLOGY_DEFECT"
                evidence_items.append(
                    FeatureEvidence(
                        evidence_type="TOPOLOGICAL_INTEGRITY",
                        source_entity_ids=(f1.id, f2.id),
                        rule="Rib boundary edge contains non-manifold bifurcation",
                        result="FAIL",
                    )
                )
            else:
                # Honest capability boundary: geometry candidate recognized,
                # analytical solid extrusion verification requires full CAD kernel -> ASSISTED
                status = CapabilityStatus.ASSISTED
                conf = 0.80 if thickness is not None else 0.70
                reason = (
                    "ASSISTED_GEOMETRY_CANDIDATE"
                    if thickness is not None
                    else "INSUFFICIENT_THICKNESS_EVIDENCE"
                )

            all_associated_faces = [f1.id, f2.id]
            if cap_face_candidate:
                all_associated_faces.append(cap_face_candidate.id)
            sorted_face_ids = tuple(sorted(all_associated_faces))

            feat_id = f"FEAT_RIB_{sorted_face_ids[0]}"
            candidate = FeatureCandidate(
                feature_id=feat_id,
                feature_type=FeatureType.RIB,
                status=status,
                confidence=conf,
                face_ids=sorted_face_ids,
                edge_ids=tuple(sorted(f1_edges | f2_edges)),
                geometry={
                    "length": round(length, 3) if length is not None else None,
                    "thickness": round(thickness, 3) if thickness is not None else None,
                    "slenderness_ratio": slenderness_ratio,
                    "base_face_id": base_face_candidate.id,
                    "reason": reason,
                },
                evidence=tuple(evidence_items),
            )
            candidates.append(candidate)
            processed_pairs.add(pair_key)

    return tuple(sorted(candidates, key=lambda c: c.feature_id))


# ---------------------------------------------------------------------------
# Contact Plane Candidate Recognition (GA-1.3B-5)
# ---------------------------------------------------------------------------

def detect_contact_planes(
    model: GeometryModel,
    topology: NormalizedTopology,
    holes: Optional[Tuple[FeatureCandidate, ...]] = None,
    min_contact_area: float = 1.0,
) -> Tuple[FeatureCandidate, ...]:
    """Identify contact/mating plane candidates from normalized B-Rep topology.

    Evaluates:
    1. Planar geometry candidate (is_planar=True or surface_type='PLANE').
    2. Strict unit normal verification: |n| must satisfy | |n| - 1.0 | <= 0.05.
       Unverified/unnormalized normals strictly downgrade to normal=None (zero synthetic normalization).
    3. Transition feature exclusion: excludes fillet transitions, chamfer ribbons, and rib side walls.
    4. Engineering semantic anchoring:
       - Hole mounting spotface / boss plane (anchored by inner loop boundary connected to recognized hole).
       - Flange / bearing step plane (anchored by orthogonal supporting step walls or shoulder transitions).
       Ordinary unanchored exterior box faces are rejected to prevent over-generalization.
    5. Zero contact pair / interaction actions:
       Strictly outputs candidate geometry; creates zero Contact Pair, Tie, or Master/Slave interaction actions.
    6. Honest capability gating:
       All valid candidates converge to CapabilityStatus.ASSISTED (never SUPPORTED).
       Non-manifold defects fail-closed to CapabilityStatus.BLOCKED.
    """
    candidates: List[FeatureCandidate] = []
    face_by_id: Dict[str, CadFace] = {f.id: f for f in model.faces}

    if holes is None:
        holes = detect_fastener_holes(model, topology)

    # Map hole features to their constituent and boundary edges
    hole_by_edge: Dict[str, List[str]] = {}
    for h in holes:
        for eid in h.edge_ids:
            hole_by_edge.setdefault(eid, []).append(h.feature_id)

    # Collect cylindrical hole barrel faces to exclude them
    hole_barrel_faces: Set[str] = set()
    for h in holes:
        hole_barrel_faces.update(h.face_ids)

    for face in sorted(model.faces, key=lambda f: f.id):
        fid = face.id
        if fid in hole_barrel_faces:
            continue

        if not face.is_planar and face.surface_type.upper() != "PLANE":
            continue

        # Reject negligible micro-sliver faces
        if face.area is not None and face.area < min_contact_area:
            continue

        face_edges = topology.face_to_edges.get(fid, ())

        # Strict Normal Vector Verification
        normal_val: Optional[List[float]] = None
        normal_valid = False
        evidence_items: List[FeatureEvidence] = []

        if face.normal and len(face.normal) == 3:
            norm_len = math.sqrt(sum(c * c for c in face.normal))
            if abs(norm_len - 1.0) <= 0.05:
                normal_val = [round(c, 4) for c in face.normal]
                normal_valid = True
                evidence_items.append(
                    FeatureEvidence(
                        evidence_type="SURFACE_NORMAL_UNIT_METRIC",
                        source_entity_ids=(fid,),
                        rule="Planar face normal vector is strictly unit normalized within tolerance",
                        measured_value=round(norm_len, 4),
                        expected_relation="approx 1.0",
                        result="PASS",
                    )
                )
            else:
                evidence_items.append(
                    FeatureEvidence(
                        evidence_type="SURFACE_NORMAL_UNIT_METRIC",
                        source_entity_ids=(fid,),
                        rule="Face normal vector deviates from unit length; synthetic normalization forbidden",
                        measured_value=round(norm_len, 4),
                        expected_relation="approx 1.0",
                        result="INSUFFICIENT_EVIDENCE",
                    )
                )
        else:
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="SURFACE_NORMAL_UNIT_METRIC",
                    source_entity_ids=(fid,),
                    rule="Planar face lacks 3D normal vector definition",
                    result="INSUFFICIENT_EVIDENCE",
                )
            )

        # Semantic Anchoring & False-Positive Prevention:
        # Check Anchor 1: Fastener hole connection (inner loops or boundary edges shared with recognized holes)
        associated_hole_ids: List[str] = []
        for eid in face_edges:
            if eid in hole_by_edge:
                associated_hole_ids.extend(hole_by_edge[eid])

        has_inner_hole = len(face.inner_loops) > 0 or len(associated_hole_ids) > 0

        # Check Anchor 2: Flange / Step Bearing Surface
        # Must have adjacent perpendicular or stepped shoulder walls
        has_stepped_shoulder = False
        if normal_val is not None:
            adjacent_face_ids = topology.get_adjacent_faces(fid)
            for afid in adjacent_face_ids:
                aface = face_by_id.get(afid)
                if aface and aface.normal and len(aface.normal) == 3:
                    dot_adj = abs(sum(a * b for a, b in zip(normal_val, aface.normal)))
                    if dot_adj < 0.25:
                        # Perpendicular step wall detected (e.g. boss cylinder or flange collar)
                        # The primary flange mating surface has substantial area; smaller perpendicular
                        # faces act as the positioning shoulder wall rather than the contact plane.
                        if aface.area and face.area and face.area < aface.area * 0.5:
                            continue
                        has_stepped_shoulder = True
                        break

        # A planar face must have an explicit engineering anchor to be a contact plane candidate.
        # Simple isolated box sides without holes or steps are rejected as plain bulk walls.
        if not has_inner_hole and not has_stepped_shoulder:
            continue

        if has_inner_hole:
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="FASTENER_MOUNTING_ANCHOR",
                    source_entity_ids=(fid,),
                    rule="Planar face serves as fastener bearing spotface anchored by mounting hole boundary",
                    result="PASS",
                )
            )
        elif has_stepped_shoulder:
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="FLANGE_BEARING_ANCHOR",
                    source_entity_ids=(fid,),
                    rule="Planar face bounded by orthogonal step shoulder suitable for flange or joint contact",
                    result="PASS",
                )
            )

        # Check topological defects
        has_non_manifold = any(e in topology.non_manifold_edges for e in face_edges)
        if has_non_manifold:
            status = CapabilityStatus.BLOCKED
            conf = 0.3
            reason = "NON_MANIFOLD_TOPOLOGY_DEFECT"
            evidence_items.append(
                FeatureEvidence(
                    evidence_type="TOPOLOGICAL_INTEGRITY",
                    source_entity_ids=(fid,),
                    rule="Contact plane boundary edge contains non-manifold bifurcation",
                    result="FAIL",
                )
            )
        else:
            status = CapabilityStatus.ASSISTED
            conf = 0.85 if has_inner_hole else 0.75
            reason = (
                "ASSISTED_CONTACT_PLANE_CANDIDATE"
                if normal_valid
                else "UNVERIFIED_NORMAL_VECTOR"
            )

        feat_id = f"FEAT_CONTACT_PLANE_{fid}"
        candidate = FeatureCandidate(
            feature_id=feat_id,
            feature_type=FeatureType.CONTACT_PLANE,
            status=status,
            confidence=conf,
            face_ids=(fid,),
            edge_ids=tuple(sorted(face_edges)),
            geometry={
                "normal": normal_val,
                "area": round(face.area, 3) if face.area is not None else None,
                "has_inner_hole": has_inner_hole,
                "associated_hole_ids": sorted(list(set(associated_hole_ids))),
                "reason": reason,
            },
            evidence=tuple(evidence_items),
        )
        candidates.append(candidate)

    return tuple(sorted(candidates, key=lambda c: c.feature_id))


# ---------------------------------------------------------------------------
# Consolidated Feature Recognition Pipeline
# ---------------------------------------------------------------------------

def detect_features(
    model: GeometryModel,
    topology: NormalizedTopology,
) -> Tuple[FeatureCandidate, ...]:
    """Extract all recognized engineering features (Holes, Fillets, Chamfers, Ribs, Contact Planes).

    Consolidates:
    - Fastener Holes (through, blind, counterbore, countersink)
    - Constant-radius cylindrical fillets (with honest continuity gating)
    - Planar chamfers (with non-coplanar neighbor verification and scale filtering)
    - Structural ribs / stiffeners (with base anchoring and protrusion gating)
    - Contact / mating plane candidates (with normal verification and semantic anchoring)

    Disambiguation rules:
    - Specialized fillet transitions subsume generic cylindrical cavities on the same face.
    - Transition faces (fillets, chamfers, rib walls) are strictly excluded from contact planes.

    Guarantees:
    - 100% deterministic ordering by feature_id.
    - Zero duplicate CAD kernel dependencies.
    """
    holes = detect_fastener_holes(model, topology)
    fillets = detect_fillets(model, topology)
    chamfers = detect_chamfers(model, topology)
    ribs = detect_ribs(model, topology)
    contact_planes = detect_contact_planes(model, topology, holes=holes)

    # Disambiguation:
    # 1. Specialized fillet transitions subsume generic cylindrical cavities on same face
    fillet_face_ids = {fid for f in fillets for fid in f.face_ids}
    filtered_holes = [
        h for h in holes
        if not (h.feature_type == FeatureType.CYLINDRICAL_CAVITY and any(fid in fillet_face_ids for fid in h.face_ids))
    ]

    # 2. Exclude faces claimed by transitions from contact planes
    transition_face_ids = (
        fillet_face_ids
        | {fid for c in chamfers for fid in c.face_ids}
        | {fid for r in ribs for fid in r.face_ids}
    )
    filtered_contact_planes = [
        cp for cp in contact_planes
        if not any(fid in transition_face_ids for fid in cp.face_ids)
    ]

    all_features = (
        list(filtered_holes)
        + list(fillets)
        + list(chamfers)
        + list(ribs)
        + list(filtered_contact_planes)
    )
    return tuple(sorted(all_features, key=lambda c: c.feature_id))
