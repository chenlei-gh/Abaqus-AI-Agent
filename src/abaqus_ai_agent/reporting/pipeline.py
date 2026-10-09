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
        require_deliverable: bool = True,
        odb_path: Optional[Union[str, Path]] = None,
        input_hash: Optional[str] = None,
        launcher: Optional[str] = None,
    ) -> Tuple[ReportDeliveryCard, ArtifactPointer, EngineeringReportData]:
        """Compile report, render HTML & Markdown, register artifacts, and produce LLM card."""
        # 0. Early Delivery Gate: Verify authorization BEFORE any file creation or disk I/O.
        status_val = "UNKNOWN"
        if hasattr(acceptance_info, "status"):
            status_val = getattr(acceptance_info, "status")
        elif isinstance(acceptance_info, dict):
            status_val = acceptance_info.get("status", "UNKNOWN")

        # Strict deliverable authorization determination (P0-D-1):
        # Official deliverable authorization is granted IF AND ONLY IF:
        # acceptance_info has deliverable is True (or for dict, acceptance_info.get("deliverable") is True).
        # Legacy objects with passed=True / status="PASS" but missing explicit `deliverable is True`
        # MUST NOT be granted official delivery authorization!
        is_deliverable = False
        if hasattr(acceptance_info, "deliverable"):
            is_deliverable = getattr(acceptance_info, "deliverable") is True
        elif isinstance(acceptance_info, dict) and "deliverable" in acceptance_info:
            is_deliverable = acceptance_info["deliverable"] is True

        if require_deliverable and not is_deliverable:
            raise PermissionError(
                f"Official engineering delivery blocked: deliverable is False (acceptance_status={status_val}). "
                "Only runs with verified evidence and valid PASS acceptance can be released as official deliverables. "
                "No report artifacts were written to disk."
            )

        delivery_mode = "official_delivery" if is_deliverable else "diagnostic_draft"
        effective_title = title if is_deliverable else f"[DIAGNOSTIC / NON-DELIVERABLE DRAFT] {title}"

        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        # 1. Process and bind authentic CAE visualization figures
        # If visualization specs are requested and images are not yet rendered, invoke headless authentic Viewer if odb_path provided
        missing_specs = []
        for spec in visualization_specs:
            img_path = target_dir / spec.target_filename
            alt_path = Path(spec.target_filename)
            if not img_path.exists() and not alt_path.is_file():
                missing_specs.append(spec)

        if missing_specs and odb_path:
            from ..execution.odb_rendering import render_authentic_visualizations
            render_authentic_visualizations(
                odb_path=odb_path,
                specs=missing_specs,
                output_dir=target_dir,
                launcher=launcher,
                run_id=run_id,
                input_hash=input_hash,
            )

        report_figures: List[ReportFigure] = []
        fig_pointers: List[ArtifactPointer] = []

        for spec in visualization_specs:
            img_path = target_dir / spec.target_filename
            if not img_path.exists():
                alt_path = Path(spec.target_filename)
                if alt_path.is_file():
                    img_path = alt_path

            if not img_path.exists():
                if require_deliverable or is_deliverable:
                    raise FileNotFoundError(
                        f"Official engineering delivery blocked: required CAE visualization asset '{spec.target_filename}' "
                        f"({spec.field_name}.{spec.component}) does not exist on disk. "
                        "Synthetic placeholder generation is strictly prohibited for official deliverables; "
                        "authentic CAE results rendered from live ODB extraction are required."
                    )
                # In diagnostic draft mode: do not synthesize fake CAE images; skip missing asset
                continue

            img_bytes = img_path.read_bytes()
            img_sha256 = hashlib.sha256(img_bytes).hexdigest()
            rel_path = str(img_path.as_posix())

            report_figures.append(spec.to_report_figure(rel_path))
            fig_pointers.append(spec.to_artifact_pointer(rel_path, len(img_bytes), img_sha256))

        # 2. Build polymorphic EngineeringReportData
        report_data = self.builder.build_report_data(
            title=effective_title,
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

        # 3. Deterministically render Semantic HTML (Single authoritative deliverable, all non-HTML stripped)
        html_content = render_report(report_data, fmt="html")
        html_file = target_dir / "report.html"
        html_bytes = html_content.encode("utf-8")
        html_file.write_bytes(html_bytes)
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
                "title": effective_title,
                "case_id": case_id,
                "language": language,
                "sections": list(self.builder.determine_active_sections()),
                "delivery_mode": delivery_mode,
                "is_diagnostic_draft": not is_deliverable,
            },
        )

        delivery_card = ReportDeliveryCard(
            report_artifact_id=report_pointer.artifact_id,
            report_title=effective_title,
            format="bilingual_html",
            location=report_pointer.location,
            acceptance_status=status_val,
            deliverable=is_deliverable,
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
