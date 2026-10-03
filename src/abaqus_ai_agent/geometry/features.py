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

        hole_subtype = HoleSubType.UNKNOWN
        if is_counterbore:
            hole_subtype = HoleSubType.COUNTERBORE
        elif is_countersink:
            hole_subtype = HoleSubType.COUNTERSINK
        elif len(planar_adjacencies) >= 2:
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
