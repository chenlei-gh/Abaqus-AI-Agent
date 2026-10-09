"""Deterministic Report Delivery Pipeline (P0-5).

Full Data Plane pipeline connecting:
EngineeringState + AdaptiveReportBuilder + VisualizationSpecs + InterpretationCard ->
Deterministic Renderer -> Output Files (.html/.md) + ArtifactPointers -> ReportDeliveryCard (for LLM).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

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
        figures: Sequence[ReportFigure] = (),
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

        is_official_delivery = bool(require_deliverable and is_deliverable)
        delivery_mode = "official_delivery" if is_official_delivery else "diagnostic_draft"
        effective_title = title if is_official_delivery else f"[DIAGNOSTIC / NON-DELIVERABLE DRAFT] {title}"

        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        # Isolate / clean any pre-existing report.html to guarantee zero stale deliverable leakage
        stale_report = target_dir / "report.html"
        if stale_report.exists():
            try:
                stale_report.unlink()
            except Exception as exc:
                raise PermissionError(
                    f"Official delivery blocked: unable to safely remove existing stale report at '{stale_report}'. "
                    f"Atomic report isolation failed: {exc}"
                )

        # Compute effective ODB hash if odb_path is provided and exists
        eff_odb_hash: Optional[str] = None
        if odb_path and Path(odb_path).is_file():
            hasher_odb = hashlib.sha256()
            with open(str(odb_path), "rb") as _fh:
                while chunk := _fh.read(65536):
                    hasher_odb.update(chunk)
            eff_odb_hash = hasher_odb.hexdigest()

        # Determine effective visualization specs: if not explicitly supplied and no pre-existing figures provided,
        # automatically invoke the Adaptive Figure Selector based on physics domain & engineering objective.
        effective_specs: List[VisualizationSpec] = list(visualization_specs)
        if not effective_specs and not figures and odb_path:
            from .figure_selector import FigureSelector
            selector = FigureSelector()
            selection_res = selector.select_figures(
                domain=getattr(self.builder, "physics_domain", "structural"),
                objective=getattr(self.builder, "objective", AnalysisObjective.GENERAL_FEA),
                odb_path=odb_path,
                extracted_results=results_info,
                output_dir=target_dir,
                run_id=run_id,
                input_hash=input_hash,
                odb_hash=eff_odb_hash,
            )
            effective_specs = list(selection_res.specs)

        # 1. Process and bind authentic CAE visualization figures
        # Match specs against provided figures using strict admit_figure_for_reuse
        from .figure_selector import admit_figure_for_reuse

        spec_to_figure: Dict[VisualizationSpec, ReportFigure] = {}
        missing_specs: List[VisualizationSpec] = []
        used_figure_paths = set()

        for spec in effective_specs:
            matched_fig = None
            for cand_fig in figures:
                if not isinstance(cand_fig, ReportFigure) or cand_fig.path in used_figure_paths:
                    continue
                is_adm, _reason = admit_figure_for_reuse(
                    figure=cand_fig,
                    current_run_id=run_id,
                    current_input_hash=input_hash,
                    current_odb_hash=eff_odb_hash,
                    target_field=spec.field_name,
                    target_component=spec.component,
                    target_step=spec.step_name,
                    target_frame=spec.frame_index,
                    target_region=getattr(spec, "region", "WHOLE_MODEL"),
                    target_output_position=getattr(spec, "output_position", "INTEGRATION_POINT"),
                    resolved_actual_frame=getattr(spec, "actual_frame_index", None),
                )
                if is_adm:
                    matched_fig = cand_fig
                    break

            if matched_fig is not None:
                spec_to_figure[spec] = matched_fig
                used_figure_paths.add(matched_fig.path)
            else:
                missing_specs.append(spec)

        rendered_by_filename: Dict[str, ReportFigure] = {}
        if missing_specs and odb_path:
            from ..execution.odb_rendering import render_authentic_visualizations
            rendered_list = render_authentic_visualizations(
                odb_path=odb_path,
                specs=missing_specs,
                output_dir=target_dir,
                launcher=launcher,
                run_id=run_id,
                input_hash=input_hash,
            )
            for rf in rendered_list:
                rendered_by_filename[Path(rf.path).name] = rf

        report_figures: List[ReportFigure] = []
        fig_pointers: List[ArtifactPointer] = []

        for spec in effective_specs:
            fig_obj: Optional[ReportFigure] = None
            if spec in spec_to_figure:
                fig_obj = spec_to_figure[spec]
            elif spec.target_filename in rendered_by_filename:
                fig_obj = rendered_by_filename[spec.target_filename]
            else:
                img_path = target_dir / spec.target_filename
                if not img_path.exists():
                    if is_official_delivery:
                        raise FileNotFoundError(
                            f"Official engineering delivery blocked: required CAE visualization asset '{spec.target_filename}' "
                            f"({spec.field_name}.{spec.component}) does not exist in target run directory '{target_dir}'. "
                            "Fallback to ambient working directory or synthetic placeholder generation is strictly prohibited; "
                            "authentic CAE results rendered from live ODB extraction are required."
                        )
                    continue

                if is_official_delivery:
                    raise PermissionError(
                        f"Official engineering delivery blocked: required figure '{spec.target_filename}' "
                        f"({spec.field_name}.{spec.component}) was neither admitted with verified provenance "
                        "nor rendered by a controlled Viewer session in this run. "
                        "Pre-existing files on disk cannot be automatically adopted or certified as authentic Viewer outputs."
                    )

                img_bytes = img_path.read_bytes()
                img_sha256 = hashlib.sha256(img_bytes).hexdigest()
                rel_path = str(img_path.as_posix())
                fig_obj = spec.to_report_figure(rel_path)
                fig_obj.metadata["image_sha256"] = img_sha256
                fig_obj.metadata["sha256"] = img_sha256
                if run_id:
                    fig_obj.metadata["run_id"] = run_id
                if input_hash:
                    fig_obj.metadata["input_hash"] = input_hash
                if eff_odb_hash:
                    fig_obj.metadata["odb_sha256"] = eff_odb_hash
                    fig_obj.metadata["odb_hash"] = eff_odb_hash
                fig_obj.metadata["viewer_rendered"] = False

            if fig_obj is None:
                continue

            img_p = Path(fig_obj.path)
            if not img_p.is_absolute():
                img_p = target_dir / img_p
            img_bytes = img_p.read_bytes()
            img_sha256 = hashlib.sha256(img_bytes).hexdigest()
            report_figures.append(fig_obj)
            fig_pointers.append(spec.to_artifact_pointer(str(img_p.as_posix()), len(img_bytes), img_sha256))

        # Handle provided figures not already matched to effective_specs
        if not effective_specs:
            # Caller supplied figures directly without explicit VisualizationSpecs
            for f in figures:
                f_path = Path(f.path)
                if not f_path.is_absolute():
                    f_path = target_dir / f_path
                if f_path.is_file():
                    f_bytes = f_path.read_bytes()
                    f_sha = hashlib.sha256(f_bytes).hexdigest()
                    fig_meta = dict(getattr(f, "metadata", {}) or {})
                    art_id = fig_meta.get("artifact_id") or f"FIG-{f.kind}-{run_id}"
                    fig_pointers.append(ArtifactPointer(
                        artifact_id=art_id,
                        type="figure",
                        media_type="image/svg+xml" if f_path.suffix.lower() == ".svg" else "image/png",
                        location=str(f_path.as_posix()),
                        size_bytes=len(f_bytes),
                        checksum_sha256=f_sha,
                        metadata=fig_meta,
                    ))
                    report_figures.append(f)
        else:
            # Caller or selector supplied effective_specs.
            # In official delivery mode: do not attach extra unrequested / unadmitted figures.
            # If caller provided extra figures that were not admitted against effective_specs, block official delivery!
            if is_official_delivery and figures:
                unmatched_figs = [f for f in figures if f.path not in used_figure_paths]
                if unmatched_figs:
                    raise PermissionError(
                        f"Official delivery blocked: caller provided unadmitted / unrequested figure(s) "
                        f"{[f.path for f in unmatched_figs]}. Every figure in official delivery must strictly match an admitted VisualizationSpec."
                    )
            elif not is_official_delivery:
                # In diagnostic draft mode: allow unadmitted figures as draft annex
                for f in figures:
                    if f.path in used_figure_paths:
                        continue
                    f_path = Path(f.path)
                    if not f_path.is_absolute():
                        f_path = target_dir / f_path
                    if f_path.is_file():
                        f_bytes = f_path.read_bytes()
                        f_sha = hashlib.sha256(f_bytes).hexdigest()
                        fig_meta = dict(getattr(f, "metadata", {}) or {})
                        art_id = fig_meta.get("artifact_id") or f"FIG-{f.kind}-{run_id}"
                        fig_pointers.append(ArtifactPointer(
                            artifact_id=art_id,
                            type="figure",
                            media_type="image/svg+xml" if f_path.suffix.lower() == ".svg" else "image/png",
                            location=str(f_path.as_posix()),
                            size_bytes=len(f_bytes),
                            checksum_sha256=f_sha,
                            metadata=fig_meta,
                        ))
                        report_figures.append(f)

        # 1.5 Final Delivery Gate: Anti-tamper & Cryptographic Lineage Verification
        if is_official_delivery:
            # 1. Strict execution context validation (mandatory, non-empty, non-placeholder)
            if not run_id or str(run_id).strip() in ("RUN-DEFAULT", "DEFAULT", "UNKNOWN", ""):
                raise PermissionError(
                    f"Official delivery blocked: current execution run_id is missing or placeholder ({run_id!r})"
                )

            if not input_hash or not str(input_hash).strip():
                raise PermissionError(
                    "Official delivery blocked: current execution input_hash is missing or empty. "
                    "Authentic engineering delivery requires full provenance traceability."
                )

            if not eff_odb_hash or not str(eff_odb_hash).strip():
                raise PermissionError(
                    "Official delivery blocked: authentic ODB hash is missing or ODB file was not provided. "
                    "Authentic engineering delivery requires live ODB provenance."
                )

            for fig in report_figures:
                f_path = Path(fig.path)
                if not f_path.is_absolute():
                    f_path = target_dir / f_path
                if not f_path.is_file() or f_path.stat().st_size <= 0:
                    raise PermissionError(
                        f"Official delivery blocked: figure physical file is missing or empty at '{fig.path}'"
                    )
                f_meta = fig.metadata or {}
                # 1. Live hash re-verification on disk (anti-tamper)
                f_bytes = f_path.read_bytes()
                live_sha256 = hashlib.sha256(f_bytes).hexdigest()
                rec_sha256 = f_meta.get("image_sha256") or f_meta.get("sha256")
                if not rec_sha256 or live_sha256 != str(rec_sha256).strip():
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' tampered or sha256 mismatch "
                        f"(recorded={rec_sha256!r}, live={live_sha256!r})"
                    )

                # 2. P0-2 & P0-10: Verify genuine PNG header & positive dimensions
                if f_path.suffix.lower() == ".png":
                    try:
                        from ..execution.odb_rendering import verify_png_image_integrity
                        verify_png_image_integrity(f_path)
                    except Exception as png_err:
                        raise PermissionError(
                            f"Official delivery blocked: Figure '{f_path.name}' is corrupt or not a valid PNG image: {png_err}"
                        )

                # 2. Strict run_id verification (mandatory, exact match)
                fig_run_id = f_meta.get("run_id")
                if not fig_run_id or str(fig_run_id).strip() != str(run_id).strip():
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' run_id mismatch "
                        f"(fig={fig_run_id!r}, current={run_id!r})"
                    )

                # 3. Strict input_hash verification (mandatory, exact match)
                fig_input_hash = f_meta.get("input_hash")
                if not fig_input_hash or str(fig_input_hash).strip() != str(input_hash).strip():
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' input_hash missing or mismatch "
                        f"(fig={fig_input_hash!r}, current={input_hash!r})"
                    )

                # 4. Strict odb_hash verification (mandatory, exact match)
                fig_odb_hash = f_meta.get("odb_sha256") or f_meta.get("odb_hash")
                if not fig_odb_hash or str(fig_odb_hash).strip() != str(eff_odb_hash).strip():
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' odb_hash missing or mismatch "
                        f"(fig={fig_odb_hash!r}, current={eff_odb_hash!r})"
                    )

                # 5. Strict engineering semantic metadata
                if not f_meta.get("field") and not f_meta.get("field_name"):
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' missing field output label in metadata"
                    )
                if not f_meta.get("output_position"):
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' missing output_position in metadata"
                    )

                # 6. Strict controlled Viewer origin
                if f_meta.get("viewer_rendered") is not True:
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' was not rendered by a controlled Viewer session"
                    )
                session_token = str(f_meta.get("viewer_session_token") or "").strip()
                if not session_token:
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' lacks authentic viewer_session_token evidence"
                    )
                session_nonce = str(f_meta.get("session_nonce") or "").strip()
                if not session_nonce or len(session_nonce) < 16:
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' lacks authentic session_nonce evidence"
                    )
                from ..execution.odb_rendering import compute_viewer_session_token
                expected_token = compute_viewer_session_token(
                    session_nonce=session_nonce,
                    run_id=str(run_id).strip(),
                    odb_sha256=str(eff_odb_hash).strip(),
                    target_filename=f_path.name,
                    image_sha256=live_sha256,
                )
                if session_token != expected_token:
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' viewer_session_token verification failed "
                        f"(token does not match live session evidence or was tampered)"
                    )
                rev_data = f_meta.get("render_execution_evidence")
                if not rev_data:
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' lacks mandatory render_execution_evidence"
                    )
                from ..execution.odb_rendering import verify_render_execution_evidence
                is_ev_valid, ev_reason = verify_render_execution_evidence(
                    evidence=rev_data,
                    expected_run_id=str(run_id).strip(),
                    expected_odb_sha256=str(eff_odb_hash).strip(),
                    expected_input_hash=str(input_hash).strip() if input_hash else None,
                )
                if not is_ev_valid:
                    raise PermissionError(
                        f"Official delivery blocked: Figure '{f_path.name}' render_execution_evidence invalid: {ev_reason}"
                    )

                ev_figs = rev_data.get("rendered_figures") or []
                matching_ev_fig = next((rf for rf in ev_figs if Path(rf.get("filename", "")).name == f_path.name), None)
                if matching_ev_fig:
                    rf_sha = matching_ev_fig.get("image_sha256")
                    if rf_sha and rf_sha != live_sha256:
                        raise PermissionError(
                            f"Official delivery blocked: Figure '{f_path.name}' content sha256 mismatch with signed evidence: {live_sha256} != {rf_sha}"
                        )

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

        # 3. Deterministically render Semantic HTML (Single authoritative deliverable, atomic publication)
        html_content = render_report(report_data, fmt="html")
        html_bytes = html_content.encode("utf-8")
        html_sha256 = hashlib.sha256(html_bytes).hexdigest()

        # Atomic publication: staged write to a unique temporary file in target_dir, then atomic replace
        html_file = target_dir / "report.html"
        tmp_report = target_dir / f".report_{secrets.token_hex(8)}.tmp"
        try:
            tmp_report.write_bytes(html_bytes)
            os.replace(tmp_report, html_file)
        except Exception as _pub_err:
            if tmp_report.exists():
                try:
                    tmp_report.unlink()
                except Exception:
                    pass
            raise PermissionError(
                f"Atomic report publication failed: unable to publish authoritative {html_file}: {_pub_err}"
            )

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
                "is_diagnostic_draft": not is_official_delivery,
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
