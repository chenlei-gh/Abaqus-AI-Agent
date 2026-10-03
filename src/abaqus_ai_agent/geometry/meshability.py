"""Pre-meshing Meshability Assessment & Direct Mesh Gate Reuse (Track GA-1.4).

Provides an auditable pre-meshing geometric meshability assessment layer:
1. Geometry Meshability: Audits topological invariants, degenerate geometry, and scale anomalies
   via GeometryHealthReport and NormalizedTopology. Blocks defective models fail-closed.
2. Local Geometric Risk: Detects sub-scale edges, micro-slivers, and element swallowing conflicts.
3. Feature Scale Hints: Derives heuristic mesh refinement candidates strictly from evidenced
   feature parameters (holes, fillets, chamfers, ribs, contact planes) without fabricating
   unprovable mechanics rules or partition mandates.
4. Downstream Strategy Handoff: Seamlessly bridges to existing GeometryMeshPlan contracts while
   preserving an explicit boundary before post-meshing element quality gates (mesh_gate.py).

CRITICAL ARCHITECTURAL BOUNDARY:
GA-1.4 evaluates whether the CAD geometry can reliably enter meshing workflows and provides
scale guidance. It does not perform geometric repair, does not fabricate deterministic FEA
heuristics (e.g. Kt assumptions), does not mandate partitions, does not synthesize an unverified
Hex/Sweep strategy, and does not replace the post-meshing element quality gate in mesh_gate.py.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..capability_boundary import CapabilityStatus
from ..contracts.mesh_strategy import GeometryMeshPlan, MeshRefinementRequest
from .features import (
    FeatureCandidate,
    FeatureType,
    detect_features,
)
from .health import (
    GeometryHealthReport,
    HealthSeverity,
    inspect_geometry_health,
)
from .model import GeometryModel
from .topology import NormalizedTopology, normalize_topology


class MeshabilitySeverity(str, Enum):
    """Severity classification for pre-meshing geometric risks."""
    INFO = "INFO"
    WARNING = "WARNING"
    RISK = "RISK"
    CRITICAL = "CRITICAL"


class MeshabilityRiskKind(str, Enum):
    """Categorized geometric risk kinds that impair downstream meshing."""
    DEFECTIVE_TOPOLOGY = "DEFECTIVE_TOPOLOGY"
    TINY_FEATURE_DEFORMATION = "TINY_FEATURE_DEFORMATION"
    SLIVER_FACE_DISTORTION = "SLIVER_FACE_DISTORTION"
    HIGH_SLENDERNESS_THIN_WALL = "HIGH_SLENDERNESS_THIN_WALL"
    SCALE_CONFLICT_ELEMENT_SWALLOWING = "SCALE_CONFLICT_ELEMENT_SWALLOWING"
    UNVERIFIED_GEOMETRY_EVIDENCE = "UNVERIFIED_GEOMETRY_EVIDENCE"


class RecommendedMeshStrategy(str, Enum):
    """High-level meshability readiness status.

    GA-1.4 explicitly leaves topological element-family selection (TET vs HEX) to downstream
    mesh planning, marking non-blocked models as UNDECIDED rather than fabricating sweepable topology.
    """
    UNDECIDED = "UNDECIDED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class MeshabilityRisk:
    """Specific pre-meshing risk identified in geometry or topology."""
    risk_id: str
    kind: MeshabilityRiskKind
    severity: MeshabilitySeverity
    description: str
    entity_ids: Tuple[str, ...] = ()
    feature_ids: Tuple[str, ...] = ()
    metric_value: Optional[float] = None
    threshold: Optional[float] = None

    def __post_init__(self):
        if not self.risk_id:
            raise ValueError("risk_id is required")
        if not self.description:
            raise ValueError("description is required")


@dataclass(frozen=True)
class MeshRefinementCandidate:
    """Feature-driven local mesh refinement candidate derived from evidenced geometry."""
    target_id: str
    entity_type: str
    feature_type: Optional[FeatureType]
    characteristic_name: Optional[str]
    characteristic_value: Optional[float]
    suggested_size: Optional[float]
    priority: str
    confidence: float
    reason: str
    evidence: Tuple[str, ...] = ()

    def __post_init__(self):
        if not self.target_id:
            raise ValueError("target_id is required")
        if self.entity_type not in ("Face", "Edge", "Region", "Vertex"):
            raise ValueError(f"unsupported entity_type: {self.entity_type}")
        if self.priority not in ("low", "normal", "high", "critical"):
            raise ValueError(f"unsupported priority: {self.priority}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


@dataclass(frozen=True)
class MeshabilityResult:
    """Consolidated pre-meshing meshability evaluation."""
    model_id: str
    status: CapabilityStatus
    is_meshable: bool
    recommended_strategy: RecommendedMeshStrategy
    target_mesh_size: Optional[float]
    characteristic_length: float
    risks: Tuple[MeshabilityRisk, ...] = ()
    refinement_candidates: Tuple[MeshRefinementCandidate, ...] = ()
    scale_metrics: Dict[str, float] = field(default_factory=dict)
    evidence: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()

    @property
    def has_critical_risks(self) -> bool:
        return any(r.severity == MeshabilitySeverity.CRITICAL for r in self.risks)

    @property
    def has_scale_conflicts(self) -> bool:
        return any(r.kind == MeshabilityRiskKind.SCALE_CONFLICT_ELEMENT_SWALLOWING for r in self.risks)

    def to_geometry_mesh_plan(self, global_size: Optional[float] = None) -> GeometryMeshPlan:
        """Convert pre-meshing assessment to existing GeometryMeshPlan contract.

        - If model is BLOCKED or not meshable, raises ValueError to enforce fail-closed gate.
        - Translates candidates with valid suggested_size into MeshRefinementRequest items.
        - Translates unevidenced or review candidates into feature_reviews.
        - Preserves risks as warnings and audits provenance in evidence.
        """
        if not self.is_meshable or self.status == CapabilityStatus.BLOCKED:
            raise ValueError(
                f"Cannot create GeometryMeshPlan for unmeshable/blocked model '{self.model_id}'. "
                f"Status: {self.status.value}"
            )

        resolved_global_size = global_size or self.target_mesh_size
        if resolved_global_size is None or resolved_global_size <= 0:
            # Fallback to coarse heuristic: 5% of characteristic length, bounded above 0
            resolved_global_size = max(self.characteristic_length * 0.05, 1.0)

        refinements: List[MeshRefinementRequest] = []
        reviews: List[MeshRefinementRequest] = []
        warnings: List[str] = [r.description for r in self.risks if r.severity in (MeshabilitySeverity.WARNING, MeshabilitySeverity.RISK)]
        plan_evidence: List[str] = list(self.evidence) + [
            f"meshability_status:{self.status.value}",
            f"recommended_strategy:{self.recommended_strategy.value}",
        ]

        for cand in self.refinement_candidates:
            if cand.suggested_size is not None and cand.suggested_size > 0:
                # Direct local seedable candidate (requires_partition is strictly False in GA-1.4)
                refinements.append(
                    MeshRefinementRequest(
                        target=cand.target_id,
                        entity_type=cand.entity_type,
                        target_size=float(cand.suggested_size),
                        reason=cand.reason,
                        priority=cand.priority,
                        source="meshability_assessment",
                        method="local_seed",
                        transition="smooth",
                        requires_partition=False,
                        evidence=cand.evidence,
                    )
                )
            else:
                # Review candidate: candidate exists but characteristic scale was unprovable
                reviews.append(
                    MeshRefinementRequest(
                        target=cand.target_id,
                        entity_type=cand.entity_type,
                        target_size=float(resolved_global_size),
                        reason=f"review_unproven_scale:{cand.reason}",
                        priority=cand.priority,
                        source="meshability_feature_review",
                        method="virtual_topology_review",
                        transition="controlled",
                        requires_partition=False,
                        evidence=cand.evidence,
                    )
                )

        return GeometryMeshPlan(
            global_size=float(resolved_global_size),
            refinements=tuple(refinements),
            feature_reviews=tuple(reviews),
            warnings=tuple(warnings),
            evidence=tuple(plan_evidence),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize evaluation result for telemetry, reporting, and audit."""
        return {
            "model_id": self.model_id,
            "status": self.status.value,
            "is_meshable": self.is_meshable,
            "recommended_strategy": self.recommended_strategy.value,
            "target_mesh_size": self.target_mesh_size,
            "characteristic_length": self.characteristic_length,
            "scale_metrics": self.scale_metrics,
            "risks": [
                {
                    "risk_id": r.risk_id,
                    "kind": r.kind.value,
                    "severity": r.severity.value,
                    "description": r.description,
                    "entity_ids": list(r.entity_ids),
                    "feature_ids": list(r.feature_ids),
                    "metric_value": r.metric_value,
                    "threshold": r.threshold,
                }
                for r in self.risks
            ],
            "refinement_candidates": [
                {
                    "target_id": c.target_id,
                    "entity_type": c.entity_type,
                    "feature_type": c.feature_type.value if c.feature_type else None,
                    "characteristic_name": c.characteristic_name,
                    "characteristic_value": c.characteristic_value,
                    "suggested_size": c.suggested_size,
                    "priority": c.priority,
                    "confidence": c.confidence,
                    "reason": c.reason,
                    "evidence": list(c.evidence),
                }
                for c in self.refinement_candidates
            ],
            "evidence": list(self.evidence),
            "limitations": list(self.limitations),
        }


