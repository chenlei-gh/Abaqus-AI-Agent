"""P1.4 Solver Failure Self-Healing Orchestrator."""

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..analysis_run_diff import diff_analysis_runs
from ..contracts.diagnostics import (
    HealingAttempt,
    RemediationAction,
    RemediationCategory,
    SelfHealingResult,
)
from ..contracts.intent import EngineeringIntent
from ..execution.analysis_run import AnalysisRun, AnalysisRunState
from .remediator import SolverRemediator
from .solver_patterns import DiagnosticIssue, diagnose_solver_artifacts


class SelfHealingOrchestrator:
    """Coordinates solver failure diagnosis, remediation synthesis, and bounded re-execution."""

    @classmethod
    def extract_solver_texts(
        cls,
        run: AnalysisRun,
        executor: Optional[Any] = None,
        workdir: Optional[str] = None,
    ) -> Dict[str, str]:
        """Extract bounded solver text artifacts (.msg, .sta, .dat, .log) from run or filesystem."""
        texts = {"msg": "", "sta": "", "dat": "", "log": ""}

        # 1. From run.diagnostics metadata if captured
        for d in getattr(run, "diagnostics", ()) or ():
            if isinstance(d, dict) and "solver_artifacts" in d:
                art = d["solver_artifacts"]
                if isinstance(art, dict):
                    texts["msg"] = texts["msg"] or art.get(".msg", {}).get("tail", "")
                    texts["sta"] = texts["sta"] or art.get(".sta", {}).get("tail", "")
                    texts["dat"] = texts["dat"] or art.get(".dat", {}).get("tail", "")
                    texts["log"] = texts["log"] or art.get(".log", {}).get("tail", "")

        # 2. From filesystem if executor/workdir available
        wd = workdir or getattr(run, "work_dir", None) or os.getcwd()
        job = getattr(run, "job_name", "")
        if job and os.path.exists(wd):
            for suffix, key in ((".msg", "msg"), (".sta", "sta"), (".dat", "dat"), (".log", "log")):
                if not texts[key]:
                    p = os.path.join(wd, job + suffix)
                    if os.path.exists(p):
                        try:
                            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                                lines = f.readlines()
                                texts[key] = "".join(lines[-100:])
                        except Exception:
                            pass

        return texts

    @classmethod
    def attempt_healing(
        cls,
        agent: Any,
        failed_run: AnalysisRun,
        intent: EngineeringIntent,
        capability: Any,
        plan: Any,
        geometry: Optional[Any] = None,
        material: Optional[Any] = None,
        mesh: Optional[Any] = None,
        grounded_regions: Optional[Dict[str, Any]] = None,
        max_attempts: int = 2,
        timeout: int = 3600,
        workdir: Optional[str] = None,
        criteria: Sequence[Any] = (),
        postprocess_profile: Optional[Any] = None,
        **kwargs,
    ) -> Tuple[AnalysisRun, SelfHealingResult]:
        """Execute bounded self-healing cycle and return final run and audit result."""
        from ..planning.compiler import compile_engineering_intent
        from ..validation.preflight import preflight_plan

        initial_status = getattr(failed_run, "engineering_status", "UNKNOWN")
        attempts_records: List[HealingAttempt] = []
        all_remediations: List[RemediationAction] = []
        all_diagnosed_issues: List[DiagnosticIssue] = []

        current_run = failed_run
        current_intent = intent
        current_plan = plan
        healed = False
        final_diff = None

        # Bound attempts strictly
        bounded_max_attempts = max(1, min(max_attempts, 3))

        for attempt_idx in range(1, bounded_max_attempts + 1):
            # 1. Harvest artifacts and diagnose
            texts = cls.extract_solver_texts(current_run, executor=getattr(agent, "executor", None), workdir=workdir)
            issues = diagnose_solver_artifacts(
                msg_text=texts["msg"],
                sta_text=texts["sta"],
                dat_text=texts["dat"],
                log_text=texts["log"],
                job_status=str(getattr(current_run, "engineering_status", "FAILED")),
            )

            if not issues:
                # If no textual patterns matched, fallback to checking run diagnostics dict
                for d in getattr(current_run, "diagnostics", ()) or ():
                    if isinstance(d, dict) and "diagnosis_id" in d:
                        issues = issues + (
                            DiagnosticIssue(
                                diagnosis_id=str(d["diagnosis_id"]),
                                severity=str(d.get("severity", "ERROR")),
                                supporting_evidence=tuple(d.get("supporting_evidence", ("Diagnostics from run record",))),
                                likely_cause=str(d.get("likely_cause", "Unconstrained degrees of freedom or divergence")),
                                suggested_remediation=str(d.get("suggested_remediation", "Apply remediation")),
                            ),
                        )
                    else:
                        reason = d.get("reason") if isinstance(d, dict) else str(d)
                        if reason:
                            issues = issues + (
                                DiagnosticIssue(
                                    diagnosis_id="UNRESOLVED_SOLVER_ERROR",
                                    severity="ERROR",
                                    supporting_evidence=(str(reason),),
                                    likely_cause="Generic solver failure without matching textual patterns",
                                    suggested_remediation="Inspect solver log files and input deck manually.",
                                ),
                            )

            for iss in issues:
                if iss not in all_diagnosed_issues:
                    all_diagnosed_issues.append(iss)

            # 2. Check for unhealable failure modes
            if any(iss.diagnosis_id == "LICENSE_DENIED" for iss in issues):
                break

            # 3. Generate candidate remediations
            remediations = SolverRemediator.generate_remediations(issues, intent=current_intent, plan=current_plan)
            healable_remediations = [r for r in remediations if r.category != RemediationCategory.UNRESOLVED]
            if not healable_remediations:
                break

            for r in healable_remediations:
                if r not in all_remediations:
                    all_remediations.append(r)

            # 4. Apply remediations to derive enriched intent
            enriched_intent = SolverRemediator.apply_remediations(current_intent, healable_remediations)

            # 5. Recompile and preflight new plan
            try:
                new_plan = compile_engineering_intent(
                    intent=enriched_intent,
                    model_name=f"{current_plan.model_name}_H{attempt_idx}",
                    part_name=current_plan.part_name,
                    job_name=f"{current_plan.job_name}_H{attempt_idx}",
                    geometry=geometry,
                    material=material,
                    mesh=mesh,
                    grounded_regions=grounded_regions,
                    submit_job=True,
                )
            except Exception as comp_err:
                # Compilation failed, cannot proceed
                break

            preflight_res = preflight_plan(new_plan.actions)
            if not preflight_res.passed:
                break

            # 6. Apply actions to CAE executor if present
            if hasattr(agent, "apply_plan") and getattr(agent, "executor", None) is not None:
                agent.apply_plan(new_plan)

            # 7. Execute candidate run
            new_run = agent.analysis_run(
                model_name=new_plan.model_name,
                job_name=new_plan.job_name,
                odb_path=None,
                criteria=criteria,
                engineering_intent=enriched_intent,
                postprocess_profile=postprocess_profile or getattr(capability, "profile", None),
                action_plan=new_plan.actions,
                timeout=timeout,
                **kwargs,
            )

            # 8. Compute inspectable RunDiff between failure and candidate
            diff = diff_analysis_runs(current_run, new_run)
            final_diff = diff.to_dict()

            # 9. Verify single-exit acceptance contract on candidate
            run_state = getattr(new_run, "state", None)
            run_state_val = getattr(run_state, "value", str(run_state))
            eng_status = getattr(new_run, "engineering_status", "")
            is_accepted = (
                (run_state == AnalysisRunState.ACCEPTED or str(run_state_val).lower() == "accepted")
                and eng_status in ("ACCEPTED", "RESULT_VALID")
                and bool(getattr(new_run, "acceptance_passed", False))
            )

            attempt_record = HealingAttempt(
                attempt_number=attempt_idx,
                trigger_issues=tuple(iss.diagnosis_id for iss in issues),
                actions_applied=tuple(healable_remediations),
                pre_run_id=getattr(current_run, "id", f"run_attempt_{attempt_idx-1}"),
                post_run_id=getattr(new_run, "id", f"run_attempt_{attempt_idx}"),
                run_diff=final_diff,
                outcome="ACCEPTED" if is_accepted else "FAILED",
                metadata={"job_name": new_plan.job_name},
            )
            attempts_records.append(attempt_record)

            current_run = new_run
            current_intent = enriched_intent
            current_plan = new_plan

            if is_accepted:
                healed = True
                break

        unresolved = tuple(
            iss.diagnosis_id for iss in all_diagnosed_issues
            if not healed and iss.severity == "ERROR"
        )

        healing_result = SelfHealingResult(
            healed=healed,
            total_attempts=len(attempts_records),
            initial_status=initial_status,
            final_status=getattr(current_run, "engineering_status", "FAILED"),
            diagnosed_issues=tuple(all_diagnosed_issues),
            remediations_applied=tuple(all_remediations),
            attempts=tuple(attempts_records),
            final_run_diff=final_diff,
            unresolved_issues=unresolved,
            metadata={
                "max_attempts_budget": bounded_max_attempts,
                "healed": healed,
            },
        )

        return current_run, healing_result
