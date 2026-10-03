"""Geometry and CAD processing subsystem for Abaqus-AI-Agent (Track GA-1)."""

from .model import (
    CadBoundingBox,
    CadEdge,
    CadFace,
    CadFormat,
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

__all__ = [
    "CadBoundingBox",
    "CadEdge",
    "CadFace",
    "CadFormat",
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
]
