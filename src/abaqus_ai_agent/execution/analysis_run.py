import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .jobs import JobController, JobState, JobStatus
from ..engineering_status import EngineeringStatus
from ..evidence.result import summarize_odb
from ..evidence.model import Evidence, EvidenceBundle
from ..contracts.provenance import AnalysisProvenance
from ..provenance import stable_hash
from ..acceptance import evaluate_result_acceptance


class AnalysisRunState(str, Enum):
    CREATED = "created"
    PREFLIGHTED = "preflighted"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    ODB_VALIDATED = "odb_validated"
    RESULTS_EXTRACTED = "results_extracted"
    ACCEPTED = "accepted"
    FAILED = "failed"


@dataclass(frozen=True)
class AnalysisRun:
    id: str
    model_name: str
    job_name: str
    state: AnalysisRunState = AnalysisRunState.CREATED
    job_status: Optional[JobStatus] = None
    odb_path: Optional[str] = None
    engineering_status: Optional[str] = None
    acceptance_passed: Optional[bool] = None
    provenance: Optional[AnalysisProvenance] = None
    evidence: EvidenceBundle = field(default_factory=EvidenceBundle)
    diagnostics: Tuple[Dict[str, Any], ...] = ()
    artifacts: Tuple[Any, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)
    metrics: Tuple[Any, ...] = ()
    intent: Optional[Any] = None
    assumptions: Tuple[str, ...] = ()
    solver_selection: Optional[Any] = None
    postprocess_profile: Optional[Any] = None
    action_plan: Tuple[Any, ...] = ()
    model_snapshot: Optional[Any] = None
    runtime: Optional[Dict[str, Any]] = None
    solver: str = "standard"
    inputs: Tuple[Any, ...] = ()
    outputs: Optional[Dict[str, Any]] = None
    verification: Optional[Dict[str, Any]] = None
    acceptance: Optional[Any] = None
    report_reference: Optional[str] = None

    def with_state(self, state, **changes):
        values = dict(
            id=self.id, model_name=self.model_name, job_name=self.job_name,
            state=state, job_status=self.job_status, odb_path=self.odb_path,
            engineering_status=self.engineering_status,
            acceptance_passed=self.acceptance_passed, provenance=self.provenance,
            evidence=self.evidence,
            diagnostics=self.diagnostics, artifacts=self.artifacts,
            metadata=dict(self.metadata), metrics=self.metrics,
            intent=self.intent, assumptions=self.assumptions,
            solver_selection=self.solver_selection,
            postprocess_profile=self.postprocess_profile,
            action_plan=self.action_plan, model_snapshot=self.model_snapshot,
            runtime=self.runtime, solver=self.solver, inputs=self.inputs,
            outputs=self.outputs, verification=self.verification,
            acceptance=self.acceptance, report_reference=self.report_reference,
        )
        values.update(changes)
        return AnalysisRun(**values)

    @property
    def solver_completed(self):
        return self.job_status is not None and self.job_status.state == JobState.COMPLETED

    def get_metric(self, name: str) -> Optional[Any]:
        """Look up a metric value by name from extracted metrics."""
        for m in self.metrics:
            if getattr(m, "name", None) == name or getattr(m, "value_key", None) == name:
                return getattr(m, "value", None)
            if isinstance(m, dict) and (m.get("name") == name or m.get("value_key") == name):
                return m.get("value")
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Canonical dictionary representation answering all engineering run questions."""
        return {
            "id": self.id,
            "model_name": self.model_name,
            "job_name": self.job_name,
            "state": self.state.value if hasattr(self.state, "value") else str(self.state),
            "solver": self.solver,
            "solver_completed": self.solver_completed,
            "job_status": str(getattr(self.job_status, "state", self.job_status)) if self.job_status else None,
            "odb_path": self.odb_path,
            "engineering_status": self.engineering_status,
            "acceptance_passed": self.acceptance_passed,
            "intent": getattr(self.intent, "to_dict", lambda: str(self.intent))() if self.intent is not None else None,
            "assumptions": list(self.assumptions),
            "solver_selection": str(self.solver_selection) if self.solver_selection else None,
            "postprocess_profile": str(self.postprocess_profile) if self.postprocess_profile else None,
            "action_plan_count": len(self.action_plan),
            "runtime": dict(self.runtime or {}),
            "inputs": [getattr(i, "to_dict", lambda: str(i))() if hasattr(i, "to_dict") else i for i in self.inputs],
            "outputs": dict(self.outputs) if self.outputs is not None else None,
            "metrics": [getattr(m, "to_dict", lambda: str(m))() if hasattr(m, "to_dict") else m for m in self.metrics],
            "verification": self.verification,
            "acceptance": getattr(self.acceptance, "to_dict", lambda: str(self.acceptance))() if self.acceptance else None,
            "diagnostics": list(self.diagnostics),
            "artifacts_count": len(self.artifacts),
            "artifacts": [getattr(a, "to_dict", lambda: str(a))() if hasattr(a, "to_dict") else str(a) for a in self.artifacts],
            "provenance": self.provenance.to_dict() if hasattr(self.provenance, "to_dict") else (self.provenance.__dict__ if self.provenance else None),
            "report_reference": self.report_reference,
            "metadata": dict(self.metadata),
        }

    def to_evidence_package(self) -> Dict[str, Any]:
        """Produce a unified evidence view for audit and acceptance."""
        return {
            "run_id": self.id,
            "job_name": self.job_name,
            "solver": self.solver,
            "solver_status": "completed" if self.solver_completed else "failed",
            "odb_status": "available" if self.odb_path else "missing",
            "engineering_status": self.engineering_status,
            "acceptance_passed": self.acceptance_passed,
            "metrics": [getattr(m, "to_dict", lambda: str(m))() if hasattr(m, "to_dict") else m for m in self.metrics],
            "artifacts": [getattr(a, "to_dict", lambda: str(a))() if hasattr(a, "to_dict") else str(a) for a in self.artifacts],
            "inputs": [getattr(i, "to_dict", lambda: str(i))() if hasattr(i, "to_dict") else i for i in self.inputs],
            "outputs": dict(self.outputs) if self.outputs is not None else None,
            "verification": self.verification or {},
            "acceptance": getattr(self.acceptance, "to_dict", lambda: str(self.acceptance))() if self.acceptance else None,
            "diagnostics": list(self.diagnostics),
            "provenance": self.provenance.to_dict() if hasattr(self.provenance, "to_dict") else None,
            "report_reference": self.report_reference,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisRun":
        """Reconstruct an AnalysisRun instance from its serialized dictionary representation."""
        st_val = data.get("state", "created")
        try:
            state = AnalysisRunState(st_val)
        except (ValueError, TypeError):
            state = AnalysisRunState.CREATED

        raw_metrics = data.get("metrics", [])
        parsed_metrics = []
        for m in raw_metrics:
            if isinstance(m, dict):
                from ..contracts.metrics import EngineeringMetric
                parsed_metrics.append(EngineeringMetric(
                    name=m.get("name", "unknown"),
                    value=m.get("value", 0.0),
                    unit=m.get("unit", ""),
                    source=m.get("source", "odb"),
                    quantity=m.get("quantity", ""),
                    metadata=dict(m.get("metadata", {})),
                ))
            else:
                parsed_metrics.append(m)

        raw_prov = data.get("provenance")
        prov = None
        if isinstance(raw_prov, dict):
            from ..contracts.provenance import AnalysisProvenance
            prov = AnalysisProvenance(
                run_id=raw_prov.get("run_id", data.get("id", "")),
                model_name=raw_prov.get("model_name", data.get("model_name", "")),
                job_name=raw_prov.get("job_name", data.get("job_name", "")),
                model_hash=raw_prov.get("model_hash"),
                input_hash=raw_prov.get("input_hash"),
                output_hash=raw_prov.get("output_hash"),
                environment=dict(raw_prov.get("environment", {})),
                metadata=dict(raw_prov.get("metadata", {})),
            )

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            model_name=data.get("model_name", "Model-1"),
            job_name=data.get("job_name", "Job-1"),
            state=state,
            solver=data.get("solver", "standard"),
            odb_path=data.get("odb_path"),
            engineering_status=data.get("engineering_status"),
            acceptance_passed=data.get("acceptance_passed"),
            intent=data.get("intent"),
            assumptions=tuple(data.get("assumptions", ())),
            solver_selection=data.get("solver_selection"),
            postprocess_profile=data.get("postprocess_profile"),
            runtime=dict(data.get("runtime", {})),
            inputs=tuple(data.get("inputs", ())),
            outputs=data.get("outputs"),
            artifacts=tuple(data.get("artifacts", ())),
            metrics=tuple(parsed_metrics),
            verification=data.get("verification"),
            acceptance=data.get("acceptance"),
            provenance=prov,
            diagnostics=tuple(data.get("diagnostics", ())),
            metadata=dict(data.get("metadata", {})),
            report_reference=data.get("report_reference"),
        )


def discover_odb(executor, job_name, workdir=None):
    if workdir:
        candidate = os.path.join(workdir, job_name + ".odb")
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
    raw = executor.execute(
        "import os; print(os.path.abspath(%r + '.odb') if os.path.exists(%r + '.odb') else '')"
        % (job_name, job_name))
    if isinstance(raw, dict):
        for key in ("path", "odb_path"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("stdout", "output"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                candidate = value.strip().splitlines()[-1].strip()
                if candidate:
                    return candidate
    if isinstance(raw, str) and raw.strip():
        return raw.strip().splitlines()[-1].strip()
    return None


class AnalysisRunner:
    """Complete lifecycle: job -> artifacts -> ODB -> result extraction -> acceptance."""

    def __init__(self, executor):
        self.executor = executor

    def run(self, model_name, job_name, odb_path=None, criteria=(),
            result_values=None, numerical_verification=None, engineering_checks=None,
            mesh_quality=None, mesh_convergence=None, fatigue=None, contact_diagnostics=None,
            connector_kinematics=None, fmbd_dynamics=None, sensitivity=None, uncertainty=None,
            timeout=3600, action_plan=(), environment=None, engineering_intent=None,
            postprocess_profile=None, workdir=None, physics_domain=None, require_evidence=None):
        run_id = str(uuid.uuid4())
        orig_executor_workdir = getattr(self.executor, "workdir", None)
        if not workdir:
            if orig_executor_workdir:
                workdir = orig_executor_workdir
            else:
                runs_root = os.path.abspath("runs")
                workdir = os.path.join(runs_root, run_id)
        os.makedirs(workdir, exist_ok=True)
        workdir = os.path.abspath(workdir)

        if hasattr(self.executor, "workdir"):
            self.executor.workdir = workdir
        runtime = _runtime_provenance(self.executor)
        initial_snapshot = None
        try:
            if hasattr(self.executor, "snapshot"):
                initial_snapshot = self.executor.snapshot()
        except Exception:
            # Snapshot is provenance enrichment, never an execution prerequisite.
            initial_snapshot = None
        runtime_environment = dict(getattr(runtime, "metadata", {}) or {}) if runtime else {}
        if environment:
            runtime_environment.update(dict(environment))
        normalized_action_plan = _normalize_action_plan(action_plan)
        provenance = AnalysisProvenance(
            run_id=run_id,
            model_name=model_name,
            job_name=job_name,
            model_hash=None,
            input_hash=None,
            output_hash=None,
            abaqus_version=getattr(runtime, "version", None) if runtime else None,
            python_version=getattr(runtime, "python_version", None) if runtime else None,
            executor=self.executor.__class__.__name__,
            action_plan=normalized_action_plan,
            environment=runtime_environment,
            metadata={
                "model_snapshot_hash": stable_hash(initial_snapshot)
                if initial_snapshot is not None else None,
                "content_hash_scope": "not_captured",
                "action_plan_scope": "caller" if normalized_action_plan else "none",
            },
        )
        run = AnalysisRun(
            run_id, model_name, job_name, AnalysisRunState.PREFLIGHTED,
            provenance=provenance,
        )

        # Preflight Plan Hard Gate (P1-1): Verify plan before job creation/submission
        if action_plan:
            from ..validation.preflight import preflight_plan
            from ..contracts.action import AbaqusAction
            actions_to_preflight = []
            for act in action_plan:
                if isinstance(act, dict):
                    actions_to_preflight.append(AbaqusAction(
                        action_type=act.get("action_type", ""),
                        model_name=act.get("model_name", model_name),
                        target=act.get("target"),
                        parameters=act.get("parameters", {}),
                    ))
                else:
                    actions_to_preflight.append(act)
            preflight_res = preflight_plan(actions_to_preflight, snapshot=initial_snapshot)
            if not preflight_res.passed:
                return run.with_state(
                    AnalysisRunState.FAILED,
                    engineering_status=EngineeringStatus.EXECUTION_FAILED.value,
                    diagnostics=tuple({"preflight_blocker": b} for b in preflight_res.blockers),
                )

        jobs = JobController(self.executor)
        try:
            snapshot = initial_snapshot
            if snapshot is not None and job_name not in snapshot.jobs:
                jobs.create(job_name, model_name)

            from ..planning.output import plan_outputs, actions_from_output_plan, criteria_from_postprocess_profile
            effective_criteria = tuple(criteria or ())
            if postprocess_profile is not None:
                profile_criteria = criteria_from_postprocess_profile(postprocess_profile)
                existing_keys = {item.get("value_key") for item in effective_criteria if isinstance(item, dict)}
                effective_criteria = effective_criteria + tuple(
                    item for item in profile_criteria
                    if item.get("value_key") not in existing_keys
                )
            if engineering_intent is not None:
                from ..contracts.solver_selection import select_solver
                from ..contracts.postprocess import profile_for_solver_selection
                selection = select_solver(engineering_intent)
                postprocess_profile = postprocess_profile or profile_for_solver_selection(selection)
                metadata = dict(run.metadata)
                metadata["solver_selection"] = selection
                metadata["postprocess_profile"] = postprocess_profile
                run = run.with_state(run.state, metadata=metadata)
            output_plan = plan_outputs(effective_criteria, postprocess_profile=None)
            output_actions = actions_from_output_plan(model_name, output_plan)
            if not action_plan and output_actions:
                run = run.with_state(
                    run.state,
                    provenance=AnalysisProvenance(
                        run_id=run.provenance.run_id,
                        model_name=run.provenance.model_name,
                        job_name=run.provenance.job_name,
                        model_hash=run.provenance.model_hash,
                        input_hash=run.provenance.input_hash,
                        output_hash=run.provenance.output_hash,
                        artifact_manifest_hash=run.provenance.artifact_manifest_hash,
                        abaqus_version=run.provenance.abaqus_version,
                        python_version=run.provenance.python_version,
                        executor=run.provenance.executor,
                        action_plan=_action_records(output_actions),
                        environment=dict(run.provenance.environment),
                        metadata=dict(run.provenance.metadata, action_plan_scope="output_plan"),
                    ),
                )
            try:
                if hasattr(self.executor, "execute"):
                    self.executor.execute(f"import os; os.chdir({workdir!r})")
            except Exception:
                pass

            for output_action in output_actions:
                from ..validation.actions import validate_action
                from ..actions.runner import execute
                validate_action(output_action)
                execute(self.executor, output_action)

            status = jobs.submit(job_name, wait=True, timeout=timeout)
            artifacts = _collect_artifacts(self.executor, job_name, workdir=workdir)
            run = run.with_state(
                run.state,
                provenance=_provenance_with_artifacts(run.provenance, artifacts),
            )
            if status.state != JobState.COMPLETED:
                solver_diagnostics = _collect_diagnostics(self.executor, job_name, workdir=workdir)
                sta_tail = solver_diagnostics.get(".sta", {}).get("tail", "")
                log_tail = solver_diagnostics.get(".log", {}).get("tail", "")
                if "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in sta_tail and "COMPLETED" in log_tail:
                    status = JobStatus(job_name, JobState.COMPLETED, status.raw)
                else:
                    engineering = (
                        EngineeringStatus.SOLVER_FAILED
                        if status.state in (JobState.ABORTED, JobState.TERMINATED,
                                             JobState.ERROR, JobState.TIMEOUT)
                        else EngineeringStatus.EXECUTION_FAILED)
                    return run.with_state(
                        AnalysisRunState.FAILED,
                        job_status=status,
                        engineering_status=engineering.value,
                        artifacts=artifacts,
                        diagnostics=({"reason": "job_not_completed",
                                      "state": status.state.value,
                                      "solver_artifacts": solver_diagnostics},))

            run = run.with_state(
                AnalysisRunState.COMPLETED,
                job_status=status,
                engineering_status=EngineeringStatus.RESULT_SUSPICIOUS.value,
                artifacts=artifacts)

            path = odb_path or discover_odb(self.executor, job_name, workdir=workdir)
            if not path:
                return run.with_state(
                    AnalysisRunState.FAILED,
                    engineering_status=EngineeringStatus.ODB_MISSING.value,
                    diagnostics=({"reason": "odb_missing"},),
                    artifacts=artifacts)

            raw_odb = self.executor.inspect_odb(path) if hasattr(
                self.executor, "inspect_odb") else None
            odb = summarize_odb(raw_odb) if raw_odb is not None else {"status": "unavailable"}
            if odb.get("status") != "available" or not odb.get("steps"):
                return run.with_state(
                    AnalysisRunState.FAILED,
                    odb_path=path,
                    engineering_status=EngineeringStatus.RESULT_INVALID.value,
                    diagnostics=({"reason": "odb_invalid", "odb": odb},),
                    evidence=EvidenceBundle((Evidence(kind="odb_summary", source="odb", locator=path, value=odb),)), artifacts=artifacts)

            run = run.with_state(
                AnalysisRunState.ODB_VALIDATED,
                odb_path=path,
                engineering_status=EngineeringStatus.RESULT_SUSPICIOUS.value,
                evidence=EvidenceBundle((Evidence(kind="odb_summary", source="odb", locator=path, value=odb),)), artifacts=artifacts)

            from ..contracts.fatigue import IntentFatigueSpec, FatigueResult
            fatigue_spec = getattr(engineering_intent, "fatigue", None) or (
                fatigue if isinstance(fatigue, IntentFatigueSpec) else None
            )

            if not effective_criteria and numerical_verification is None and engineering_checks is None and mesh_quality is None and mesh_convergence is None and fatigue is None and fatigue_spec is None and contact_diagnostics is None and connector_kinematics is None and fmbd_dynamics is None and not getattr(engineering_intent, "connectors", None) and not getattr(engineering_intent, "fmbd", None) and sensitivity is None and uncertainty is None:
                return run.with_state(AnalysisRunState.ODB_VALIDATED)

            if result_values is None:
                from .results import extract_requirements
                extractions, result_evidence = extract_requirements(
                    self.executor, path, effective_criteria)
                result_values = {item.requirement.value_key: item.value for item in extractions}
                from ..contracts.metrics import metrics_from_extractions
                run_metrics = metrics_from_extractions(extractions)
                result_source = "odb"
            else:
                result_evidence = (Evidence(
                    kind="injected_result",
                    source="external_input",
                    value=dict(result_values),
                    metadata={
                        "odb_backed": False,
                        "engineering_validity": "not_established",
                    },
                ),)
                result_source = "external_input"

            if fatigue_spec is not None and result_source == "odb":
                from ..fatigue import run_fatigue_postprocess
                computed_fatigue_res = None
                fatigue_metrics = {}
                try:
                    target_odb = raw_odb if (raw_odb is not None and hasattr(raw_odb, "steps")) else path
                    computed_fatigue_res, fatigue_metrics = run_fatigue_postprocess(target_odb, fatigue_spec)
                except Exception:
                    out_json_path = None
                    try:
                        import tempfile
                        import json
                        from ..fatigue import build_odb_fatigue_postprocess_script
                        with tempfile.NamedTemporaryFile(suffix=".json", dir=workdir, delete=False) as tf:
                            out_json_path = tf.name
                        post_script = build_odb_fatigue_postprocess_script(
                            odb_path=path,
                            output_json=out_json_path,
                            material_curve=fatigue_spec.material_curve,
                            ultimate_strength=fatigue_spec.ultimate_strength,
                            mean_stress_correction=fatigue_spec.mean_stress_correction,
                            measure=fatigue_spec.measure,
                            step_name=fatigue_spec.step_name,
                            element_label=fatigue_spec.element_label,
                        )
                        self.executor.execute(post_script)
                        if os.path.exists(out_json_path):
                            with open(out_json_path, "r", encoding="utf-8") as f:
                                fatigue_data = json.load(f)
                            c_sum = fatigue_data.get("cycle_summary", {})
                            damage_val = c_sum.get("cumulative_damage", 0.0)
                            total_cnt = max(c_sum.get("total_cycles_count", 1.0), 1.0)
                            life_val = c_sum.get("life_blocks", 0.0) * total_cnt
                            status_val = fatigue_data.get("status", "fail")
                            computed_fatigue_res = FatigueResult(
                                status=status_val,
                                life_cycles=life_val,
                                damage=damage_val,
                                evidence=tuple(fatigue_data.get("evidence", ("fatigue_postprocess_script",))),
                            )
                            fatigue_metrics = {
                                "fatigue_life": life_val,
                                "damage": damage_val,
                                "max_stress_range": c_sum.get("max_stress_range", 0.0),
                                "mean_stress_average": c_sum.get("mean_stress_average", 0.0),
                                "total_cycles_count": c_sum.get("total_cycles_count", 0.0),
                                "hotspot_element": fatigue_data.get("hotspot", {}).get("element_label"),
                            }
                    except Exception:
                        pass
                    finally:
                        if out_json_path and os.path.exists(out_json_path):
                            try:
                                os.remove(out_json_path)
                            except Exception:
                                pass

                if computed_fatigue_res is not None:
                    fatigue = computed_fatigue_res
                    if fatigue_metrics:
                        result_values.update(fatigue_metrics)
                        from ..contracts.metrics import EngineeringMetric
                        f_metrics = [
                            EngineeringMetric(
                                name=k,
                                value=v,
                                unit="cycles" if "life" in k or "cycles" in k else ("MPa" if "stress" in k else ""),
                                source="odb",
                                quantity="fatigue",
                            )
                            for k, v in fatigue_metrics.items() if isinstance(v, (int, float))
                        ]
                        run_metrics = tuple(locals().get("run_metrics", ())) + tuple(f_metrics)

                existing_keys = {c.get("value_key") for c in effective_criteria if isinstance(c, dict)}
                added_crit = []
                if "fatigue_life" not in existing_keys:
                    added_crit.append({
                        "name": "fatigue_life_gate",
                        "value_key": "fatigue_life",
                        "operator": ">=",
                        "limit": float(fatigue_spec.target_cycles),
                        "unit": "cycles",
                        "required": True,
                    })
                if "damage" not in existing_keys:
                    added_crit.append({
                        "name": "fatigue_damage_gate",
                        "value_key": "damage",
                        "operator": "<=",
                        "limit": float(fatigue_spec.allowable_damage),
                        "unit": "",
                        "required": True,
                    })
                if added_crit:
                    effective_criteria = tuple(effective_criteria) + tuple(added_crit)

            run_manifest = None
            if result_source == "odb":
                try:
                    from ..contracts.evidence import build_evidence_manifest_v2
                    art_dir = workdir or (os.path.dirname(os.path.abspath(path)) if path else ".")
                    fnames = [os.path.basename(a.path) for a in artifacts if getattr(a, "exists", False) and getattr(a, "path", None)]
                    if fnames:
                        run_manifest = build_evidence_manifest_v2(
                            run_id=run_id,
                            case_id=job_name,
                            artifacts_dir=art_dir,
                            artifact_filenames=fnames,
                            intent_summary={"model_name": model_name, "job_name": job_name},
                            required_results={"criteria": [c if isinstance(c, dict) else str(c) for c in effective_criteria]},
                            environment=runtime_environment,
                        )
                except Exception:
                    run_manifest = None

            if physics_domain is not None:
                domain_to_eval = physics_domain
            elif fatigue_spec is not None:
                domain_to_eval = "fatigue"
            elif getattr(engineering_intent, "fmbd", None) or fmbd_dynamics is not None:
                domain_to_eval = "fmbd"
            elif getattr(engineering_intent, "connectors", None) or connector_kinematics is not None:
                domain_to_eval = "connector"
            else:
                domain_to_eval = None

            effective_require_evidence = require_evidence if require_evidence is not None else (True if result_source == "odb" else False)
            accepted = evaluate_result_acceptance(
                result_status=status.state.value.lower(),
                numerical=numerical_verification,
                engineering=engineering_checks,
                mesh_quality=mesh_quality,
                convergence=mesh_convergence,
                fatigue=fatigue,
                contact_diagnostics=contact_diagnostics,
                connector_kinematics=connector_kinematics,
                fmbd_dynamics=fmbd_dynamics,
                values=result_values,
                criteria=effective_criteria,
                evidence=result_evidence,
                evidence_manifest=run_manifest,
                base_dir=art_dir if result_source == "odb" else None,
                expected_run_id=run_id if result_source == "odb" else None,
                require_evidence=effective_require_evidence,
                physics_domain=domain_to_eval,
            )
            verification_evidence = []
            if numerical_verification is not None:
                verification_evidence.append(Evidence(
                    kind="numerical_verification", source="verification",
                    locator=job_name, value=numerical_verification,
                ))
            if engineering_checks is not None:
                verification_evidence.append(Evidence(
                    kind="engineering_checks", source="verification",
                    locator=job_name, value=engineering_checks,
                ))
            if mesh_quality is not None:
                verification_evidence.append(Evidence(
                    kind="mesh_quality", source="verification",
                    locator=job_name, value=mesh_quality,
                ))
            if mesh_convergence is not None:
                verification_evidence.append(Evidence(
                    kind="mesh_convergence", source="verification",
                    locator=job_name, value=mesh_convergence,
                ))
            if fatigue is not None:
                verification_evidence.append(Evidence(
                    kind="fatigue", source="verification",
                    locator=job_name, value=fatigue,
                ))
            if contact_diagnostics is not None:
                verification_evidence.append(Evidence(
                    kind="contact_diagnostics", source="verification",
                    locator=job_name, value=contact_diagnostics,
                ))
            if connector_kinematics is not None:
                verification_evidence.append(Evidence(
                    kind="connector_kinematics", source="verification",
                    locator=job_name, value=connector_kinematics,
                ))
            if fmbd_dynamics is not None:
                verification_evidence.append(Evidence(
                    kind="fmbd_dynamics", source="verification",
                    locator=job_name, value=fmbd_dynamics,
                ))
            if sensitivity is not None:
                verification_evidence.append(Evidence(
                    kind="sensitivity", source="analysis",
                    locator=job_name, value=sensitivity,
                ))
            if uncertainty is not None:
                verification_evidence.append(Evidence(
                    kind="uncertainty", source="analysis",
                    locator=job_name, value=uncertainty,
                ))
            evidence = EvidenceBundle((Evidence(
                kind="odb_summary", source="odb", locator=path, value=odb
            ), Evidence(
                kind="acceptance", source="acceptance", locator=job_name,
                value=accepted
            ))).extend(tuple(verification_evidence)).extend(result_evidence)
            verification_map = {}
            if numerical_verification is not None:
                verification_map["numerical"] = getattr(numerical_verification, "to_dict", lambda: str(numerical_verification))()
            if engineering_checks is not None:
                verification_map["engineering_checks"] = getattr(engineering_checks, "to_dict", lambda: str(engineering_checks))()
            if mesh_quality is not None:
                verification_map["mesh_quality"] = getattr(mesh_quality, "to_dict", lambda: str(mesh_quality))()
            if mesh_convergence is not None:
                verification_map["mesh_convergence"] = getattr(mesh_convergence, "to_dict", lambda: str(mesh_convergence))()
            if fatigue is not None:
                verification_map["fatigue"] = getattr(fatigue, "to_dict", lambda: str(fatigue))()
            if contact_diagnostics is not None:
                verification_map["contact_diagnostics"] = getattr(contact_diagnostics, "to_dict", lambda: str(contact_diagnostics))()

            if result_source == "external_input":
                final_state = AnalysisRunState.RESULTS_EXTRACTED
                status_value = EngineeringStatus.RESULT_SUSPICIOUS.value
                acceptance_passed = False
            elif accepted.passed and result_source == "odb":
                final_state = AnalysisRunState.ACCEPTED
                status_value = EngineeringStatus.RESULT_VALID.value
                acceptance_passed = True
            else:
                final_state = AnalysisRunState.RESULTS_EXTRACTED
                status_value = EngineeringStatus.RESULT_INVALID.value
                acceptance_passed = False

            return run.with_state(
                final_state,
                engineering_status=status_value,
                acceptance_passed=acceptance_passed,
                acceptance=accepted,
                intent=engineering_intent,
                solver_selection=locals().get("selection"),
                postprocess_profile=postprocess_profile,
                action_plan=tuple(normalized_action_plan),
                verification=verification_map,
                evidence=evidence, artifacts=artifacts, metrics=locals().get("run_metrics", ()))
        except Exception as exc:
            artifacts = _collect_artifacts(self.executor, job_name, workdir=workdir)
            diagnostics = _collect_diagnostics(self.executor, job_name, workdir=workdir)
            return run.with_state(
                AnalysisRunState.FAILED,
                engineering_status=EngineeringStatus.EXECUTION_FAILED.value,
                artifacts=artifacts,
                diagnostics=({"error": str(exc), "solver_artifacts": diagnostics},))
        finally:
            if hasattr(self.executor, "workdir"):
                self.executor.workdir = orig_executor_workdir
            if orig_executor_workdir:
                try:
                    if hasattr(self.executor, "execute"):
                        self.executor.execute(f"import os; os.chdir({orig_executor_workdir!r})")
                except Exception:
                    pass


def _provenance_with_artifacts(provenance, artifacts):
    if provenance is None:
        return None
    manifest = tuple((getattr(a, "suffix", ""), getattr(a, "path", ""),
                      bool(getattr(a, "exists", False)), getattr(a, "size", None),
                      getattr(a, "modified_time", None)) for a in artifacts or ())
    return AnalysisProvenance(
        run_id=provenance.run_id, model_name=provenance.model_name,
        job_name=provenance.job_name, model_hash=provenance.model_hash,
        input_hash=provenance.input_hash, output_hash=provenance.output_hash,
        artifact_manifest_hash=stable_hash(manifest),
        abaqus_version=provenance.abaqus_version, python_version=provenance.python_version,
        executor=provenance.executor, action_plan=provenance.action_plan,
        environment=provenance.environment, metadata=dict(provenance.metadata))

def _collect_diagnostics(executor, job_name, workdir=None):
    try:
        from .artifacts import inspect_job_diagnostics
        return inspect_job_diagnostics(executor, job_name, workdir=workdir)
    except Exception:
        return {}

def _collect_artifacts(executor, job_name, workdir=None):
    try:
        from .artifacts import inspect_job_artifacts
        items = inspect_job_artifacts(executor, job_name, workdir=workdir).items
        if items and any(getattr(x, "exists", False) for x in items):
            return items
    except Exception:
        pass
    if workdir and os.path.isdir(workdir):
        from .artifacts import JobArtifact, DEFAULT_ARTIFACT_SUFFIXES
        local_items = []
        for sfx in DEFAULT_ARTIFACT_SUFFIXES:
            p = os.path.join(workdir, job_name + sfx)
            if os.path.exists(p):
                st = os.stat(p)
                local_items.append(JobArtifact(
                    job_name=job_name,
                    suffix=sfx,
                    path=p,
                    exists=True,
                    size=st.st_size,
                    modified_time=st.st_mtime,
                ))
        if local_items:
            return tuple(local_items)
    return ()


def _normalize_action_plan(action_plan):
    items = tuple(action_plan or ())
    if not items:
        return ()
    if all(isinstance(item, dict) for item in items):
        return items
    return _action_records(items)


def _runtime_provenance(executor):
    """Best-effort runtime metadata; absence never masquerades as verification."""
    try:
        if hasattr(executor, "runtime_info"):
            return executor.runtime_info()
    except Exception:
        return None
    return None


def _action_records(actions):
    records = []
    for action in actions or ():
        records.append({
            "action_type": getattr(action, "action_type", None),
            "model_name": getattr(action, "model_name", None),
            "target": getattr(action, "target", None),
            "parameters": dict(getattr(action, "parameters", {}) or {}),
        })
    return tuple(records)
