"""Automatic Engineering Figure Selection & Provenance Binding Engine.

Selects the most engineering-relevant authentic CAE visualizations based on:
1. Engineering intent and physical domain (Static, Dynamic, Contact, Sealing, Thermal, Fatigue, Mesh Convergence).
2. Verified numerical results and hotspot locations (element/node/coordinates).
3. Authenticated ODB field availability (probed to prevent requesting absent outputs).
4. Strict 4-tier image source hierarchy:
   Tier 1: Pre-existing authentic Abaqus native images from this run (reused directly).
   Tier 2: Authentic headless Viewer export from live ODB.
   Tier 3: Missing field flagged as unavailable (zero synthetic placeholders).
   Tier 4: Fail-closed on Viewer failure with failure reason retained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..contracts.report import ReportFigure
from .visualization_spec import VisualizationSpec


@dataclass
class FigureSelectionResult:
    """Outcome of automatic engineering figure selection."""

    scenario: str
    specs: List[VisualizationSpec] = field(default_factory=list)
    reused_figures: List[ReportFigure] = field(default_factory=list)
    unavailable_fields: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_count(self) -> int:
        return len(self.specs) + len(self.reused_figures)


def probe_odb_fields(
    odb_path: Union[str, Path],
    launcher_cmd: Optional[str] = None,
) -> Optional[List[str]]:
    """Probe authentic field output variables available in target ODB.

    Returns list of uppercase field names if successfully probed via native Abaqus,
    or None if probe is offline or inconclusive.
    """
    path = Path(odb_path).resolve()
    if not path.is_file():
        return None

    try:
        from ..execution.solver import verify_authentic_odb_structure

        res = verify_authentic_odb_structure(path=path, launcher_cmd=launcher_cmd)
        if res.get("verified") and "steps" in res:
            steps_info = res["steps"]
            fld_set = set()
            for _s_name, s_data in steps_info.items():
                for fld in s_data.get("fields", []):
                    fld_set.add(str(fld).upper())
            return sorted(list(fld_set))
    except Exception:
        pass
    return None


class FigureSelector:
    """Class wrapper for automatic engineering figure selection."""

    def select_figures(
        self,
        domain: str = "structural",
        objective: str = "general_fea",
        odb_path: Optional[Union[str, Path]] = None,
        extracted_results: Optional[Any] = None,
        existing_figures: Sequence[Any] = (),
        run_id: Optional[str] = None,
        output_dir: Optional[Union[str, Path]] = None,
        hotspot_info: Optional[Dict[str, Any]] = None,
    ) -> FigureSelectionResult:
        avail_fields = None
        if odb_path and os.path.exists(str(odb_path)):
            avail_fields = probe_odb_fields(odb_path)

        res_dict = {}
        if isinstance(extracted_results, dict):
            res_dict = extracted_results
        elif isinstance(extracted_results, (list, tuple)):
            for item in extracted_results:
                if isinstance(item, dict):
                    k = item.get("metric") or item.get("name")
                    v = item.get("value")
                    if k:
                        res_dict[k] = v

        return select_engineering_figures(
            intent=None,
            physics_domain=domain,
            available_fields=avail_fields,
            odb_path=odb_path,
            results_info=res_dict,
            existing_figures=existing_figures,
            run_id=run_id,
            hotspot_info=hotspot_info,
            output_dir=output_dir,
        )


def identify_analysis_scenario(
    intent: Optional[Any] = None,
    physics_domain: Optional[str] = None,
) -> str:
    """Identify the standardized engineering analysis scenario."""
    # 1. Explicit domain override
    domain = (physics_domain or "").lower()
    if domain:
        if any(k in domain for k in ("sealing", "bolted_sealing", "gasket")):
            return "bolted_sealing"
        if any(k in domain for k in ("contact", "frictional")):
            return "contact"
        if any(k in domain for k in ("thermal", "heat", "temp")):
            return "thermal"
        if any(k in domain for k in ("dynamic", "transient", "explicit", "modal", "vibration")):
            return "transient_dynamics"
        if any(k in domain for k in ("fatigue", "durability", "damage")):
            return "fatigue"
        if any(k in domain for k in ("convergence", "mesh_refine", "mesh")):
            return "mesh_convergence"
        if any(k in domain for k in ("stiffness", "compliance", "deflection", "displacement")):
            return "displacement_stiffness"
        if any(k in domain for k in ("static", "stress", "linear_static")):
            return "static_structural"

    # 2. Inspect intent attributes
    if intent is not None:
        int_dom = (getattr(intent, "physics_domain", None) or "").lower()
        if int_dom:
            return identify_analysis_scenario(physics_domain=int_dom)

        int_kind = (getattr(intent, "kind", None) or getattr(intent, "analysis_type", None) or "").lower()
        if any(k in int_kind for k in ("thermal", "heat")):
            return "thermal"
        if any(k in int_kind for k in ("dynamic", "transient", "explicit")):
            return "transient_dynamics"

        if getattr(intent, "fatigue", None) is not None:
            return "fatigue"

        # Check contact / bolt criteria or connectors
        crit = getattr(intent, "acceptance_criteria", ()) or ()
        for c in crit:
            name_val = ""
            if isinstance(c, dict):
                name_val = (c.get("name") or c.get("value_key") or "").lower()
            else:
                name_val = getattr(c, "name", getattr(c, "value_key", "")).lower()

            if any(k in name_val for k in ("seal", "gasket", "bolt_load", "pretension")):
                return "bolted_sealing"
            if any(k in name_val for k in ("cpress", "copen", "contact", "slip")):
                return "contact"

        # Check description
        desc = (getattr(intent, "description", None) or "").lower()
        if any(k in desc for k in ("sealing", "gasket", "flange")):
            return "bolted_sealing"
        if any(k in desc for k in ("contact", "frictional")):
            return "contact"
        if any(k in desc for k in ("thermal", "temperature", "heat")):
            return "thermal"
        if any(k in desc for k in ("dynamic", "impact", "drop", "transient")):
            return "transient_dynamics"
        if any(k in desc for k in ("fatigue", "life", "endurance")):
            return "fatigue"
        if any(k in desc for k in ("convergence", "mesh study")):
            return "mesh_convergence"
        if any(k in desc for k in ("stiffness", "displacement", "deflection")):
            return "displacement_stiffness"

    return "static_structural"


def select_engineering_figures(
    intent: Optional[Any] = None,
    physics_domain: Optional[str] = None,
    results_info: Optional[Union[Dict[str, Any], Sequence[Any]]] = None,
    available_fields: Optional[Sequence[str]] = None,
    existing_figures: Optional[Sequence[Any]] = None,
    run_id: Optional[str] = None,
    odb_path: Optional[Union[str, Path]] = None,
    input_hash: Optional[str] = None,
    step_name: Optional[str] = None,
    frame_index: int = -1,
    hotspot_info: Optional[Dict[str, Any]] = None,
    output_dir: Optional[Union[str, Path]] = None,
) -> FigureSelectionResult:
    """Select the most engineering-relevant authentic CAE visualizations.

    Adheres strictly to the image source priority:
    1. Reuse validated native Abaqus image if already generated for this run.
    2. Dispatch headless Viewer request if field is supported in ODB.
    3. Mark missing required field as unavailable without synthetic placeholders.
    4. Fail-closed on Viewer execution failure.
    """
    scenario = identify_analysis_scenario(intent=intent, physics_domain=physics_domain)
    r_id = run_id or "RUN-DEFAULT"
    step = step_name or "Step-1"

    # If available_fields not explicitly provided, try probing ODB directly
    if available_fields is None and odb_path and os.path.exists(str(odb_path)):
        available_fields = probe_odb_fields(odb_path)

    # Normalize available fields (case-insensitive set)
    avail_set = None
    if available_fields is not None:
        avail_set = {f.upper() for f in available_fields}

    # Extract hotspot details if available
    elem_id = None
    node_id = None
    hotspot_coords = None
    if hotspot_info:
        elem_id = hotspot_info.get("element_id") or hotspot_info.get("element_label")
        node_id = hotspot_info.get("node_id") or hotspot_info.get("node_label")
        coords = hotspot_info.get("hotspot_location") or hotspot_info.get("coordinates")
        if coords and len(coords) >= 3:
            hotspot_coords = (float(coords[0]), float(coords[1]), float(coords[2]))

    # Existing figures lookup map: key -> ReportFigure
    # Priority 1: Reuse existing verified figures belonging strictly to THIS run
    existing_by_field: Dict[str, ReportFigure] = {}
    if existing_figures:
        for f in existing_figures:
            if not isinstance(f, ReportFigure):
                continue
            f_path = Path(f.path)
            if not f_path.is_file() or f_path.stat().st_size <= 0:
                continue
            f_meta = f.metadata or {}

            # Strict provenance verification: reject figures with mismatching run_id
            fig_run_id = f_meta.get("run_id")
            if fig_run_id and r_id != "RUN-DEFAULT" and fig_run_id != r_id:
                # Figure was generated by another run; reject ambient reuse
                continue

            fig_input_hash = f_meta.get("input_hash")
            if fig_input_hash and input_hash and fig_input_hash != input_hash:
                # Input changed; reject stale image
                continue

            f_field = (f_meta.get("field") or f_meta.get("variable_label") or "").upper()
            if f_field:
                existing_by_field[f_field] = f
            if f.kind:
                existing_by_field[f.kind.lower()] = f
            f_field = (f_meta.get("field") or f_meta.get("variable_label") or "").upper()
            if f_field:
                existing_by_field[f_field] = f
            if f.kind:
                existing_by_field[f.kind.lower()] = f

    # Define candidate figure templates per scenario
    # Each item: (kind, field_name, component, filename, caption_zh, caption_en, view_mode)
    candidates: List[Tuple[str, str, str, str, str, str, str]] = []

    if scenario == "static_structural":
        candidates = [
            (
                "stress_hotspot",
                "S",
                "mises",
                "mises_stress_hotspot.png",
                "von Mises 等效应力云图及危险应力集中区域",
                "von Mises equivalent stress contour and critical hotspot",
                "ISOMETRIC",
            ),
            (
                "displacement_contour",
                "U",
                "magnitude",
                "total_displacement.png",
                "结构整体位移变形云图 (U.magnitude)",
                "Total structural deformation contour (U.magnitude)",
                "AUTO_FIT",
            ),
        ]
    elif scenario == "displacement_stiffness":
        candidates = [
            (
                "displacement_contour",
                "U",
                "magnitude",
                "displacement_distribution.png",
                "位移分布云图与关键响应测点变形图",
                "Displacement distribution and key response deformation contour",
                "AUTO_FIT",
            ),
            (
                "stress_hotspot",
                "S",
                "mises",
                "stress_check.png",
                "结构应力分布验证云图",
                "Structural stress verification contour",
                "ISOMETRIC",
            ),
        ]
    elif scenario == "contact":
        candidates = [
            (
                "contact_pressure",
                "CPRESS",
                "",
                "contact_pressure_cpress.png",
                "接触对法向接触压力 (CPRESS) 分布云图",
                "Normal contact pressure (CPRESS) contour across interface",
                "AUTO_FIT",
            ),
            (
                "contact_opening",
                "COPEN",
                "",
                "contact_opening_copen.png",
                "接触面间隙与法向穿透状态 (COPEN) 分布图",
                "Contact opening/penetration clearance (COPEN) contour",
                "AUTO_FIT",
            ),
        ]
    elif scenario == "bolted_sealing":
        candidates = [
            (
                "sealing_pressure",
                "CPRESS",
                "",
                "gasket_sealing_cpress.png",
                "密封面/垫片接触压力分布与工程密封有效性验证图",
                "Gasket interface contact pressure and sealing integrity verification",
                "TOP",
            ),
            (
                "stress_hotspot",
                "S",
                "mises",
                "bolt_preload_stress.png",
                "螺栓连接体预紧与工作载荷应力响应云图",
                "Bolt pretension and working stress response contour",
                "ISOMETRIC",
            ),
        ]
    elif scenario == "thermal":
        candidates = [
            (
                "temperature_contour",
                "NT11",
                "",
                "temperature_field_nt11.png",
                "温度场 (NT11) 分布云图及主要温度梯度区",
                "Nodal temperature (NT11) field and thermal gradient contour",
                "AUTO_FIT",
            ),
            (
                "heat_flux",
                "HFL",
                "magnitude",
                "heat_flux_magnitude.png",
                "热通量矢量与热流密度分布云图",
                "Heat flux magnitude distribution contour",
                "AUTO_FIT",
            ),
        ]
    elif scenario == "transient_dynamics":
        candidates = [
            (
                "displacement_contour",
                "U",
                "magnitude",
                "transient_peak_displacement.png",
                "瞬态动力学峰值响应时刻结构总位移云图",
                "Peak response frame total displacement contour",
                "AUTO_FIT",
            ),
            (
                "stress_hotspot",
                "S",
                "mises",
                "transient_peak_stress.png",
                "瞬态动力学峰值响应时刻应力集中云图",
                "Peak response frame von Mises stress concentration contour",
                "ISOMETRIC",
            ),
        ]
    elif scenario == "mesh_convergence":
        candidates = [
            (
                "mesh_quality",
                "S",
                "mises",
                "mesh_convergence_gradient.png",
                "网格收敛性分析应力梯度敏感区云图",
                "Mesh convergence stress gradient sensitive zone contour",
                "ISOMETRIC",
            ),
            (
                "displacement_contour",
                "U",
                "magnitude",
                "mesh_convergence_disp.png",
                "不同网格细化阶段位移场对比云图",
                "Displacement field contour for mesh refinement verification",
                "AUTO_FIT",
            ),
        ]
    elif scenario == "fatigue":
        candidates = [
            (
                "fatigue_damage",
                "S",
                "mises",
                "fatigue_critical_stress.png",
                "疲劳危险截面应力幅值与损伤热点分布云图",
                "Fatigue critical cross-section stress amplitude and damage contour",
                "ISOMETRIC",
            ),
        ]
    else:
        # Default fallback
        candidates = [
            (
                "stress_hotspot",
                "S",
                "mises",
                "stress_contour.png",
                "结构应力云图",
                "Structural stress contour",
                "ISOMETRIC",
            ),
        ]

    selected_specs: List[VisualizationSpec] = []
    reused: List[ReportFigure] = []
    unavailable: List[Dict[str, str]] = []

    for kind, f_name, comp, filename, zh, en, view_mode in candidates:
        # Priority 1: Check if already exists in verified existing_figures for THIS run
        match = existing_by_field.get(f_name.upper()) or existing_by_field.get(kind.lower())
        if match is not None:
            reused.append(match)
            continue

        # Priority 3: Check ODB field availability
        if avail_set is not None and f_name.upper() not in avail_set:
            unavailable.append({
                "field": f_name,
                "kind": kind,
                "reason": f"Field output '{f_name}' is not present in target ODB. No synthetic placeholder created.",
            })
            continue

        # Priority 2: Create authentic VisualizationSpec for Viewer dispatch
        is_hotspot = ("hotspot" in kind or "stress" in kind or f_name == "S")
        spec = VisualizationSpec(
            artifact_id=f"FIG-{f_name}-{r_id}",
            visualization_type=kind,
            field_name=f_name,
            component=comp,
            step_name=step,
            frame_index=frame_index,
            view_mode=view_mode,
            element_id=elem_id if is_hotspot else None,
            node_id=node_id if is_hotspot else None,
            hotspot_location=hotspot_coords if is_hotspot else None,
            caption_zh=zh,
            caption_en=en,
            target_filename=filename,
        )
        selected_specs.append(spec)

    return FigureSelectionResult(
        scenario=scenario,
        specs=selected_specs,
        reused_figures=reused,
        unavailable_fields=unavailable,
        metadata={
            "run_id": r_id,
            "step_name": step,
            "hotspot_attached": bool(elem_id or node_id or hotspot_coords),
        },
    )
