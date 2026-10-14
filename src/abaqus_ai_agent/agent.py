from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from .actions.runner import execute
from .evidence.result import summarize_odb
from .planning.planner import plan_from_intents
from .validation.actions import validate_plan


@dataclass
class RunResult:
    plan: object
    execution_results: list
    job_result: object = None
    odb_summary: object = None


class AbaqusAIAgent:
    """Orchestrates planning, validation, native execution and evidence.

    It intentionally does not invent geometry. A BC/load action is executable
    only after its region expression has been produced by grounding or an
    explicit user/model selection.
    """
    def __init__(self, executor, mode: str = "production"):
        self.executor = executor
        self.mode = mode

    def apply_plan(self, plan):
        validate_plan(plan)
        results = []
        for action in plan.actions:
            results.append(execute(self.executor, action))
        return results

    def inspect_model(self):
        from .execution.inspection import get_model_info
        return get_model_info(self.executor)

    def snapshot(self):
        from .execution.snapshot import read_model_snapshot
        return read_model_snapshot(self.executor)

    def runtime_info(self):
        from .execution.runtime import detect_runtime
        return detect_runtime(self.executor)

    def viewport_state(self):
        from .execution.viewport import read_viewport_state
        return read_viewport_state(self.executor)

    def session_health(self):
        from .execution.session_health import session_health
        return session_health(self.executor)

    def job_artifacts(self, job_name, workdir=None):
        from .execution.artifacts import inspect_job_artifacts
        return inspect_job_artifacts(self.executor, job_name, workdir=workdir)

    def select_solver(self, intent):
        from .contracts.solver_selection import select_solver
        return select_solver(intent)

    def build_report(self, run, title=None, objective="", **sections):
        from .contracts.report import EngineeringReportData
        return EngineeringReportData.from_analysis(run, title=title, objective=objective, **sections)

    def export_odb_animation(
        self,
        odb_path: Any,
        output_path: Optional[Any] = None,
        field_name: str = "U",
        component: Optional[str] = "magnitude",
        step_name: Optional[str] = None,
        view_orientation: str = "Iso",
        frames: int = 24,
        duration_ms: int = 100,
        viewport_zoom_factor: Optional[float] = None,
        animation_mode: str = "full_timeline",
        active_motion_only: bool = True,
        motion_threshold: float = 0.005,
        launcher: Optional[str] = None,
        timeout: int = 240,
    ) -> Any:
        """Export authentic finite element contour/deformation animation from ODB via headless Abaqus Viewer."""
        from pathlib import Path
        from .execution.odb_rendering import render_odb_animation_headless
        if output_path is None:
            from .paths import resolve_deliverables_root
            odb_stem = Path(odb_path).stem
            output_path = resolve_deliverables_root() / f"{odb_stem}_{field_name}_animation.gif"

        eff_launcher = launcher or getattr(self.executor, "launcher", None)
        return render_odb_animation_headless(
            odb_path=odb_path,
            output_path=output_path,
            variable_label=field_name,
            component_or_invariant=component,
            step_name=step_name,
            view_orientation=view_orientation,
            frames=frames,
            duration_ms=duration_ms,
            viewport_zoom_factor=viewport_zoom_factor,
            animation_mode=animation_mode,
            active_motion_only=active_motion_only,
            motion_threshold=motion_threshold,
            launcher=eff_launcher,
            timeout=timeout,
        )

    def solve_user_inp(
        self,
        inp_path: Any,
        job_name: Optional[str] = None,
        project_context: Optional[Any] = None,
        timeout: Optional[int] = None,
        run_id: Optional[str] = None,
        odb_validator: Optional[Callable[[Path], bool]] = None,
        require_verified_odb: bool = False,
        generate_report: bool = False,
        report_title: Optional[str] = None,
        deliverables_dir: Optional[Union[str, Path]] = None,
        requirements: Sequence[Any] = (),
        include_animation: bool = True,
        launcher: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Directly solve a user-provided .inp file without redundant Python modeling."""
        from .execution.input_modes import solve_user_inp
        eff_launcher = launcher or getattr(self.executor, "launcher", None)
        return solve_user_inp(
            executor=self.executor,
            inp_path=inp_path,
            job_name=job_name,
            project_context=project_context,
            timeout=timeout,
            run_id=run_id,
            odb_validator=odb_validator,
            require_verified_odb=require_verified_odb,
            generate_report=generate_report,
            report_title=report_title,
            deliverables_dir=deliverables_dir,
            requirements=requirements,
            include_animation=include_animation,
            launcher=eff_launcher,
        )

    def edit_and_solve_user_inp(
        self,
        inp_path: Any,
        operations: Sequence[Any],
        target_filename: Optional[str] = None,
        job_name: Optional[str] = None,
        project_context: Optional[Any] = None,
        timeout: Optional[int] = None,
        run_id: Optional[str] = None,
        overwrite: bool = False,
        odb_validator: Optional[Callable[[Path], bool]] = None,
        rollback_on_solver_failure: bool = False,
        require_verified_odb: bool = False,
        generate_report: bool = False,
        report_title: Optional[str] = None,
        deliverables_dir: Optional[Union[str, Path]] = None,
        requirements: Sequence[Any] = (),
        include_animation: bool = True,
        launcher: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Surgically modify a user-provided .inp in an isolated working copy and solve it."""
        from .execution.input_modes import edit_and_solve_user_inp
        eff_launcher = launcher or getattr(self.executor, "launcher", None)
        return edit_and_solve_user_inp(
            executor=self.executor,
            inp_path=inp_path,
            operations=operations,
            target_filename=target_filename,
            job_name=job_name,
            project_context=project_context,
            timeout=timeout,
            run_id=run_id,
            overwrite=overwrite,
            odb_validator=odb_validator,
            rollback_on_solver_failure=rollback_on_solver_failure,
            require_verified_odb=require_verified_odb,
            generate_report=generate_report,
            report_title=report_title,
            deliverables_dir=deliverables_dir,
            requirements=requirements,
            include_animation=include_animation,
            launcher=eff_launcher,
        )

    def postprocess_user_odb(
        self,
        odb_path: Any,
        requirements: Sequence[Any] = (),
        project_context: Optional[Any] = None,
        run_id: Optional[str] = None,
        timeout_seconds: int = 120,
    ) -> Dict[str, Any]:
        """Perform strictly read-only postprocessing and metric extraction on a user-provided .odb."""
        from .execution.input_modes import postprocess_user_odb
        return postprocess_user_odb(
            odb_path=odb_path,
            project_context=project_context,
            requirements=requirements,
            run_id=run_id,
            timeout_seconds=timeout_seconds,
        )

    def prepare_user_cae(
        self,
        cae_path: Any,
        project_context: Optional[Any] = None,
        target_filename: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Open and prepare an authentic working copy of a user-provided .cae database."""
        from .execution.input_modes import open_user_cae_working_copy
        return open_user_cae_working_copy(
            cae_path=cae_path,
            project_context=project_context,
            executor=self.executor,
            target_filename=target_filename,
            overwrite=overwrite,
        )

    def extract_result_intelligence(
        self,
        run: Any,
        intent: Optional[Any] = None,
        capability: Optional[Any] = None,
        output_dir: Optional[str] = None,
    ) -> Tuple[Any, Tuple[Any, ...]]:
        """Extract spatial hotspots, response curves, and derived engineering metrics."""
        from .contracts.result_intelligence import ResultIntelligenceBundle, SpatialHotspot, XYCurveData
        from .results.derived_metrics import calculate_derived_metrics
        from .results.history_extraction import extract_history_curve
        from .results.spatial_hotspots import extract_spatial_hotspots
        from .visualization.engine import render_hotspots_svg, render_xy_curve_svg, save_chart_figure

        out_dir = output_dir or getattr(run, "work_dir", None)
        if not out_dir:
            from .paths import resolve_deliverables_root
            out_dir = str(resolve_deliverables_root())
        os.makedirs(out_dir, exist_ok=True)

        job_name = getattr(run, "job_name", "Job") or "Job"
        metrics = getattr(run, "metrics", ()) or ()
        primary_metrics: Dict[str, float] = {}
        for m in metrics:
            m_name = getattr(m, "name", None) or (m.get("name") if isinstance(m, dict) else str(m))
            m_val = getattr(m, "value", None) if hasattr(m, "value") else (m.get("value") if isinstance(m, dict) else None)
            if m_name and isinstance(m_val, (int, float)):
                primary_metrics[m_name] = float(m_val)
            v_key = getattr(m, "value_key", None) or (m.get("value_key") if isinstance(m, dict) else None)
            if not v_key:
                m_meta = getattr(m, "metadata", {}) or (m.get("metadata", {}) if isinstance(m, dict) else {})
                if isinstance(m_meta, dict):
                    v_key = m_meta.get("value_key")
            if v_key and isinstance(m_val, (int, float)):
                primary_metrics[v_key] = float(m_val)

        # 1. Stress / Yield / Force extraction for derived metrics
        max_stress = None
        for k in ("max_mises", "S_Mises", "MISES", "max_stress", "S"):
            if k in primary_metrics:
                max_stress = primary_metrics[k]
                break

        yield_strength = None
        material_name = "Steel"
        mats = []
        if intent:
            if getattr(intent, "materials", None):
                mats.extend(intent.materials)
            if getattr(intent, "material", None):
                mats.append(intent.material)

        from .reasoning.material_catalog import resolve_material_to_definition
        for mat in mats:
            mat_def = resolve_material_to_definition(mat, fail_closed=False)
            if mat_def is not None:
                material_name = mat_def.name
                if mat_def.plastic and mat_def.plastic.yield_stress:
                    yield_strength = float(mat_def.plastic.yield_stress)
                    break
                elif mat_def.metadata.get("yield_strength_mpa"):
                    yield_strength = float(mat_def.metadata["yield_strength_mpa"])
                    break
            if isinstance(mat, dict):
                mat_name = mat.get("name", "")
                if mat_name:
                    material_name = mat_name
                props = mat.get("properties") or mat
                if "yield_strength" in props:
                    yield_strength = float(props["yield_strength"])
                    break
                elif "yield" in props:
                    yield_strength = float(props["yield"])
                    break
            else:
                mat_name = getattr(mat, "name", "") or (mat if isinstance(mat, str) else "")
                if mat_name:
                    material_name = mat_name
                props = getattr(mat, "properties", {}) or {}
                if "yield_strength" in props:
                    yield_strength = float(props["yield_strength"])
                    break
                elif "yield" in props:
                    yield_strength = float(props["yield"])
                    break

        # In strict engineering production, do not heuristically invent yield strength
        # based merely on substrings in the material name unless explicitly provided.
        # If yield_strength remains None, downstream derived metrics report "未评估 / 证据不足"
        # instead of fabricating synthetic safety factor numbers.

        applied_force = None
        if intent and getattr(intent, "loads", None):
            tot_mag = 0.0
            for ld in intent.loads:
                if isinstance(ld, dict):
                    mag = ld.get("magnitude", ld.get("value", 0.0)) or 0.0
                else:
                    mag = getattr(ld, "magnitude", getattr(ld, "value", 0.0)) or 0.0
                tot_mag += abs(float(mag))
            if tot_mag > 0:
                applied_force = tot_mag

        extraction_diagnostics: Dict[str, str] = {}

        reaction_force = None
        for k in ("RF2", "RF", "RF_mag", "reaction_force"):
            if k in primary_metrics:
                reaction_force = abs(primary_metrics[k])
                break

        # 2. ODB inspection for spatial hotspots, history curves, and reaction summation
        odb_path = getattr(run, "odb_path", None)
        if not odb_path and hasattr(run, "metadata") and isinstance(run.metadata, dict):
            out_files = run.metadata.get("output_files") or {}
            odb_path = out_files.get("odb") or run.metadata.get("odb_path")

        if reaction_force is None and odb_path and os.path.exists(odb_path):
            try:
                from odbAccess import openOdb
                _odb = openOdb(path=odb_path, readOnly=True)
                _frame = _odb.steps.values()[-1].frames[-1]
                if 'RF' in _frame.fieldOutputs:
                    rf_fld = _frame.fieldOutputs['RF']
                    tot_rf2 = sum(float(val.data[1]) for val in rf_fld.values if hasattr(val, 'data') and len(val.data) > 1)
                    if abs(tot_rf2) > 1e-6:
                        reaction_force = abs(tot_rf2)
                        primary_metrics["RF2"] = tot_rf2
                        extraction_diagnostics["RF"] = "EXTRACTED"
                    else:
                        extraction_diagnostics["RF"] = "UNAVAILABLE: RF sum below 1e-6 threshold"
                else:
                    extraction_diagnostics["RF"] = "UNAVAILABLE: fieldOutput 'RF' not present in frame"
                _odb.close()
            except Exception as rf_err:
                extraction_diagnostics["RF"] = f"UNAVAILABLE: {type(rf_err).__name__}: {rf_err}"

        hotspots_list: List[SpatialHotspot] = []
        curves_list: List[XYCurveData] = []
        figures: List[Any] = []

        if odb_path and os.path.exists(odb_path) and hasattr(self, "executor") and self.executor:
            try:
                hotspots = extract_spatial_hotspots(
                    self.executor,
                    odb_path=odb_path,
                    field_name="S",
                    component="Mises",
                    top_k=5,
                )
                hotspots_list.extend(hotspots)
                if hotspots_list:
                    svg_h = render_hotspots_svg(hotspots_list)
                    fig_h_path = os.path.join(out_dir, f"{job_name}_hotspots.svg")
                    fig_h = save_chart_figure(
                        svg_content=svg_h,
                        output_path=fig_h_path,
                        caption=f"Top-{len(hotspots_list)} Mises Stress Hotspots ({job_name})",
                        kind="spatial_hotspots",
                    )
                    figures.append(fig_h)
                    extraction_diagnostics["hotspots"] = f"EXTRACTED ({len(hotspots_list)} points)"
                else:
                    extraction_diagnostics["hotspots"] = "UNAVAILABLE: No hotspots found"
            except Exception as hs_err:
                extraction_diagnostics["hotspots"] = f"UNAVAILABLE: {type(hs_err).__name__}: {hs_err}"

            # Try extracting typical energy curves if available
            for var in ("ALLSE", "ALLIE", "ETOTAL", "ALLKE"):
                try:
                    c = extract_history_curve(
                        self.executor,
                        odb_path=odb_path,
                        variable_name=var,
                    )
                    if c.point_count > 0:
                        curves_list.append(c)
                        svg_c = render_xy_curve_svg(c)
                        fig_c_path = os.path.join(out_dir, f"{job_name}_{var}.svg")
                        fig_c = save_chart_figure(
                            svg_content=svg_c,
                            output_path=fig_c_path,
                            caption=f"{var} Response History ({job_name})",
                            kind="xy_curve",
                        )
                        figures.append(fig_c)
                        extraction_diagnostics[f"history_curve_{var}"] = f"EXTRACTED ({c.point_count} points)"
                    else:
                        extraction_diagnostics[f"history_curve_{var}"] = "UNAVAILABLE: Zero points in history region"
                except Exception as hc_err:
                    extraction_diagnostics[f"history_curve_{var}"] = f"UNAVAILABLE: {type(hc_err).__name__}: {hc_err}"

        etotal_curve = next((c for c in curves_list if c.curve_name.startswith("ETOTAL")), None)
        allie_curve = next((c for c in curves_list if c.curve_name.startswith("ALLIE")), None)
        allke_curve = next((c for c in curves_list if c.curve_name.startswith("ALLKE")), None)

        derived_metrics = calculate_derived_metrics(
            applied_load=applied_force,
            reaction_load=reaction_force,
            etotal_data=etotal_curve,
            allie_data=allie_curve,
            allke_data=allke_curve,
            max_stress=max_stress,
            yield_strength=yield_strength,
            material_name=material_name,
        )

        bundle = ResultIntelligenceBundle(
            primary_metrics=primary_metrics,
            hotspots=tuple(hotspots_list),
            curves=tuple(curves_list),
            derived_metrics=derived_metrics,
            figure_paths=tuple(f.path for f in figures),
            metadata={
                "job_name": job_name,
                "odb_path": odb_path,
                "extraction_diagnostics": extraction_diagnostics,
            },
        )
        return bundle, tuple(figures)

    def plan_outputs(self, criteria=(), outputs=(), postprocess_profile=None):
        from .planning.output import plan_outputs
        return plan_outputs(criteria, outputs, postprocess_profile=postprocess_profile)

    def analysis_run(self, model_name, job_name, odb_path=None, criteria=(), result_values=None,
                     numerical_verification=None, engineering_checks=None,
                     mesh_quality=None, mesh_convergence=None, fatigue=None,
                     contact_diagnostics=None, sensitivity=None, uncertainty=None,
                     engineering_intent=None, postprocess_profile=None,
                     action_plan=(), environment=None, timeout=3600, workdir=None,
                     require_production=None, project_context=None):
        from .execution.analysis_run import AnalysisRunner
        cname = getattr(self.executor, "__class__", None).__name__ or ""
        is_test_double = any(token in cname for token in ("Mock", "Fake", "Stub", "Dummy", "OdbBackedExecutor")) or \
                         getattr(self.executor, "_is_mock", False)
        if require_production is None:
            require_production = (self.mode == "production" and not is_test_double)
        return AnalysisRunner(self.executor).run(
            model_name, job_name, odb_path=odb_path, criteria=criteria,
            result_values=result_values, numerical_verification=numerical_verification,
            engineering_checks=engineering_checks, mesh_quality=mesh_quality,
            mesh_convergence=mesh_convergence, fatigue=fatigue,
            contact_diagnostics=contact_diagnostics, sensitivity=sensitivity,
            uncertainty=uncertainty, engineering_intent=engineering_intent,
            postprocess_profile=postprocess_profile, action_plan=action_plan,
            environment=environment, timeout=timeout, workdir=workdir,
            require_production=require_production, project_context=project_context)

    def submit(self, job_name, wait=False):
        from .execution.jobs import JobController
        return JobController(self.executor).submit(job_name, wait=wait)

    def inspect_odb(self, path):
        from .execution.odb import inspect_odb
        return summarize_odb(inspect_odb(self.executor, path))

    def _render_diagnostic_html(self, title, diag_lines):
        """Bannered HTML draft. Not a formal report.html."""
        import html as html_lib
        body = "".join(
            "<p>%s</p>" % html_lib.escape(line)
            for line in diag_lines
            if line is not None
        )
        return (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            "<title>%s</title></head><body>"
            "<div class=\"diagnostic-banner\">"
            "DIAGNOSTIC NON-DELIVERABLE DRAFT. Not an official engineering report. "
            "禁止作为正式工程报告交付。"
            "</div><h1>%s</h1>%s</body></html>"
        ) % (html_lib.escape(title), html_lib.escape(title), body)

    def _write_diagnostic_html(self, out_dir, html_text):
        """Write only report.diagnostic.html. Never create or replace report.html."""
        if not out_dir or not html_text:
            return None
        target_dir = Path(out_dir)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            draft = target_dir / "report.diagnostic.html"
            draft.write_text(html_text, encoding="utf-8")
            return draft
        except Exception:
            return None

    def _load_plan_inp_text(self, plan, workdir):
        from .diagnostics.solver_patterns import read_job_inp_text
        job_name = getattr(plan, "job_name", None)
        text, _source = read_job_inp_text(workdir=workdir, job_name=job_name)
        return text

    def solve_requirement(
        self,
        requirement,
        model_name=None,
        part_name=None,
        job_name=None,
        geometry=None,
        material=None,
        mesh=None,
        grounded_regions=None,
        timeout=3600,
        submit_job=True,
        router_strict=False,
        odb_path=None,
        result_values=None,
        enable_self_healing=True,
        max_healing_attempts=2,
        **kwargs,
    ):
        """End-to-end engineering requirement solver (P1.0 Product Main Entry).

        Takes natural language prompts or structured EngineeringIntent instances,
        routes them deterministically through the 20-L4 physical capabilities,
        compiles execution plans, applies preflight gates, executes through the canonical
        AnalysisRunner, and produces an auditable EngineeringTaskResult with markdown report.
        """
        from .contracts.capability import resolve_capability
        from .contracts.intent import EngineeringIntent
        from .contracts.task import EngineeringTaskResult, TaskStatus
        from .execution.analysis_run import AnalysisRunState
        from .planning.compiler import compile_engineering_intent
        from .reporting.renderer import render_html, render_markdown
        from .typesafe_intent import JevIntentRouter
        from .validation.preflight import preflight_plan

        # Defense-in-depth: Prohibit direct injection of internal verification objects
        # at the product entry level to guarantee zero-fabrication single-exit integrity.
        forbidden_injections = (
            "numerical_verification",
            "engineering_checks",
            "mesh_quality",
            "mesh_convergence",
            "contact_diagnostics",
            "sensitivity",
            "uncertainty",
            "connector_kinematics",
            "fmbd_dynamics",
        )
        found_injections = [k for k in forbidden_injections if k in kwargs]
        if found_injections and not kwargs.pop("_allow_test_injections", False):
            return EngineeringTaskResult(
                status=TaskStatus.BLOCKED,
                errors=(
                    f"Direct injection of internal verification objects {found_injections} "
                    "is strictly forbidden at the product entry level.",
                ),
                summary_card={
                    "status": "INJECTION_BLOCKED",
                    "forbidden_keys": found_injections,
                },
            )

        # 1. Natural Language or Structured Intent Routing
        from .typesafe_intent import DraftEngineeringIntent

        intent = None
        if isinstance(requirement, DraftEngineeringIntent) or (
            hasattr(requirement, "is_executable") and not getattr(requirement, "is_executable", True)
        ):
            return EngineeringTaskResult(
                status=TaskStatus.BLOCKED,
                errors=(
                    "Draft engineering intents (is_executable=False) are non-executable "
                    "and strictly blocked from solver execution.",
                ),
                summary_card={
                    "status": "DRAFT_INTENT_BLOCKED",
                    "reason": "non_executable_draft_intent",
                },
            )
        elif isinstance(requirement, str):
            jev_mode = kwargs.pop("jev_mode", None)
            context = kwargs.pop("context", None)
            router = JevIntentRouter(mode=jev_mode)
            routing_res = router.route(requirement, context=context)
            if routing_res.status == "NEEDS_CLARIFICATION":
                return EngineeringTaskResult(
                    status=TaskStatus.NEEDS_CLARIFICATION,
                    clarification_prompt=routing_res.clarification_prompt,
                    summary_card={
                        "status": "NEEDS_CLARIFICATION",
                        "missing_requirements": routing_res.missing_requirements,
                        "clarification_prompt": routing_res.clarification_prompt,
                    },
                    metadata={"missing_requirements": routing_res.missing_requirements},
                )
            elif routing_res.status != "ROUTED":
                return EngineeringTaskResult(
                    status=TaskStatus.BLOCKED,
                    errors=(
                        routing_res.clarification_prompt
                        or f"Intent routing failed with status: {routing_res.status}",
                    ),
                    summary_card={
                        "status": "ROUTING_BLOCKED",
                        "missing_requirements": routing_res.missing_requirements,
                    },
                    metadata={"missing_requirements": routing_res.missing_requirements},
                )
            intent = routing_res.intent
            kwargs.setdefault("environment", {})
            if not isinstance(kwargs.get("environment"), dict):
                kwargs["environment"] = {}
            kwargs["environment"] = dict(kwargs["environment"])
            kwargs["environment"].update({
                "agent_entry": "solve_requirement",
                "jev_routed": True,
                "jev_mode": getattr(router, "mode", jev_mode) or "offline",
                "requirement_kind": "natural_language",
            })
        elif isinstance(requirement, EngineeringIntent):
            if not getattr(requirement, "is_executable", True):
                return EngineeringTaskResult(
                    status=TaskStatus.BLOCKED,
                    errors=(
                        "EngineeringIntent has is_executable=False and is strictly blocked "
                        "from solver execution.",
                    ),
                    summary_card={
                        "status": "DRAFT_INTENT_BLOCKED",
                        "reason": "non_executable_intent",
                    },
                )
            intent = requirement
            kwargs.setdefault("environment", {})
            if not isinstance(kwargs.get("environment"), dict):
                kwargs["environment"] = {}
            kwargs["environment"] = dict(kwargs["environment"])
            kwargs["environment"].update({
                "agent_entry": "solve_requirement",
                "jev_routed": False,
                "requirement_kind": "engineering_intent",
            })
        else:
            raise TypeError(
                f"requirement must be str or EngineeringIntent, got {type(requirement).__name__}"
            )

        if intent is None:
            return EngineeringTaskResult(
                status=TaskStatus.FAILED,
                errors=("Failed to extract or resolve engineering intent.",),
            )

        # 2. Capability Resolution & Physical Profile Association
        capability = resolve_capability(intent)
        if not capability.is_supported:
            return EngineeringTaskResult(
                status=TaskStatus.UNSUPPORTED,
                intent=intent,
                capability=capability,
                errors=(capability.reason,),
                summary_card={
                    "status": "UNSUPPORTED",
                    "capability_id": capability.capability_id,
                    "reason": capability.reason,
                },
            )

        # 2.5. P1.2 Intent Reasoning, Parameter Completion & Engineering Plausibility Gate
        from .contracts.intent_reasoning import ReasoningStatus
        from .reasoning.engine import IntentReasoningEngine

        reasoning_res = IntentReasoningEngine.reason(
            intent=intent,
            geometry=geometry,
            material=material,
            mesh=mesh,
            grounded_regions=grounded_regions,
            strict_hitl=kwargs.get("strict_hitl", True),
        )

        if not reasoning_res.is_executable:
            reasoning_task_status = (
                TaskStatus.NEEDS_CLARIFICATION
                if reasoning_res.status == ReasoningStatus.NEEDS_CLARIFICATION
                else TaskStatus.BLOCKED
            )
            card_status = reasoning_res.status.value
            if any("missing geometry" in str(b) for b in reasoning_res.blockers):
                card_status = "COMPILATION_BLOCKED"

            return EngineeringTaskResult(
                status=reasoning_task_status,
                intent=intent,
                capability=capability,
                clarification_prompt=reasoning_res.clarification_prompt,
                errors=reasoning_res.blockers,
                summary_card={
                    "status": card_status,
                    "blockers": list(reasoning_res.blockers),
                    "clarification_prompt": reasoning_res.clarification_prompt,
                    "inferences": [inf.to_dict() for inf in reasoning_res.inferences],
                    "plausibility_checks": [c.to_dict() for c in reasoning_res.plausibility_checks],
                },
                metadata={
                    "reasoning_summary": reasoning_res.to_summary(),
                },
            )

        intent = reasoning_res.enriched_intent or intent
        effective_mesh = mesh or reasoning_res.inferred_mesh
        effective_material = material or reasoning_res.inferred_material

        from .reasoning.material_catalog import resolve_material_to_definition
        effective_mat_def = resolve_material_to_definition(
            effective_material,
            unit_system=intent.unit_system or "MM_N_MPA",
            fail_closed=False,
        )

        # 3. Intent Compilation to Action Plan (Fail-closed on missing geometry/material)
        try:
            plan = compile_engineering_intent(
                intent=intent,
                model_name=model_name,
                part_name=part_name,
                job_name=job_name,
                geometry=geometry,
                material=effective_mat_def or effective_material,
                mesh=effective_mesh,
                grounded_regions=grounded_regions,
                submit_job=submit_job,
            )
        except (ValueError, TypeError) as exc:
            return EngineeringTaskResult(
                status=TaskStatus.BLOCKED,
                intent=intent,
                capability=capability,
                errors=(str(exc),),
                summary_card={
                    "status": "COMPILATION_BLOCKED",
                    "error": str(exc),
                },
            )

        # 4. Mandatory Preflight Gate
        preflight_res = preflight_plan(plan.actions)
        if not preflight_res.passed:
            blocker_msgs = tuple(
                b.message if hasattr(b, "message") else str(b)
                for b in preflight_res.blockers
            )
            return EngineeringTaskResult(
                status=TaskStatus.BLOCKED,
                intent=intent,
                capability=capability,
                plan=plan,
                errors=blocker_msgs,
                summary_card={
                    "status": "PREFLIGHT_BLOCKED",
                    "blockers": list(blocker_msgs),
                },
            )

        # 4.5. Production Mode Isolation Gate (REQ-ISO-003):
        # Validate workspace isolation BEFORE applying plan actions or invoking CAE commands.
        project_context = kwargs.pop("project_context", None)
        cname = getattr(self.executor, "__class__", None).__name__ or ""
        is_test_double = any(token in cname for token in ("Mock", "Fake", "Stub", "Dummy", "OdbBackedExecutor")) or \
                         getattr(self.executor, "_is_mock", False)
        default_prod = (self.mode == "production" and not is_test_double)
        prod_req = kwargs.pop("require_production", default_prod)
        target_workdir = kwargs.pop("workdir", None)

        # Enforce strict project_context containment on explicit workdir (REQ-ISO-002, REQ-ISO-003)
        if project_context is not None and target_workdir:
            cand_workdir = Path(target_workdir).resolve()
            project_context.assert_within_subdir(cand_workdir, project_context.solver_dir)
            target_workdir = str(cand_workdir)

        # Strict Production Mode Isolation (REQ-ISO-003):
        # In real production mode, solver execution inside the core repository is strictly forbidden.
        if prod_req:
            if project_context is None:
                from .paths import get_repo_root, resolve_runs_root, resolve_project_root, create_external_project_context
                ext_root = resolve_project_root(fail_closed=False)
                if ext_root:
                    project_context = create_external_project_context(ext_root, project_name=plan.job_name or "Project")
                elif target_workdir:
                    repo_r = get_repo_root().resolve()
                    cand_target = Path(target_workdir).resolve()
                    if cand_target == repo_r or cand_target.is_relative_to(repo_r):
                        raise PermissionError(
                            f"Production execution blocked (REQ-ISO-003): Target workdir '{cand_target}' "
                            f"resides inside the core repository '{repo_r}'. Production runs must use an external project context."
                        )
                    # Automatically establish project context rooted at external workdir
                    proj_root = cand_target.parent if cand_target.name in ("solver", "working", "input", "delivery", "evidence") else cand_target
                    project_context = create_external_project_context(
                        proj_root,
                        project_name=plan.job_name or "Project",
                        enforce_outside_repo=False if is_test_double else True,
                    )
                    # Ensure target_workdir satisfies solver_dir boundary
                    if not cand_target.is_relative_to(project_context.solver_dir.resolve()):
                        target_workdir = str(project_context.create_run_solver_dir(plan.job_name or "run"))
                else:
                    runs_root = resolve_runs_root().resolve()
                    repo_r = get_repo_root().resolve()
                    if runs_root == repo_r or runs_root.is_relative_to(repo_r):
                        raise RuntimeError(
                            "[Production Guard] Execution in production mode requires a valid ExternalProjectContext. "
                            "Silent fallback to repository-internal runs/ is strictly prohibited."
                        )

        # 5. Apply Plan Actions to CAE Environment
        self.apply_plan(plan)

        # 6. Single Canonical Production Outlet: AnalysisRunner
        criteria = kwargs.pop("criteria", None) or intent.acceptance_criteria or ()
        run = self.analysis_run(
            model_name=plan.model_name,
            job_name=plan.job_name,
            odb_path=odb_path,
            criteria=criteria,
            result_values=result_values,
            fatigue=intent.fatigue,
            engineering_intent=intent,
            postprocess_profile=capability.profile,
            action_plan=plan.actions,
            timeout=timeout,
            workdir=target_workdir,
            require_production=prod_req,
            project_context=project_context,
            **kwargs,
        )

        # 6.5. P1.4 Automated Solver Failure Diagnostics & Controlled Self-Healing
        run_state = getattr(run, "state", None)
        run_state_val = getattr(run_state, "value", str(run_state))
        initial_eng_status = getattr(run, "engineering_status", "EXECUTED")
        initial_acc_passed = bool(getattr(run, "acceptance_passed", False))
        initial_ok = (
            (run_state == AnalysisRunState.ACCEPTED or str(run_state_val).lower() == "accepted")
            and initial_eng_status in ("ACCEPTED", "RESULT_VALID")
            and initial_acc_passed
        )

        healing_result = None
        if not initial_ok and enable_self_healing and odb_path is None and result_values is None:
            from .diagnostics.orchestrator import SelfHealingOrchestrator
            heal_kwargs = dict(kwargs)
            heal_workdir = heal_kwargs.pop("workdir", getattr(run, "work_dir", None))
            if not heal_workdir:
                from .paths import resolve_runs_root
                heal_workdir = str(resolve_runs_root() / getattr(run, "id", "heal_scratch"))
            run, healing_result = SelfHealingOrchestrator.attempt_healing(
                agent=self,
                failed_run=run,
                intent=intent,
                capability=capability,
                plan=plan,
                geometry=geometry,
                material=effective_material,
                mesh=effective_mesh,
                grounded_regions=grounded_regions,
                max_attempts=max_healing_attempts,
                timeout=timeout,
                workdir=heal_workdir,
                criteria=criteria,
                postprocess_profile=capability.profile,
                **heal_kwargs,
            )

        # 7. Summary Card & Markdown Engineering Report
        metrics = getattr(run, "metrics", ()) or ()
        acceptance = getattr(run, "acceptance", None)

        metric_dict = {}
        for m in metrics:
            m_name = getattr(m, "name", None) or (m.get("name") if isinstance(m, dict) else str(m))
            m_val = getattr(m, "value", None) if hasattr(m, "value") else (m.get("value") if isinstance(m, dict) else None)
            if m_name:
                metric_dict[m_name] = m_val
            v_key = getattr(m, "value_key", None) or (m.get("value_key") if isinstance(m, dict) else None)
            if not v_key:
                m_meta = getattr(m, "metadata", {}) or (m.get("metadata", {}) if isinstance(m, dict) else {})
                if isinstance(m_meta, dict):
                    v_key = m_meta.get("value_key")
            if v_key:
                metric_dict[v_key] = m_val

        # 7a. Result Intelligence & Graphical Assets (P1.3 Delivery)
        if project_context is not None:
            out_dir = str(project_context.delivery_dir)
        else:
            out_dir = target_workdir or (os.path.dirname(run.odb_path) if getattr(run, "odb_path", None) else None)
            if not out_dir:
                from .paths import resolve_deliverables_root
                out_dir = str(resolve_deliverables_root())
        ri_bundle, generated_figures = self.extract_result_intelligence(
            run=run,
            intent=intent,
            capability=capability,
            output_dir=out_dir,
        )

        # 7b. Automatic Engineering Figure Selection
        from .reporting.figure_selector import select_engineering_figures
        top_hotspot_info = None
        if ri_bundle and getattr(ri_bundle, "hotspots", None):
            top_h = ri_bundle.hotspots[0]
            top_hotspot_info = {
                "element_id": getattr(top_h, "element_label", None),
                "node_id": getattr(top_h, "node_label", None),
                "coordinates": getattr(top_h, "coordinates", None),
            }

        eff_odb_hash = None
        if run and getattr(run, "provenance", None):
            eff_odb_hash = getattr(run.provenance, "odb_hash", None)

        req_text = str(requirement if isinstance(requirement, str) else getattr(intent, "description", "") or "")
        req_lower = req_text.lower()
        wants_mesh_kw = any(w in req_lower for w in ("网格", "mesh", "离散", "discretization"))
        wants_anim_kw = any(w in req_lower for w in ("动图", "动画", "anim", "时程", "gif", "演化"))
        physics_domain_lower = str(capability.physics_domain or "").lower()
        intent_kind_lower = str(getattr(intent, "kind", "") or "").lower()
        intent_desc_lower = str(getattr(intent, "description", "") or "").lower()
        is_dynamic_case = (
            any(k in physics_domain_lower for k in ("dynamic", "transient", "mbd", "explicit", "vibration"))
            or any(k in intent_kind_lower for k in ("dynamic", "transient", "mbd", "explicit", "vibration"))
            or any(k in intent_desc_lower for k in ("dynamic", "mbd", "multibody", "瞬态", "动力学", "多体"))
        )
        req_prod = bool(kwargs.get("require_production", False))
        inc_mesh = bool(kwargs.get("include_mesh", req_prod or wants_mesh_kw))
        inc_anim = bool(kwargs.get("include_animation", req_prod or wants_anim_kw or is_dynamic_case))

        figure_selection = select_engineering_figures(
            intent=intent,
            physics_domain=capability.physics_domain,
            results_info=metric_dict,
            existing_figures=generated_figures,
            run_id=getattr(run, "id", None),
            odb_path=getattr(run, "odb_path", None),
            input_hash=getattr(run.provenance, "input_hash", "") if getattr(run, "provenance", None) else "",
            odb_hash=eff_odb_hash,
            hotspot_info=top_hotspot_info,
            output_dir=out_dir,
            include_mesh=inc_mesh,
            include_animation=inc_anim,
        )

        all_figures = list(generated_figures) + list(figure_selection.reused_figures)
        report_title = f"Engineering Analysis Report: {intent.description or plan.model_name}"

        eng_status = getattr(run, "engineering_status", "EXECUTED")
        run_state = getattr(run, "state", None)
        run_state_val = getattr(run_state, "value", str(run_state))
        # Strict single-exit acceptance contract:
        # TaskStatus is COMPLETED if and only if:
        # 1. run.state == AnalysisRunState.ACCEPTED
        # 2. run.engineering_status in ("ACCEPTED", "RESULT_VALID")
        # 3. run.acceptance_passed is True
        # This strictly prevents external_input, missing ODB, or unverified runs from ever reaching COMPLETED.
        is_completed = (
            (run_state == AnalysisRunState.ACCEPTED or str(run_state_val).lower() == "accepted")
            and eng_status in ("ACCEPTED", "RESULT_VALID")
            and bool(getattr(run, "acceptance_passed", False))
        )

        # P1-D: Causal link between required criteria, extraction diagnostics, and delivery authorization.
        # If any acceptance criterion is explicitly marked as required (required=True),
        # its metric must exist in metric_dict as a valid finite numeric value, and its extraction must not be UNAVAILABLE or FAILED.
        if intent and getattr(intent, "acceptance_criteria", None):
            diag_map = (
                ri_bundle.metadata.get("extraction_diagnostics", {})
                if ri_bundle and hasattr(ri_bundle, "metadata")
                else {}
            )
            field_aliases = {
                "S": ("max_mises", "s_mises", "mises", "max_stress", "s"),
                "U": ("max_displacement", "u_magnitude", "displacement", "u"),
                "RF": ("reaction_force", "rf", "rf2", "rf_mag", "total_rf"),
                "CPRESS": ("max_cpress", "cpress", "contact_pressure"),
                "NT": ("max_temperature", "temperature", "nt", "nt11"),
            }
            import math
            for c in intent.acceptance_criteria:
                is_req = c.get("required") if isinstance(c, dict) else getattr(c, "required", False)
                if not is_req:
                    continue
                c_name = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
                c_key = c.get("value_key") if isinstance(c, dict) else getattr(c, "value_key", None)
                c_field = c.get("field") if isinstance(c, dict) else getattr(c, "field", None)

                # Build candidate keys set
                candidate_keys = set()
                if c_name:
                    candidate_keys.add(str(c_name))
                    candidate_keys.add(str(c_name).lower())
                if c_key:
                    candidate_keys.add(str(c_key))
                    candidate_keys.add(str(c_key).lower())
                if c_field:
                    f_upper = str(c_field).upper()
                    candidate_keys.add(f_upper)
                    for alias in field_aliases.get(f_upper, ()):
                        candidate_keys.add(alias)
                        candidate_keys.add(alias.upper())

                found_valid_val = False
                for k in candidate_keys:
                    if k in metric_dict:
                        v = metric_dict[k]
                        # Disallow bool (bool subclasses int in Python) and require finite number
                        if not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(float(v)):
                            found_valid_val = True
                            break

                # Also inspect extraction diagnostics
                diag_failed = False
                for k in candidate_keys:
                    if k in diag_map:
                        diag_entry = diag_map[k]
                        msg = ""
                        if isinstance(diag_entry, dict):
                            msg = str(diag_entry.get("status") or diag_entry.get("error") or diag_entry.get("reason") or diag_entry.get("detail") or "").upper()
                        else:
                            msg = str(diag_entry).upper()
                        if any(token in msg for token in ("UNAVAILABLE", "FAILED", "MISSING", "ERROR", "INVALID", "BLOCKED")):
                            diag_failed = True
                            break

                if not found_valid_val or diag_failed:
                    is_completed = False
                    eng_status = "RESULT_INVALID"
                    break

        # Determine whether this run qualifies for official authoritative delivery
        is_official = bool(prod_req and is_completed and acceptance and getattr(acceptance, "deliverable", False))

        deterministic_delivery_card = None
        delivery_block_error = None
        report_md = None
        report_html_str = None

        if is_official:
            try:
                from .reporting.pipeline import DeterministicReportPipeline
                pipeline = DeterministicReportPipeline()
                materials_payload = []
                final_mat_def = getattr(plan, "material", None) or effective_mat_def
                if final_mat_def is not None:
                    materials_payload.append(final_mat_def.to_dict())

                # Build grounded mesh discretization and quality payload
                mesh_extraction_error = None
                actual_mesh_metrics = (getattr(run, "verification", {}) or {}).get("mesh_metrics") or {}
                if not actual_mesh_metrics and getattr(run, "odb_path", None):
                    try:
                        from .execution.solver import extract_authentic_odb_mesh_metrics
                        actual_mesh_metrics = extract_authentic_odb_mesh_metrics(
                            run.odb_path,
                            launcher_cmd=getattr(self.executor, "launcher", None),
                        )
                    except Exception as exc:
                        mesh_extraction_error = str(exc)
                        actual_mesh_metrics = {}

                eff_mesh_spec = getattr(plan, "mesh", None) or effective_mesh
                req_global_size = getattr(eff_mesh_spec, "global_size", 2.5) if eff_mesh_spec else 2.5
                req_elem_type = getattr(eff_mesh_spec, "element_type", "C3D8R") if eff_mesh_spec else "C3D8R"
                local_seeds_tuple = getattr(eff_mesh_spec, "local_seeds", ()) or ()

                actual_total_elements = actual_mesh_metrics.get("total_elements")
                actual_total_nodes = actual_mesh_metrics.get("total_nodes")
                actual_elem_types = actual_mesh_metrics.get("element_types") or {}

                if actual_elem_types:
                    actual_elem_type_display = ", ".join(f"{k} ({v})" for k, v in sorted(actual_elem_types.items()))
                elif actual_total_elements is not None:
                    actual_elem_type_display = "INCOMPLETE"
                else:
                    actual_elem_type_display = "UNAVAILABLE"

                disc_data = {
                    "requested_seed_size": float(req_global_size),
                    "requested_element_type": req_elem_type,
                    "seed_size": float(req_global_size),
                    "total_elements": actual_total_elements if actual_total_elements is not None else "UNAVAILABLE",
                    "total_nodes": actual_total_nodes if actual_total_nodes is not None else "UNAVAILABLE",
                    "actual_element_type": actual_elem_type_display,
                    "element_type": actual_elem_type_display,
                    "strategy": "局部种子约束 (Local Edge Refinement)" if local_seeds_tuple else "全局均匀布种 (Global Unconstrained)",
                    "local_refinements": len(local_seeds_tuple),
                    "extraction_status": "AUTHENTIC" if actual_total_elements is not None else "FAILED_OR_MISSING",
                }
                if mesh_extraction_error:
                    disc_data["extraction_error"] = mesh_extraction_error

                # Mesh quality gate resolution: must strictly originate from actual mesh quality check
                mq_audit = (getattr(run, "verification", {}) or {}).get("mesh_quality")
                if not mq_audit or not isinstance(mq_audit, dict):
                    mq_audit = (getattr(run, "verification", {}) or {}).get("mesh_gate")

                resolved_gate_status = "NOT_CHECKED"
                if isinstance(mq_audit, dict) and mq_audit.get("gate_status"):
                    raw_status = str(mq_audit["gate_status"]).upper()
                    if "PASS" in raw_status:
                        resolved_gate_status = "PASS"
                    elif "WARN" in raw_status:
                        resolved_gate_status = "WARNING"
                    elif "BLOCK" in raw_status:
                        resolved_gate_status = "BLOCKED"
                    elif "FAIL" in raw_status:
                        resolved_gate_status = "FAIL"
                    else:
                        resolved_gate_status = "NOT_CHECKED"
                else:
                    acc_gates = {}
                    if isinstance(acceptance, dict):
                        acc_gates = acceptance.get("gates") or {}
                    elif hasattr(acceptance, "gates"):
                        acc_gates = getattr(acceptance, "gates") or {}
                    mq_gate_val = acc_gates.get("mesh_quality")
                    if mq_gate_val is not None:
                        val_str = str(mq_gate_val).upper()
                        if val_str == "PASS":
                            resolved_gate_status = "PASS"
                        elif "WARN" in val_str:
                            resolved_gate_status = "WARNING"
                        elif "BLOCK" in val_str:
                            resolved_gate_status = "BLOCKED"
                        elif "FAIL" in val_str:
                            resolved_gate_status = "FAIL"
                        else:
                            resolved_gate_status = "NOT_CHECKED"

                quality_audit_payload = dict(mq_audit) if isinstance(mq_audit, dict) else {}
                quality_audit_payload["gate_status"] = resolved_gate_status

                mesh_info_payload = {
                    "discretization": disc_data,
                    "quality_audit": quality_audit_payload,
                    "total_elements": actual_total_elements if actual_total_elements is not None else "UNAVAILABLE",
                    "total_nodes": actual_total_nodes if actual_total_nodes is not None else "UNAVAILABLE",
                    "element_type": actual_elem_type_display,
                    "seed_size": float(req_global_size),
                }
                if mesh_extraction_error:
                    mesh_info_payload["extraction_error"] = mesh_extraction_error

                issued = getattr(run, "provenance", None)
                odb_for_report = getattr(run, "odb_path", None)
                if issued is not None and odb_for_report and not getattr(issued, "output_hash", None):
                    from .contracts.provenance import attach_delivery_stamp
                    import hashlib
                    odb_file = Path(odb_for_report)
                    if odb_file.is_file():
                        issued = attach_delivery_stamp(issued.replace(
                            output_hash=hashlib.sha256(odb_file.read_bytes()).hexdigest(),
                        ))
                deck_text = (getattr(run, "metadata", None) or {}).get("inp_text")
                if not deck_text:
                    deck_text = self._load_plan_inp_text(plan, target_workdir or getattr(run, "work_dir", None))
                deterministic_delivery_card, _, det_report_data = pipeline.build_and_render(
                    output_dir=Path(out_dir),
                    title=report_title,
                    case_id=plan.job_name,
                    run_id=getattr(run, "id", "RUN-AUTH"),
                    provenance=issued,
                    inp_text=deck_text,
                    model_info={
                        "name": plan.model_name,
                        "material": final_mat_def.name if final_mat_def else "Steel",
                        "standard_reference": final_mat_def.provenance if final_mat_def else "",
                        "max_mises_mpa": metric_dict.get("max_mises") or metric_dict.get("S_Mises"),
                        "max_displacement_mm": metric_dict.get("max_displacement") or metric_dict.get("U_magnitude"),
                        "total_elements": actual_total_elements if actual_total_elements is not None else "UNAVAILABLE",
                        "total_nodes": actual_total_nodes if actual_total_nodes is not None else "UNAVAILABLE",
                        "element_type": actual_elem_type_display,
                    },
                    results_info=[{"metric": k, "value": v} for k, v in metric_dict.items()],
                    acceptance_info=acceptance,
                    visualization_specs=figure_selection.specs,
                    figures=list(figure_selection.reused_figures),
                    materials_info=materials_payload,
                    mesh_info=mesh_info_payload,
                    require_deliverable=True,
                    odb_path=getattr(run, "odb_path", None),
                    input_hash=getattr(run.provenance, "input_hash", "") if getattr(run, "provenance", None) else "",
                    launcher=getattr(self.executor, "launcher", None),
                    result_intelligence=ri_bundle,
                    self_healing=healing_result,
                )
                report_md = render_markdown(det_report_data)
                report_html_str = render_html(det_report_data)
            except Exception as d_exc:
                is_completed = False
                eng_status = "DELIVERY_BLOCKED"
                deterministic_delivery_card = None
                report_md = None
                report_html_str = None
                delivery_block_error = f"Official delivery blocked: {d_exc}"
        else:
            # Non-deliverable diagnostic path. This is not an official deliverable:
            # it never writes report.html and never sets deliverable=True. The
            # diagnostic HTML is a bannered draft so a failed gate is not left as
            # an unmarked Markdown file that can be filed as the CAE report.
            draft_title = f"[DIAGNOSTIC / NON-DELIVERABLE DRAFT] {report_title}"

            diag_lines = [
                f"# {draft_title}\n",
                "> **工程交付警告 (Engineering Delivery Notice)**: "
                "本产物为非正式诊断记录/测试草稿（未通过生产级正式交付管线认证或未签署 Delivery Card），"
                "禁止作为正式工程报告交付。\n",
                "## 1. 任务与求解状态 (Task & Execution Diagnostics)",
                f"- **Task Status**: {'COMPLETED' if is_completed else 'FAILED'}",
                f"- **Engineering Status**: {eng_status}",
                f"- **Acceptance Passed**: {bool(getattr(run, 'acceptance_passed', False))}",
                f"- **Physics Capability**: {getattr(capability, 'capability_id', 'UNKNOWN')} ({getattr(capability, 'physics_domain', 'UNKNOWN')})",
                f"- **Job Name**: {getattr(plan, 'job_name', 'N/A')}",
                f"- **Model Name**: {getattr(plan, 'model_name', 'N/A')}",
                f"- **ODB Path**: {getattr(run, 'odb_path', 'UNAVAILABLE')}\n",
                "## 2. 关键工程指标与验证维度 (Key Metrics & Verification Dimension)",
            ]
            if metric_dict:
                diag_lines.append("| 指标名称 (Metric) | 数值 (Value) |")
                diag_lines.append("| :--- | :--- |")
                for k, v in sorted(metric_dict.items()):
                    diag_lines.append(f"| `{k}` | `{v}` |")
                diag_lines.append("")
            else:
                diag_lines.append("*未提取到有效工程标量指标 (No valid engineering metrics extracted).*\n")

            diag_lines.append("## 3. 验收准则判定 (Acceptance Verdict)")
            if acceptance:
                acc_status = getattr(acceptance, "status", "UNKNOWN")
                diag_lines.append(f"- **Overall Acceptance Status**: `{acc_status}`")
                if hasattr(acceptance, "criteria") and acceptance.criteria:
                    diag_lines.append("| 准则项 (Criterion) | 实测值 (Actual) | 限制值 (Limit) | 判定 (Verdict) |")
                    diag_lines.append("| :--- | :--- | :--- | :--- |")
                    for c in acceptance.criteria:
                        c_name = getattr(c, "name", str(c))
                        c_act = getattr(c, "actual", "N/A")
                        c_op = getattr(c, "operator", "")
                        c_lim = getattr(c, "limit", "N/A")
                        c_pass = "PASS" if getattr(c, "passed", False) else "FAIL"
                        diag_lines.append(f"| {c_name} | {c_act} | {c_op} {c_lim} | {c_pass} |")
                    diag_lines.append("")
                if hasattr(acceptance, "audit_summary") and acceptance.audit_summary:
                    diag_lines.append(f"- **Audit Summary**: {acceptance.audit_summary}\n")
            else:
                diag_lines.append("*未关联验收评定对象 (No acceptance evaluation associated).*\n")

            if ri_bundle:
                diag_lines.append("## 4. 衍生智能与图件资产 (Result Intelligence Diagnostics)")
                hs_count = len(getattr(ri_bundle, "hotspots", ()))
                cv_count = len(getattr(ri_bundle, "curves", ()))
                diag_lines.append(f"- **Hotspots Count**: {hs_count}")
                diag_lines.append(f"- **History Curves Count**: {cv_count}")
                dm = getattr(ri_bundle, "derived_metrics", None)
                if dm and getattr(dm, "safety_factor", None):
                    sf = dm.safety_factor
                    max_s = getattr(sf, "max_stress", "N/A")
                    diag_lines.append(f"- **Nominal Safety Factor (FoS)**: `{sf.factor_of_safety:.2f}` (Yield: `{sf.yield_strength}` MPa, Max Stress: `{max_s}` MPa)")
                diag_lines.append("")

            if healing_result:
                diag_lines.append("## 5. 自愈审计上下文 (Self-Healing Context)")
                is_healed = getattr(healing_result, "healed", False)
                heal_status = "HEALED" if is_healed else getattr(healing_result, "final_status", "UNRESOLVED")
                attempts = getattr(healing_result, "total_attempts", 0)
                diag_lines.append(f"- **Healing Status**: {heal_status}")
                diag_lines.append(f"- **Total Attempts**: {attempts}\n")

            diag_errs = []
            if not is_completed:
                diag_errs.append(f"Engineering status: {eng_status}")
            if delivery_block_error:
                diag_errs.append(delivery_block_error)
            if diag_errs:
                diag_lines.append("## 6. 异常与阻断诊断 (Blockers & Errors)")
                for err in diag_errs:
                    diag_lines.append(f"- ⚠️ {err}")
                diag_lines.append("")

            report_md = "\n".join(diag_lines)
            report_html_str = self._render_diagnostic_html(draft_title, diag_lines)
            self._write_diagnostic_html(out_dir, report_html_str)

        task_status = TaskStatus.COMPLETED if is_completed else TaskStatus.FAILED

        summary_card = {
            "status": task_status.value,
            "model_name": plan.model_name,
            "job_name": plan.job_name,
            "capability_id": capability.capability_id,
            "physics_domain": capability.physics_domain,
            "engineering_status": eng_status,
            "acceptance_passed": getattr(run, "acceptance_passed", False),
            "deliverable": getattr(acceptance, "deliverable", False) if acceptance else False,
            "metrics": metric_dict,
            "reasoning_status": reasoning_res.status.value,
            "inferences": [inf.to_dict() for inf in reasoning_res.inferences],
            "result_intelligence": {
                "hotspot_count": len(ri_bundle.hotspots),
                "curve_count": len(ri_bundle.curves),
                "figure_count": len(all_figures),
                "derived_metrics": ri_bundle.derived_metrics.to_dict() if ri_bundle.derived_metrics else None,
            },
            "figure_selection": {
                "scenario": figure_selection.scenario,
                "specs_count": len(figure_selection.specs),
                "reused_count": len(figure_selection.reused_figures),
                "unavailable_fields": figure_selection.unavailable_fields,
            },
            "delivery_card": deterministic_delivery_card.to_dict() if deterministic_delivery_card else None,
            "self_healing": healing_result.to_dict() if healing_result else None,
        }

        err_list = []
        if not is_completed:
            err_list.append(f"Engineering status: {eng_status}")
            if delivery_block_error:
                err_list.append(delivery_block_error)

        task_metadata = {"self_healing": healing_result.to_dict() if healing_result else None}
        report_meta = getattr(det_report_data, "metadata", None) if "det_report_data" in locals() else None
        if isinstance(report_meta, dict) and report_meta.get("deliverable_authorization"):
            task_metadata["deliverable_authorization"] = report_meta["deliverable_authorization"]
        if not is_official:
            task_metadata["report_kind"] = "diagnostic_draft"
            task_metadata["formal_report_written"] = False
            if out_dir:
                task_metadata["diagnostic_report_path"] = str(Path(out_dir) / "report.diagnostic.html")
        else:
            task_metadata["report_kind"] = "official_html"
            task_metadata["formal_report_written"] = True
        return EngineeringTaskResult(
            status=task_status,
            intent=intent,
            capability=capability,
            plan=plan,
            run=run,
            acceptance=acceptance,
            metrics=metrics,
            summary_card=summary_card,
            report_markdown=report_md,
            report_html=report_html_str,
            result_intelligence=ri_bundle,
            errors=tuple(err_list),
            metadata=task_metadata,
        )
