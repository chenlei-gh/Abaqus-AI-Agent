import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

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

        out_dir = output_dir or getattr(run, "work_dir", None) or os.getcwd()
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

        for mat in mats:
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
                mat_name = getattr(mat, "name", "")
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
                     require_production=None):
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
            require_production=require_production)

    def submit(self, job_name, wait=False):
        from .execution.jobs import JobController
        return JobController(self.executor).submit(job_name, wait=wait)

    def inspect_odb(self, path):
        from .execution.odb import inspect_odb
        return summarize_odb(inspect_odb(self.executor, path))

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
        intent = None
        if isinstance(requirement, str):
            router = JevIntentRouter()
            routing_res = router.route(requirement)
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
            intent = routing_res.intent
        elif isinstance(requirement, EngineeringIntent):
            intent = requirement
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

        # 3. Intent Compilation to Action Plan (Fail-closed on missing geometry/material)
        try:
            plan = compile_engineering_intent(
                intent=intent,
                model_name=model_name,
                part_name=part_name,
                job_name=job_name,
                geometry=geometry,
                material=effective_material,
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

        # 5. Apply Plan Actions to CAE Environment
        self.apply_plan(plan)

        # 6. Single Canonical Production Outlet: AnalysisRunner
        criteria = kwargs.pop("criteria", None) or intent.acceptance_criteria or ()
        cname = getattr(self.executor, "__class__", None).__name__ or ""
        is_test_double = any(token in cname for token in ("Mock", "Fake", "Stub", "Dummy", "OdbBackedExecutor")) or \
                         getattr(self.executor, "_is_mock", False)
        default_prod = (self.mode == "production" and not is_test_double)
        prod_req = kwargs.pop("require_production", default_prod)
        target_workdir = kwargs.pop("workdir", None)
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
            heal_workdir = heal_kwargs.pop("workdir", getattr(run, "work_dir", None) or os.getcwd())
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
        out_dir = target_workdir or (os.path.dirname(run.odb_path) if getattr(run, "odb_path", None) else None) or os.getcwd()
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
        )

        all_figures = list(generated_figures) + list(figure_selection.reused_figures)

        report_title = f"Engineering Analysis Report: {intent.description or plan.model_name}"
        report_data = self.build_report(
            run,
            title=report_title,
            objective=intent.description or f"Automated analysis under {capability.capability_id}",
            result_intelligence=ri_bundle,
            figures=all_figures,
            self_healing=healing_result,
        )
        report_md = render_markdown(report_data)
        report_html_str = render_html(report_data)

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
                        if isinstance(v, (int, float)) and not math.isnan(float(v)):
                            found_valid_val = True
                            break

                # Also inspect extraction diagnostics
                diag_failed = False
                for k in candidate_keys:
                    if k in diag_map:
                        msg = str(diag_map[k]).upper()
                        if msg.startswith("UNAVAILABLE") or msg.startswith("FAILED"):
                            diag_failed = True
                            break

                if not found_valid_val or diag_failed:
                    is_completed = False
                    eng_status = "RESULT_INVALID"
                    break

        deterministic_delivery_card = None
        if prod_req and is_completed and acceptance and getattr(acceptance, "deliverable", False):
            try:
                from pathlib import Path
                from .reporting.pipeline import DeterministicReportPipeline
                pipeline = DeterministicReportPipeline()
                deterministic_delivery_card, _, det_report_data = pipeline.build_and_render(
                    output_dir=Path(out_dir),
                    title=report_title,
                    case_id=plan.job_name,
                    run_id=getattr(run, "id", "RUN-AUTH"),
                    model_info={
                        "name": plan.model_name,
                        "max_mises_mpa": metric_dict.get("max_mises") or metric_dict.get("S_Mises"),
                        "max_displacement_mm": metric_dict.get("max_displacement") or metric_dict.get("U_magnitude"),
                    },
                    results_info=[{"metric": k, "value": v} for k, v in metric_dict.items()],
                    acceptance_info=acceptance,
                    visualization_specs=figure_selection.specs,
                    figures=all_figures,
                    require_deliverable=True,
                    odb_path=getattr(run, "odb_path", None),
                    input_hash=getattr(run.provenance, "input_hash", "") if getattr(run, "provenance", None) else "",
                    launcher=getattr(self.executor, "launcher", None),
                )
                report_md = render_markdown(det_report_data)
                report_html_str = render_html(det_report_data)
            except Exception as d_exc:
                is_completed = False
                eng_status = "DELIVERY_BLOCKED"

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
            errors=() if is_completed else (f"Engineering status: {eng_status}",),
            metadata={"self_healing": healing_result.to_dict() if healing_result else None},
        )