def assess_meshability(
    model: GeometryModel,
    topology: Optional[NormalizedTopology] = None,
    features: Optional[Tuple[FeatureCandidate, ...]] = None,
    health_report: Optional[GeometryHealthReport] = None,
    target_mesh_size: Optional[float] = None,
) -> MeshabilityResult:
    """Execute pre-meshing meshability assessment across geometry, topology, and features.

    Parameters:
        model: Canonical GeometryModel from GA-1.1 ingestion.
        topology: Optional NormalizedTopology from GA-1.3A. If None, computed on-the-fly.
        features: Optional tuple of FeatureCandidate from GA-1.3B. If None, detected on-the-fly.
        health_report: Optional GeometryHealthReport from GA-1.2. If None, inspected on-the-fly.
        target_mesh_size: Optional proposed global element size for conflict screening.

    Returns:
        Structured MeshabilityResult with explicit status, risks, refinement hints, and limitations.
    """
    # 0. Resolve dependencies
    resolved_topology = topology or normalize_topology(model)
    resolved_health = health_report or inspect_geometry_health(model)
    resolved_features = features if features is not None else detect_features(model, resolved_topology)

    char_len = resolved_health.characteristic_length
    if char_len <= 0.0 and model.bounding_box:
        char_len = max(model.bounding_box.diagonal, 1.0)
    elif char_len <= 0.0:
        char_len = 1.0

    risks: List[MeshabilityRisk] = []
    candidates: List[MeshRefinementCandidate] = []
    evidence: List[str] = [
        f"model:{model.model_id}",
        f"char_length:{char_len:.4g}",
        f"health_status:{resolved_health.status.value}",
    ]
    risk_counter = 0

    # Explicit limitations statement
    limitations: Tuple[str, ...] = (
        "HEX_SWEEP suitability is not assessed without 3D B-Rep volume parameterization",
        "Exact boundary curvature quality is not assessed without complete CAD analytical kernel",
        "Feature-derived refinement sizes are heuristic recommendations, not deterministic engineering requirements",
        "Partition feasibility is not assessed in GA-1.4",
        "Pre-meshing assessment does not replace post-meshing element quality gate (mesh_gate.py)",
    )

    # -------------------------------------------------------------------------
    # Layer 1: Global Geometry Health Gate (Fail-Closed)
    # -------------------------------------------------------------------------
    if not resolved_health.is_acceptable_for_analysis or resolved_health.status == CapabilityStatus.BLOCKED:
        for issue in resolved_health.issues:
            if issue.severity in (HealthSeverity.CRITICAL, HealthSeverity.ERROR):
                risk_counter += 1
                risks.append(
                    MeshabilityRisk(
                        risk_id=f"RISK_HEALTH_{risk_counter}",
                        kind=MeshabilityRiskKind.DEFECTIVE_TOPOLOGY,
                        severity=MeshabilitySeverity.CRITICAL,
                        description=f"Health defect blocks meshing: {issue.description}",
                        entity_ids=issue.entity_ids,
                        metric_value=issue.metric_value,
                        threshold=issue.threshold,
                    )
                )

        evidence.append("global_health_gate:BLOCKED")
        return MeshabilityResult(
            model_id=model.model_id,
            status=CapabilityStatus.BLOCKED,
            is_meshable=False,
            recommended_strategy=RecommendedMeshStrategy.BLOCKED,
            target_mesh_size=target_mesh_size,
            characteristic_length=char_len,
            risks=tuple(risks),
            refinement_candidates=(),
            scale_metrics={"characteristic_length": char_len},
            evidence=tuple(evidence),
            limitations=limitations,
        )

    # -------------------------------------------------------------------------
    # Layer 2: Local Scale Metrics & Geometric Risks
    # -------------------------------------------------------------------------
    min_edge_len: Optional[float] = None
    max_edge_len: Optional[float] = None
    valid_edge_lengths = [e.length for e in model.edges if e.length is not None and e.length > 0]
    if valid_edge_lengths:
        min_edge_len = min(valid_edge_lengths)
        max_edge_len = max(valid_edge_lengths)

    min_face_area: Optional[float] = None
    max_face_area: Optional[float] = None
    valid_face_areas = [f.area for f in model.faces if f.area is not None and f.area > 0]
    if valid_face_areas:
        min_face_area = min(valid_face_areas)
        max_face_area = max(valid_face_areas)

    scale_metrics: Dict[str, float] = {
        "characteristic_length": char_len,
    }
    if min_edge_len is not None:
        scale_metrics["min_edge_length"] = min_edge_len
        scale_metrics["max_edge_length"] = max_edge_len or min_edge_len
    if min_face_area is not None:
        scale_metrics["min_face_area"] = min_face_area
        scale_metrics["max_face_area"] = max_face_area or min_face_area

    # Sub-scale tiny edges (< 0.005 char_len)
    tiny_edge_thresh = char_len * 0.005
    for edge in model.edges:
        if edge.length is not None and 0.0 < edge.length < tiny_edge_thresh:
            risk_counter += 1
            risks.append(
                MeshabilityRisk(
                    risk_id=f"RISK_TINY_EDGE_{risk_counter}",
                    kind=MeshabilityRiskKind.TINY_FEATURE_DEFORMATION,
                    severity=MeshabilitySeverity.WARNING,
                    description=(
                        f"Sub-scale edge '{edge.id}' (length={edge.length:.3e} < {tiny_edge_thresh:.3e}) "
                        "may produce severe aspect-ratio elongation or corner pinching in standard meshing"
                    ),
                    entity_ids=(edge.id,),
                    metric_value=edge.length,
                    threshold=tiny_edge_thresh,
                )
            )

    # Micro-sliver faces (< 1e-4 of reference area)
    ref_area = char_len * char_len
    sliver_area_thresh = ref_area * 1e-4
    for face in model.faces:
        if face.area is not None and 0.0 < face.area < sliver_area_thresh:
            risk_counter += 1
            risks.append(
                MeshabilityRisk(
                    risk_id=f"RISK_SLIVER_FACE_{risk_counter}",
                    kind=MeshabilityRiskKind.SLIVER_FACE_DISTORTION,
                    severity=MeshabilitySeverity.WARNING,
                    description=(
                        f"Micro-sliver face '{face.id}' (area={face.area:.3e} < {sliver_area_thresh:.3e}) "
                        "may force degenerate or inverted elements during surface discretization"
                    ),
                    entity_ids=(face.id,),
                    metric_value=face.area,
                    threshold=sliver_area_thresh,
                )
            )

    # Element swallowing conflict check (if target_mesh_size provided)
    if target_mesh_size is not None and target_mesh_size > 0:
        scale_metrics["target_mesh_size"] = target_mesh_size
        if min_edge_len is not None and target_mesh_size > 2.0 * min_edge_len:
            risk_counter += 1
            risks.append(
                MeshabilityRisk(
                    risk_id=f"RISK_SCALE_CONFLICT_{risk_counter}",
                    kind=MeshabilityRiskKind.SCALE_CONFLICT_ELEMENT_SWALLOWING,
                    severity=MeshabilitySeverity.WARNING,
                    description=(
                        f"Proposed target mesh size ({target_mesh_size:.3g}) exceeds 2x smallest geometric edge "
                        f"({min_edge_len:.3g}). Features may be geometrically swallowed or distorted without local refinement"
                    ),
                    metric_value=target_mesh_size,
                    threshold=2.0 * min_edge_len,
                )
            )
            evidence.append("scale_conflict_detected")

    # -------------------------------------------------------------------------
    # Layer 3: Feature Scale Hints (Heuristic, Evidenced-Only)
    # -------------------------------------------------------------------------
    for feat in resolved_features:
        fid = feat.feature_id
        ftype = feat.feature_type
        geom = feat.geometry

        if ftype in (FeatureType.FASTENER_HOLE, FeatureType.GENERIC_HOLE):
            dia = geom.get("diameter")
            target_face = feat.face_ids[0] if feat.face_ids else f"Hole_{fid}"
            if dia is not None and isinstance(dia, (int, float)) and dia > 0:
                # Heuristic: roughly 12-16 elements around circumference -> suggested element size ~ 0.25 * diameter
                sugg_size = float(dia) * 0.25
                candidates.append(
                    MeshRefinementCandidate(
                        target_id=target_face,
                        entity_type="Face",
                        feature_type=ftype,
                        characteristic_name="diameter",
                        characteristic_value=float(dia),
                        suggested_size=sugg_size,
                        priority="high",
                        confidence=feat.confidence,
                        reason=f"Circumferential curvature resolution for hole feature {fid} (heuristic size ~ 0.25D)",
                        evidence=(f"feature_id:{fid}", f"diameter:{dia:.4g}", "basis:hole_circumference_heuristic"),
                    )
                )
            else:
                candidates.append(
                    MeshRefinementCandidate(
                        target_id=target_face,
                        entity_type="Face",
                        feature_type=ftype,
                        characteristic_name="diameter",
                        characteristic_value=None,
                        suggested_size=None,
                        priority="normal",
                        confidence=feat.confidence,
                        reason=f"Hole candidate {fid} has unproven diameter; refinement size cannot be derived",
                        evidence=(f"feature_id:{fid}", "reason:INSUFFICIENT_DIAMETER_EVIDENCE"),
                    )
                )

        elif ftype == FeatureType.FILLET:
            rad = geom.get("radius")
            target_face = feat.face_ids[0] if feat.face_ids else f"Fillet_{fid}"
            if rad is not None and isinstance(rad, (int, float)) and rad > 0:
                # Heuristic: 2-3 elements across fillet span -> suggested size ~ 0.5 * radius
                sugg_size = float(rad) * 0.5
                candidates.append(
                    MeshRefinementCandidate(
                        target_id=target_face,
                        entity_type="Face",
                        feature_type=ftype,
                        characteristic_name="radius",
                        characteristic_value=float(rad),
                        suggested_size=sugg_size,
                        priority="normal",
                        confidence=feat.confidence,
                        reason=f"Curved transition boundary resolution for fillet {fid} (heuristic size ~ 0.5R)",
                        evidence=(f"feature_id:{fid}", f"radius:{rad:.4g}", "basis:fillet_span_heuristic"),
                    )
                )
            else:
                candidates.append(
                    MeshRefinementCandidate(
                        target_id=target_face,
                        entity_type="Face",
                        feature_type=ftype,
                        characteristic_name="radius",
                        characteristic_value=None,
                        suggested_size=None,
                        priority="low",
                        confidence=feat.confidence,
                        reason=f"Fillet candidate {fid} has unproven radius; refinement size cannot be derived",
                        evidence=(f"feature_id:{fid}", "reason:INSUFFICIENT_RADIUS_EVIDENCE"),
                    )
                )

        elif ftype == FeatureType.CHAMFER:
            width = geom.get("chamfer_width")
            target_face = feat.face_ids[0] if feat.face_ids else f"Chamfer_{fid}"
            if width is not None and isinstance(width, (int, float)) and width > 0:
                sugg_size = float(width) * 0.5
                candidates.append(
                    MeshRefinementCandidate(
                        target_id=target_face,
                        entity_type="Face",
                        feature_type=ftype,
                        characteristic_name="chamfer_width",
                        characteristic_value=float(width),
                        suggested_size=sugg_size,
                        priority="normal",
                        confidence=feat.confidence,
                        reason=f"Planar transition resolution for chamfer {fid} (heuristic size ~ 0.5W)",
                        evidence=(f"feature_id:{fid}", f"chamfer_width:{width:.4g}", "basis:chamfer_width_heuristic"),
                    )
                )
            else:
                candidates.append(
                    MeshRefinementCandidate(
                        target_id=target_face,
                        entity_type="Face",
                        feature_type=ftype,
                        characteristic_name="chamfer_width",
                        characteristic_value=None,
                        suggested_size=None,
                        priority="low",
                        confidence=feat.confidence,
                        reason=f"Chamfer candidate {fid} has unproven width; refinement size cannot be derived",
                        evidence=(f"feature_id:{fid}", "reason:INSUFFICIENT_CHAMFER_WIDTH_EVIDENCE"),
                    )
                )

        elif ftype == FeatureType.RIB:
            thk = geom.get("thickness")
            target_face = feat.face_ids[0] if feat.face_ids else f"Rib_{fid}"
            if thk is not None and isinstance(thk, (int, float)) and thk > 0:
                sugg_size = float(thk) * 0.5
                candidates.append(
                    MeshRefinementCandidate(
                        target_id=target_face,
                        entity_type="Face",
                        feature_type=ftype,
                        characteristic_name="thickness",
                        characteristic_value=float(thk),
                        suggested_size=sugg_size,
                        priority="high",
                        confidence=feat.confidence,
                        reason=f"Thin-wall cross-thickness element resolution for rib {fid} (heuristic size ~ 0.5T)",
                        evidence=(f"feature_id:{fid}", f"thickness:{thk:.4g}", "basis:rib_thickness_heuristic"),
                    )
                )
            else:
                candidates.append(
                    MeshRefinementCandidate(
                        target_id=target_face,
                        entity_type="Face",
                        feature_type=ftype,
                        characteristic_name="thickness",
                        characteristic_value=None,
                        suggested_size=None,
                        priority="normal",
                        confidence=feat.confidence,
                        reason=f"Rib candidate {fid} has unproven thickness; refinement size cannot be derived",
                        evidence=(f"feature_id:{fid}", "reason:INSUFFICIENT_THICKNESS_EVIDENCE"),
                    )
                )

        elif ftype == FeatureType.CONTACT_PLANE:
            target_face = feat.face_ids[0] if feat.face_ids else f"Contact_{fid}"
            area = geom.get("area")
            candidates.append(
                MeshRefinementCandidate(
                    target_id=target_face,
                    entity_type="Face",
                    feature_type=ftype,
                    characteristic_name="area" if area else None,
                    characteristic_value=float(area) if area else None,
                    suggested_size=None,  # Contact plane size is left to assembly contact discretization
                    priority="normal",
                    confidence=feat.confidence,
                    reason=f"Potential planar contact/bearing surface candidate {fid}; mesh transition review recommended",
                    evidence=(f"feature_id:{fid}", "basis:contact_plane_candidate_hint"),
                )
            )

    # -------------------------------------------------------------------------
    # Layer 4: Strategy Recommendation & Capability Gate
    # -------------------------------------------------------------------------
    # Determine final capability status
    warning_risks = [r for r in risks if r.severity in (MeshabilitySeverity.WARNING, MeshabilitySeverity.RISK)]
    if warning_risks or resolved_health.status == CapabilityStatus.ASSISTED:
        status = CapabilityStatus.ASSISTED
    else:
        status = CapabilityStatus.SUPPORTED

    evidence.append(f"risk_count:{len(risks)}")
    evidence.append(f"refinement_candidate_count:{len(candidates)}")

    return MeshabilityResult(
        model_id=model.model_id,
        status=status,
        is_meshable=True,
        recommended_strategy=RecommendedMeshStrategy.UNDECIDED,
        target_mesh_size=target_mesh_size,
        characteristic_length=char_len,
        risks=tuple(risks),
        refinement_candidates=tuple(candidates),
        scale_metrics=scale_metrics,
        evidence=tuple(evidence),
        limitations=limitations,
    )
