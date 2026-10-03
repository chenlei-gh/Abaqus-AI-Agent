"""Geometry and CAD processing subsystem for Abaqus-AI-Agent (Track GA-1)."""

from .model import (
    CadBoundingBox,
    CadEdge,
    CadFace,
    CadFormat,
    CadLoop,
    CadProvenance,
    CadShell,
    CadSolid,
    CadUnit,
    CadVertex,
    GeometryModel,
)
from .cad_ingestion import (
    CadIngestionError,
    classify_cad_model,
    compute_file_sha256,
    detect_cad_format,
    ingest_cad_file,
)
from .health import (
    GeometryHealthIssue,
    GeometryHealthReport,
    HealthIssueKind,
    HealthSeverity,
    inspect_geometry_health,
)
from .topology import (
    NormalizedTopology,
    normalize_topology,
)
from .features import (
    FeatureCandidate,
    FeatureEvidence,
    FeatureType,
    HoleSubType,
    detect_fastener_holes,
)

__all__ = [
    "CadBoundingBox",
    "CadEdge",
    "CadFace",
    "CadFormat",
    "CadLoop",
    "CadProvenance",
    "CadShell",
    "CadSolid",
    "CadUnit",
    "CadVertex",
    "GeometryModel",
    "CadIngestionError",
    "classify_cad_model",
    "compute_file_sha256",
    "detect_cad_format",
    "ingest_cad_file",
    "GeometryHealthIssue",
    "GeometryHealthReport",
    "HealthIssueKind",
    "HealthSeverity",
    "inspect_geometry_health",
    "NormalizedTopology",
    "normalize_topology",
    "FeatureCandidate",
    "FeatureEvidence",
    "FeatureType",
    "HoleSubType",
    "detect_fastener_holes",
]
