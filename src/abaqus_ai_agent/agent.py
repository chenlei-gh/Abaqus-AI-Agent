from dataclasses import dataclass

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
    def __init__(self, executor):
        self.executor = executor

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

    def plan_outputs(self, criteria=(), outputs=(), postprocess_profile=None):
        from .planning.output import plan_outputs
        return plan_outputs(criteria, outputs, postprocess_profile=postprocess_profile)

    def analysis_run(self, model_name, job_name, odb_path=None, criteria=(), result_values=None,
                     numerical_verification=None, engineering_checks=None,
                     mesh_quality=None, mesh_convergence=None, fatigue=None,
                     contact_diagnostics=None, sensitivity=None, uncertainty=None,
                     engineering_intent=None, postprocess_profile=None,
                     action_plan=(), environment=None, timeout=3600):
        from .execution.analysis_run import AnalysisRunner
        return AnalysisRunner(self.executor).run(
            model_name, job_name, odb_path=odb_path, criteria=criteria,
            result_values=result_values, numerical_verification=numerical_verification,
            engineering_checks=engineering_checks, mesh_quality=mesh_quality,
            mesh_convergence=mesh_convergence, fatigue=fatigue,
            contact_diagnostics=contact_diagnostics, sensitivity=sensitivity,
            uncertainty=uncertainty, engineering_intent=engineering_intent,
            postprocess_profile=postprocess_profile, action_plan=action_plan,
            environment=environment, timeout=timeout)

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
        from .planning.compiler import compile_engineering_intent
        from .reporting.renderer import render_markdown
        from .typesafe_intent import JevIntentRouter
        from .validation.preflight import preflight_plan

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

        # 3. Intent Compilation to Action Plan (Fail-closed on missing geometry/material)
        try:
            plan = compile_engineering_intent(
                intent=intent,
                model_name=model_name,
                part_name=part_name,
                job_name=job_name,
                geometry=geometry,
                material=material,
                mesh=mesh,
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
        criteria = intent.acceptance_criteria or ()
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
            **kwargs,
        )

        # 7. Summary Card & Markdown Engineering Report
        metrics = getattr(run, "metrics", ()) or ()
        acceptance = getattr(run, "acceptance", None)

        report_title = f"Engineering Analysis Report: {intent.description or plan.model_name}"
        report_data = self.build_report(
            run,
            title=report_title,
            objective=intent.description or f"Automated analysis under {capability.capability_id}",
        )
        report_md = render_markdown(report_data)

        eng_status = getattr(run, "engineering_status", "EXECUTED")
        run_state = getattr(run, "state", None)
        run_state_val = getattr(run_state, "value", str(run_state))
        is_completed = (
            run_state_val == "ACCEPTED"
            or eng_status in ("ACCEPTED", "RESULT_VALID")
        ) and bool(getattr(run, "acceptance_passed", False))
        task_status = TaskStatus.COMPLETED if is_completed else TaskStatus.FAILED

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

        summary_card = {
            "status": task_status.value,
            "model_name": plan.model_name,
            "job_name": plan.job_name,
            "capability_id": capability.capability_id,
            "physics_domain": capability.physics_domain,
            "engineering_status": eng_status,
            "acceptance_passed": getattr(run, "acceptance_passed", False),
            "metrics": metric_dict,
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
            errors=() if is_completed else (f"Engineering status: {eng_status}",),
        )
