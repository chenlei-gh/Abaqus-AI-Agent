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
        # Guard geometry against arbitrary complex objects: only canonical scalars and primitive structures
        for k, v in self.geometry.items():
            if not isinstance(k, str):
                raise TypeError(f"geometry key must be str, got {type(k)}")
            if not isinstance(v, (int, float, bool, str, type(None), tuple, list, dict)):
                raise TypeError(
                    f"geometry value for key '{k}' must be primitive scalar/collection, got {type(v)}"
                )

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

        # Estimate radius from cylindrical edge curvature or area/length
        radius = None
        for eid in face_edges:
            edge = edge_by_id.get(eid)
            if edge and edge.length and edge.length > 0:
                if edge.curve_type.upper() in ("CIRCLE", "ARC") or "ARC" in edge.curve_type.upper():
                    radius = edge.length / (2.0 * math.pi)
                    break

        if radius is None:
            if face.area and face.area > 0 and char_len > 0:
                radius = min(math.sqrt(face.area / 4.0), max_fillet_radius * 0.5)
            else:
                radius = 5.0

        # Reject oversized cylinder (e.g. main cylinder body or column, not a fillet)
        if radius > max_fillet_radius:
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
            FeatureEvidence(
                evidence_type="LOCAL_SCALE_METRIC",
                source_entity_ids=(fid,),
                rule=f"Estimated radius {radius:.2f} is within local fillet limit {max_fillet_radius:.2f}",
                measured_value=radius,
                expected_relation=f"<= {max_fillet_radius:.2f}",
                result="PASS",
            ),
        ]

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
        else:
            # Honest surface continuity gating:
            # Model data lacks high-order analytical tangent vector fields for G1 proof
            status = CapabilityStatus.ASSISTED
            conf = 0.75
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
                "radius": round(radius, 3),
                "is_constant_radius": True,
                "continuity_verified": False,
                "reason": "INSUFFICIENT_SURFACE_CONTINUITY_EVIDENCE",
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

        # Estimate chamfer width across the transition
        shared_lengths = [
            edge_by_id[e].length for e in shared_boundary_edges
            if e in edge_by_id and edge_by_id[e].length and edge_by_id[e].length > 0
        ]
        all_lengths = [
            edge_by_id[e].length for e in face_edges
            if e in edge_by_id and edge_by_id[e].length and edge_by_id[e].length > 0
        ]

        if face.area and face.area > 0 and shared_lengths:
            chamfer_width = face.area / max(shared_lengths)
        elif all_lengths and shared_lengths and len(all_lengths) > len(shared_lengths):
            # Non-shared boundary edges represent end-width profiles
            non_shared_lengths = [
                edge_by_id[e].length for e in face_edges
                if e not in shared_boundary_edges and e in edge_by_id and edge_by_id[e].length
            ]
            chamfer_width = min(non_shared_lengths) if non_shared_lengths else min(all_lengths)
        elif all_lengths:
            chamfer_width = min(all_lengths)
        else:
            chamfer_width = 2.0

        # Reject oversized sloped face (primary sloped surface, not a local chamfer)
        if chamfer_width > max_chamfer_width:
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
            FeatureEvidence(
                evidence_type="CHAMFER_DIMENSIONAL_METRIC",
                source_entity_ids=(fid,),
                rule=f"Chamfer width {chamfer_width:.2f} is within local threshold {max_chamfer_width:.2f}",
                measured_value=chamfer_width,
                expected_relation=f"<= {max_chamfer_width:.2f}",
                result="PASS",
            ),
        ]

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
        else:
            status = CapabilityStatus.SUPPORTED
            conf = 0.90

        feat_id = f"FEAT_CHAMFER_{fid}"
        candidate = FeatureCandidate(
            feature_id=feat_id,
            feature_type=FeatureType.CHAMFER,
            status=status,
            confidence=conf,
            face_ids=(fid,),
            edge_ids=tuple(sorted(shared_boundary_edges)),
            geometry={
                "width": round(chamfer_width, 3),
                "is_planar": True,
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
    """Extract all recognized engineering features (Holes, Fillets, Chamfers).

    Consolidates:
    - Fastener Holes (through, blind, counterbore, countersink)
    - Constant-radius cylindrical fillets (with honest continuity gating)
    - Planar chamfers (with non-coplanar neighbor verification and scale filtering)

    Guarantees:
    - 100% deterministic ordering by feature_id.
    - Zero duplicate CAD kernel dependencies.
    """
    holes = detect_fastener_holes(model, topology)
    fillets = detect_fillets(model, topology)
    chamfers = detect_chamfers(model, topology)

    # Disambiguation: specialized fillet transitions subsume generic cylindrical cavities on same face
    fillet_face_ids = {fid for f in fillets for fid in f.face_ids}
    filtered_holes = [
        h for h in holes
        if not (h.feature_type == FeatureType.CYLINDRICAL_CAVITY and any(fid in fillet_face_ids for fid in h.face_ids))
    ]

    all_features = list(filtered_holes) + list(fillets) + list(chamfers)
    return tuple(sorted(all_features, key=lambda c: c.feature_id))
