"""Geometry Health Inspection and Defect Detection Gate for Track GA-1.2.

Provides a multi-layered, non-destructive validation engine across:
1. Topological Consistency (non-manifold edges, dangling edges, shell closure)
2. Geometric Invariants (degenerate zero-length edges, zero-area faces)
3. Scale Anomalies (micro-slivers, tiny edge features relative to bounding box)
4. Analysis-Intent Compatibility (distinguishing intentional shell models from defective solids)

CRITICAL ARCHITECTURAL BOUNDARY:
GA-1.2 strictly performs DETECTION and AUDITING. It never performs destructive
auto-healing, auto-stitching, or synthetic topological modification, avoiding the
creation of an unverified secondary CAD kernel.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple

from ..capability_boundary import CapabilityBoundary, CapabilityStatus
from .model import GeometryModel


class HealthSeverity(str, Enum):
    """Severity of a detected geometric or topological condition."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class HealthIssueKind(str, Enum):
    """Categorized geometry and topology defect classes."""
    # Topological Consistency
    NON_MANIFOLD_EDGE = "NON_MANIFOLD_EDGE"
    DANGLING_EDGE = "DANGLING_EDGE"
    UNCLOSED_SHELL_IN_SOLID = "UNCLOSED_SHELL_IN_SOLID"
    DISCONNECTED_TOPOLOGY = "DISCONNECTED_TOPOLOGY"

    # Geometric Consistency
    DEGENERATE_EDGE = "DEGENERATE_EDGE"
    DEGENERATE_FACE = "DEGENERATE_FACE"
    TOLERANCE_GAP = "TOLERANCE_GAP"
    SELF_INTERSECTION_INDICATOR = "SELF_INTERSECTION_INDICATOR"

    # Scale Anomalies
    TINY_EDGE = "TINY_EDGE"
    SLIVER_FACE = "SLIVER_FACE"

    # Analysis Intent Compatibility
    INTENT_TOPOLOGY_MISMATCH = "INTENT_TOPOLOGY_MISMATCH"


@dataclass(frozen=True)
class GeometryHealthIssue:
    """Specific detected geometric flaw or anomalous metric."""
    issue_id: str
    kind: HealthIssueKind
    severity: HealthSeverity
    description: str
    entity_ids: Tuple[str, ...] = ()
    location: Optional[Tuple[float, float, float]] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None

    def __post_init__(self):
        if not self.issue_id:
            raise ValueError("issue_id is required")
        if not self.description:
            raise ValueError("description is required")


@dataclass(frozen=True)
class GeometryHealthReport:
    """Consolidated geometric audit report and capability gate determination."""
    model_id: str
    status: CapabilityStatus
    analysis_intent: str
    issues: Tuple[GeometryHealthIssue, ...] = ()
    summary: Dict[str, int] = field(default_factory=dict)
    characteristic_length: float = 0.0

    @property
    def is_acceptable_for_analysis(self) -> bool:
        """True if model can proceed to downstream meshing without blocking."""
        return self.status in (CapabilityStatus.SUPPORTED, CapabilityStatus.ASSISTED)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity in (HealthSeverity.ERROR, HealthSeverity.CRITICAL))

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == HealthSeverity.WARNING)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "status": self.status.value,
            "analysis_intent": self.analysis_intent,
            "characteristic_length": self.characteristic_length,
            "is_acceptable": self.is_acceptable_for_analysis,
            "counts": {
                "critical": sum(1 for i in self.issues if i.severity == HealthSeverity.CRITICAL),
                "error": sum(1 for i in self.issues if i.severity == HealthSeverity.ERROR),
                "warning": sum(1 for i in self.issues if i.severity == HealthSeverity.WARNING),
                "info": sum(1 for i in self.issues if i.severity == HealthSeverity.INFO),
            },
            "issues": [
                {
                    "issue_id": i.issue_id,
                    "kind": i.kind.value,
                    "severity": i.severity.value,
                    "description": i.description,
                    "entity_ids": list(i.entity_ids),
                    "metric_value": i.metric_value,
                    "threshold": i.threshold,
                }
                for i in self.issues
            ],
        }


