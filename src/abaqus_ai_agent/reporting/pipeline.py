"""Deterministic Report Delivery Pipeline (P0-5).

Full Data Plane pipeline connecting:
EngineeringState + AdaptiveReportBuilder + VisualizationSpecs + InterpretationCard ->
Deterministic Renderer -> Output Files (.html/.md) + ArtifactPointers -> ReportDeliveryCard (for LLM).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts.artifact import ArtifactPointer
from ..contracts.report import EngineeringReportData, ReportFigure
from .adaptive_template import AdaptiveReportBuilder, AnalysisObjective
from .interpretation_card import InterpretationCard, ReportDeliveryCard
from .renderer import render_report
from .visualization_spec import VisualizationSpec


class DeterministicReportPipeline:
    """Executes deterministic report compilation and artifact registration."""

    def __init__(self, builder: Optional[AdaptiveReportBuilder] = None):
        self.builder = builder or AdaptiveReportBuilder()

    def build_and_render(
        self,
        output_dir: Path,
        title: str,
        case_id: str,
        run_id: str,
        model_info: Dict[str, Any],
        results_info: Sequence[Any],
        acceptance_info: Any,
        visualization_specs: Sequence[VisualizationSpec] = (),
        interpretation_card: Optional[InterpretationCard] = None,
        language: str = "bilingual",
        materials_info: Sequence[Dict[str, Any]] = (),
        loads_info: Sequence[Dict[str, Any]] = (),
        bcs_info: Sequence[Dict[str, Any]] = (),
        mesh_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[ReportDeliveryCard, ArtifactPointer, EngineeringReportData]:
        """Compile report, render HTML & Markdown, register artifacts, and produce LLM card."""
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        # 1. Process and bind visualization figures
        report_figures: List[ReportFigure] = []
        fig_pointers: List[ArtifactPointer] = []

        for spec in visualization_specs:
            img_path = target_dir / spec.target_filename
            # If image doesn't exist on disk yet, generate deterministic SVG/placeholder
            if not img_path.exists():
                svg_content = f"""<svg width="400" height="250" xmlns="http://www.w3.org/2000/svg">
  <rect width="100%" height="100%" fill="#1a1a2e"/>
  <text x="50%" y="40%" fill="#e94560" font-size="16" text-anchor="middle" font-family="sans-serif">{spec.caption_zh}</text>
  <text x="50%" y="60%" fill="#0f3460" font-size="12" text-anchor="middle" font-family="sans-serif">{spec.caption_en}</text>
  <text x="50%" y="80%" fill="#ffffff" font-size="10" text-anchor="middle" font-family="sans-serif">{spec.field_name}.{spec.component} (Step: {spec.step_name})</text>
</svg>"""
                img_path.write_text(svg_content, encoding="utf-8")

            img_bytes = img_path.read_bytes()
            img_sha256 = hashlib.sha256(img_bytes).hexdigest()
            rel_path = str(img_path.as_posix())

            report_figures.append(spec.to_report_figure(rel_path))
            fig_pointers.append(spec.to_artifact_pointer(rel_path, len(img_bytes), img_sha256))

        # 2. Build polymorphic EngineeringReportData
        report_data = self.builder.build_report_data(
            title=title,
            case_id=case_id,
            run_id=run_id,
            model_info=model_info,
            results_info=results_info,
            acceptance_info=acceptance_info,
            figures=report_figures,
            interpretation_card=interpretation_card,
            materials_info=materials_info,
            loads_info=loads_info,
            bcs_info=bcs_info,
            mesh_info=mesh_info,
            language=language,
        )

        # 3. Deterministically render HTML & Markdown
        html_content = render_report(report_data, fmt="html")
        md_content = render_report(report_data, fmt="markdown")

        html_file = target_dir / "report.html"
        md_file = target_dir / "report.md"

        html_bytes = html_content.encode("utf-8")
        md_bytes = md_content.encode("utf-8")

        html_file.write_bytes(html_bytes)
        md_file.write_bytes(md_bytes)

        html_sha256 = hashlib.sha256(html_bytes).hexdigest()

        # 4. Construct Data Plane Artifact Pointer
        report_pointer = ArtifactPointer(
            artifact_id=f"ART-REP-HTML-{run_id}",
            type="report",
            media_type="text/html",
            location=str(html_file.as_posix()),
            size_bytes=len(html_bytes),
            created_by="deterministic_report_pipeline",
            storage_scope="run",
            access_policy="human_downloadable",
            checksum_sha256=html_sha256,
            metadata={
                "title": title,
                "case_id": case_id,
                "language": language,
                "sections": list(self.builder.determine_active_sections()),
            },
        )

        # 5. Extract critical metrics from acceptance/results for lean LLM card
        status_val = "PASS"
        if hasattr(acceptance_info, "status"):
            status_val = getattr(acceptance_info, "status")
        elif isinstance(acceptance_info, dict):
            status_val = acceptance_info.get("status", "PASS")

        delivery_card = ReportDeliveryCard(
            report_artifact_id=report_pointer.artifact_id,
            report_title=title,
            format="bilingual_html",
            location=report_pointer.location,
            acceptance_status=status_val,
            key_metrics={
                "max_mises_mpa": model_info.get("max_mises_mpa"),
                "max_displacement_mm": model_info.get("max_displacement_mm"),
            },
            active_sections=self.builder.determine_active_sections(),
            figures_count=len(report_figures),
            size_bytes=len(html_bytes),
            checksum_sha256=html_sha256,
        )

        return delivery_card, report_pointer, report_data
