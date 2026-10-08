"""Visualization Specification and Deterministic Figure Binding (P0-5).

Establishes the contract:
Result -> Visualization Specification -> Deterministic Abaqus Image Generation -> ArtifactPointer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..contracts.artifact import ArtifactPointer
from ..contracts.report import ReportFigure


@dataclass(frozen=True)
class VisualizationSpec:
    """Rigorous specification for rendering postprocessing contour/vector figures."""
    artifact_id: str
    visualization_type: str              # "stress_hotspot", "displacement_contour", "contact_pressure", "mesh_quality"
    field_name: str                      # "S", "U", "CPRESS", "RF"
    component: str                       # "mises", "magnitude", "cpress", "norm"
    step_name: str = "Step-1"
    frame_index: int = -1
    view_mode: str = "AUTO_FIT"          # "AUTO_FIT", "ISOMETRIC", "TOP", "SECTION_Z"
    element_id: Optional[int] = None
    node_id: Optional[int] = None
    hotspot_location: Optional[Tuple[float, float, float]] = None
    caption_zh: str = ""
    caption_en: str = ""
    target_filename: str = "figure.png"

    def to_report_figure(self, physical_image_path: str) -> ReportFigure:
        """Produce the ReportFigure record for the deterministic renderer."""
        caption = f"{self.caption_zh} / {self.caption_en}" if self.caption_en else self.caption_zh
        return ReportFigure(
            kind=self.visualization_type,
            path=physical_image_path,
            caption=caption,
            source=f"{self.field_name}.{self.component} (Frame {self.frame_index})",
            metadata={
                "artifact_id": self.artifact_id,
                "step": self.step_name,
                "frame": self.frame_index,
                "element_id": self.element_id,
                "node_id": self.node_id,
                "hotspot_location": list(self.hotspot_location) if self.hotspot_location else None,
            },
        )

    def to_artifact_pointer(
        self,
        physical_image_path: str,
        size_bytes: int,
        checksum_sha256: str,
    ) -> ArtifactPointer:
        """Create the authoritative Data Plane pointer."""
        return ArtifactPointer(
            artifact_id=self.artifact_id,
            type="figure",
            media_type="image/png",
            location=physical_image_path,
            size_bytes=size_bytes,
            created_by="deterministic_visualization_pipeline",
            storage_scope="run",
            access_policy="llm_pointer_only",
            checksum_sha256=checksum_sha256,
            metadata={
                "visualization_type": self.visualization_type,
                "field": self.field_name,
                "component": self.component,
                "step": self.step_name,
            },
        )