def inspect_geometry_health(
    model: GeometryModel,
    analysis_intent: str = "auto",
    relative_tiny_edge_ratio: float = 1e-3,
    relative_sliver_aspect_ratio: float = 50.0,
    absolute_zero_tolerance: float = 1e-7,
) -> GeometryHealthReport:
    """Execute four-layer non-destructive geometry health inspection.

    Parameters:
        model: Canonical GeometryModel from GA-1.1 ingestion.
        analysis_intent: Expected FEA application ("auto", "solid", "shell").
                         "auto" infers from topological primitives.
        relative_tiny_edge_ratio: Ratio of characteristic length below which edges
                                  are flagged as potential sliver defects.
        relative_sliver_aspect_ratio: Aspect ratio threshold for sliver face warning.
        absolute_zero_tolerance: Numerical threshold for degenerate zero metrics.

    Returns:
        GeometryHealthReport with explicit CapabilityStatus mapping.
    """
    if model.is_empty:
        issue = GeometryHealthIssue(
            issue_id="ISSUE_EMPTY_GEOMETRY",
            kind=HealthIssueKind.DISCONNECTED_TOPOLOGY,
            severity=HealthSeverity.CRITICAL,
            description="CAD model contains zero geometric or topological entities",
        )
        return GeometryHealthReport(
            model_id=model.model_id,
            status=CapabilityStatus.BLOCKED,
            analysis_intent=analysis_intent,
            issues=(issue,),
            summary={"CRITICAL": 1},
        )

    # Compute characteristic length from bounding box
    char_len = 1.0
    if model.bounding_box:
        char_len = max(model.bounding_box.diagonal, 1.0)

    tiny_edge_thresh = char_len * relative_tiny_edge_ratio

    issues: List[GeometryHealthIssue] = []
    issue_counter = 0

    # -----------------------------------------------------------------------
    # Layer 1: Topological Consistency & Manifoldness
    # -----------------------------------------------------------------------
    # Build edge-to-face connectivity map if faces have edge_ids
    edge_face_count: Dict[str, int] = {}
    for face in model.faces:
        for eid in face.edge_ids:
            edge_face_count[eid] = edge_face_count.get(eid, 0) + 1

    # Check for non-manifold edges (>2 incident faces in 2-manifold B-Rep)
    for eid, count in edge_face_count.items():
        if count > 2:
            issue_counter += 1
            issues.append(
                GeometryHealthIssue(
                    issue_id=f"ISSUE_NM_{issue_counter}",
                    kind=HealthIssueKind.NON_MANIFOLD_EDGE,
                    severity=HealthSeverity.ERROR,
                    description=f"Edge '{eid}' is shared by {count} faces (>2 violates 2-manifold boundary condition)",
                    entity_ids=(eid,),
                    metric_value=float(count),
                    threshold=2.0,
                )
            )

    # Check for dangling disconnected edges in solid intent
    if model.face_count > 0 and len(edge_face_count) > 0:
        for edge in model.edges:
            if edge.id not in edge_face_count:
                issue_counter += 1
                issues.append(
                    GeometryHealthIssue(
                        issue_id=f"ISSUE_DANGLE_{issue_counter}",
                        kind=HealthIssueKind.DANGLING_EDGE,
                        severity=HealthSeverity.WARNING,
                        description=f"Edge '{edge.id}' is disconnected from any boundary face (wireframe sliver)",
                        entity_ids=(edge.id,),
                    )
                )

    # -----------------------------------------------------------------------
    # Layer 2: Geometric Consistency & Invariants
    # -----------------------------------------------------------------------
    # Degenerate zero-length edges
    for edge in model.edges:
        if edge.length is not None and edge.length < absolute_zero_tolerance:
            issue_counter += 1
            issues.append(
                GeometryHealthIssue(
                    issue_id=f"ISSUE_DEG_E_{issue_counter}",
                    kind=HealthIssueKind.DEGENERATE_EDGE,
                    severity=HealthSeverity.ERROR,
                    description=f"Edge '{edge.id}' has degenerate near-zero length {edge.length:.2e}",
                    entity_ids=(edge.id,),
                    metric_value=edge.length,
                    threshold=absolute_zero_tolerance,
                )
            )

    # Degenerate zero-area faces
    for face in model.faces:
        if face.area is not None and face.area < absolute_zero_tolerance:
            issue_counter += 1
            issues.append(
                GeometryHealthIssue(
                    issue_id=f"ISSUE_DEG_F_{issue_counter}",
                    kind=HealthIssueKind.DEGENERATE_FACE,
                    severity=HealthSeverity.ERROR,
                    description=f"Face '{face.id}' has degenerate near-zero area {face.area:.2e}",
                    entity_ids=(face.id,),
                    metric_value=face.area,
                    threshold=absolute_zero_tolerance,
                )
            )

    # -----------------------------------------------------------------------
    # Layer 3: Scale Anomalies & Micro-Features
    # -----------------------------------------------------------------------
    for edge in model.edges:
        if edge.length is not None and absolute_zero_tolerance <= edge.length < tiny_edge_thresh:
            issue_counter += 1
            issues.append(
                GeometryHealthIssue(
                    issue_id=f"ISSUE_TINY_E_{issue_counter}",
                    kind=HealthIssueKind.TINY_EDGE,
                    severity=HealthSeverity.WARNING,
                    description=(
                        f"Edge '{edge.id}' has sub-scale length {edge.length:.3f} "
                        f"(< {tiny_edge_thresh:.3f}); may trigger severe local mesh distortion"
                    ),
                    entity_ids=(edge.id,),
                    metric_value=edge.length,
                    threshold=tiny_edge_thresh,
                )
            )

    # Micro-sliver faces (e.g. extremely small area compared to bounding box square)
    ref_area = char_len * char_len
    for face in model.faces:
        if face.area is not None and face.area > absolute_zero_tolerance:
            if face.area < ref_area * 1e-5:
                issue_counter += 1
                issues.append(
                    GeometryHealthIssue(
                        issue_id=f"ISSUE_SLIVER_F_{issue_counter}",
                        kind=HealthIssueKind.SLIVER_FACE,
                        severity=HealthSeverity.WARNING,
                        description=(
                            f"Face '{face.id}' is a micro-sliver surface (area {face.area:.2e} "
                            f"is < 1e-5 of reference model scale)"
                        ),
                        entity_ids=(face.id,),
                        metric_value=face.area,
                        threshold=ref_area * 1e-5,
                    )
                )

    # -----------------------------------------------------------------------
    # Layer 4: Analysis-Intent Compatibility
    # -----------------------------------------------------------------------
    # Normalize analysis intent
    resolved_intent = analysis_intent.lower()
    if resolved_intent == "auto":
        resolved_intent = "solid" if model.solid_count > 0 else "shell"

    if resolved_intent == "solid":
        # In solid mechanics, open shells without solid closure are un-meshable volumetric defects
        if model.solid_count == 0 and model.has_open_shells:
            issue_counter += 1
            issues.append(
                GeometryHealthIssue(
                    issue_id=f"ISSUE_INTENT_{issue_counter}",
                    kind=HealthIssueKind.UNCLOSED_SHELL_IN_SOLID,
                    severity=HealthSeverity.CRITICAL,
                    description=(
                        "Model contains only unclosed open shells (sheet body); "
                        "cannot perform 3D solid continuum meshing without volume closure"
                    ),
                )
            )
        elif model.has_open_shells and model.solid_count > 0:
            issue_counter += 1
            issues.append(
                GeometryHealthIssue(
                    issue_id=f"ISSUE_INTENT_{issue_counter}",
                    kind=HealthIssueKind.UNCLOSED_SHELL_IN_SOLID,
                    severity=HealthSeverity.WARNING,
                    description="Model contains mixed solid bodies and auxiliary open sheet shells",
                )
            )
    elif resolved_intent == "shell":
        # In shell mechanics, open shells are intentional and valid
        if model.has_open_shells:
            issue_counter += 1
            issues.append(
                GeometryHealthIssue(
                    issue_id=f"ISSUE_INFO_SHELL_{issue_counter}",
                    kind=HealthIssueKind.INTENT_TOPOLOGY_MISMATCH,
                    severity=HealthSeverity.INFO,
                    description="Intentional open shell geometry confirmed for 2D/3D shell element meshing",
                )
            )

    # -----------------------------------------------------------------------
    # Determine Final Capability Gate Status
    # -----------------------------------------------------------------------
    summary = {
        HealthSeverity.CRITICAL.value: sum(1 for i in issues if i.severity == HealthSeverity.CRITICAL),
        HealthSeverity.ERROR.value: sum(1 for i in issues if i.severity == HealthSeverity.ERROR),
        HealthSeverity.WARNING.value: sum(1 for i in issues if i.severity == HealthSeverity.WARNING),
        HealthSeverity.INFO.value: sum(1 for i in issues if i.severity == HealthSeverity.INFO),
    }

    if summary[HealthSeverity.CRITICAL.value] > 0 or summary[HealthSeverity.ERROR.value] > 0:
        status = CapabilityStatus.BLOCKED
    elif summary[HealthSeverity.WARNING.value] > 0:
        status = CapabilityStatus.ASSISTED
    else:
        status = CapabilityStatus.SUPPORTED

    return GeometryHealthReport(
        model_id=model.model_id,
        status=status,
        analysis_intent=resolved_intent,
        issues=tuple(issues),
        summary=summary,
        characteristic_length=char_len,
    )
