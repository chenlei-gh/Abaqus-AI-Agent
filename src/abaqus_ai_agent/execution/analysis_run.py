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

    def with_state(self, state, **changes):
        values = dict(
            id=self.id, model_name=self.model_name, job_name=self.job_name,
            state=state, job_status=self.job_status, odb_path=self.odb_path,
            engineering_status=self.engineering_status,
            acceptance_passed=self.acceptance_passed, provenance=self.provenance,
            evidence=self.evidence,
            diagnostics=self.diagnostics, artifacts=self.artifacts,
            metadata=dict(self.metadata))
        values.update(changes)
        return AnalysisRun(**values)

    @property
    def solver_completed(self):
        return self.job_status is not None and self.job_status.state == JobState.COMPLETED


def discover_odb(executor, job_name):
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
            timeout=3600, action_plan=(), environment=None,
            contact_expected=None, contact_evidence=None, contact_step=None,
            contact_frame=-1, contact_history_region=None, contact_position=None,
            contact_region=None, benchmark=None, benchmark_reference_values=None, benchmark_result_overrides=None,
            experimental_observations=()):
        run_id = str(uuid.uuid4())
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
        jobs = JobController(self.executor)
        try:
            snapshot = initial_snapshot
            if snapshot is not None and job_name not in snapshot.jobs:
                jobs.create(job_name, model_name)

            from ..planning.output import plan_outputs, actions_from_output_plan
            benchmark_execution_criteria = ()
            if benchmark is not None:
                from ..benchmarks import benchmark_result_criteria
                benchmark_execution_criteria = benchmark_result_criteria(benchmark, benchmark_result_overrides)
            execution_criteria = tuple(criteria or ()) + tuple(benchmark_execution_criteria)
            output_plan = plan_outputs(execution_criteria)
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
            for output_action in output_actions:
                from ..validation.actions import validate_action
                from ..actions.runner import execute
                validate_action(output_action)
                execute(self.executor, output_action)

            status = jobs.submit(job_name, wait=True, timeout=timeout)
            artifacts = _collect_artifacts(self.executor, job_name)
            run = run.with_state(
                run.state,
                provenance=_provenance_with_artifacts(run.provenance, artifacts),
            )
            if status.state != JobState.COMPLETED:
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
                                  "solver_artifacts": _collect_diagnostics(self.executor, job_name)},))

            run = run.with_state(
                AnalysisRunState.COMPLETED,
                job_status=status,
                engineering_status=EngineeringStatus.RESULT_SUSPICIOUS.value,
                artifacts=artifacts)

            path = odb_path or discover_odb(self.executor, job_name)
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

            if (not criteria and benchmark is None and numerical_verification is None and
                    engineering_checks is None and contact_expected is None and
                    not experimental_observations):
                return run.with_state(AnalysisRunState.ODB_VALIDATED)

            if result_values is None:
                from .results import extract_criteria
                result_values, result_evidence = extract_criteria(
                    self.executor, path, execution_criteria)
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

            benchmark_result = None
            benchmark_evidence = ()
            experimental_validation = None
            experimental_evidence = ()
            if benchmark is not None:
                from ..benchmarks import derive_benchmark_observations, evaluate_benchmark
                benchmark_observed, benchmark_derivation, benchmark_pre_failures = (
                    derive_benchmark_observations(
                        benchmark, result_values, benchmark_reference_values
                    )
                )
                benchmark_result = evaluate_benchmark(
                    benchmark,
                    benchmark_observed,
                    benchmark.acceptance,
                    pre_failures=benchmark_pre_failures,
                )
                benchmark_evidence = (
                    Evidence(
                        kind="benchmark_derivation",
                        source="odb" if result_source == "odb" else "external_input",
                        locator=job_name,
                        value=benchmark_derivation,
                    ),
                    Evidence(
                        kind="benchmark_result",
                        source="benchmark",
                        locator=job_name,
                        value=benchmark_result,
                    ),
                )

            if experimental_observations:
                from ..experimental_validation import validate_result_values
                experimental_validation = validate_result_values(
                    result_values, experimental_observations
                )
                experimental_evidence = (Evidence(
                    kind="experimental_validation",
                    source="experimental_validation",
                    locator=job_name,
                    value=experimental_validation,
                ),)

            contact_diagnostics = None
            if contact_expected is not None:
                from ..execution.odb import extract_contact_evidence
                from ..contact_diagnostics import diagnose_contact
                if contact_evidence is None:
                    steps = tuple(odb.get("steps", ())) if isinstance(odb, dict) else ()
                    if steps or contact_step is not None:
                        selected_step = contact_step or steps[-1]
                        contact_evidence = extract_contact_evidence(
                            self.executor, path, selected_step,
                            frame=contact_frame,
                            history_region=contact_history_region,
                            position=contact_position,
                            region=contact_region,
                        )
                if contact_evidence is None:
                    from ..contracts.contact import ContactDiagnostic, ContactDiagnosticReport
                    contact_diagnostics = ContactDiagnosticReport((
                        ContactDiagnostic(
                            "contact_evidence_sufficiency",
                            "insufficient_evidence",
                            message="contact expectation declared but no contact evidence could be obtained",
                        ),
                    ))
                else:
                    contact_diagnostics = diagnose_contact(contact_evidence, contact_expected)

            accepted = evaluate_result_acceptance(
                result_status=status.state.value.lower(),
                numerical=numerical_verification,
                engineering=engineering_checks,
                values=result_values,
                criteria=criteria,
                contact_diagnostics=contact_diagnostics,
                benchmark_result=benchmark_result,
                experimental_validation=experimental_validation,
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
            if contact_evidence is not None:
                verification_evidence.append(Evidence(
                    kind="contact_evidence", source="odb",
                    locator=path, value=contact_evidence,
                ))
            if contact_diagnostics is not None:
                verification_evidence.append(Evidence(
                    kind="contact_diagnostics", source="verification",
                    locator=job_name, value=contact_diagnostics,
                ))
            status_value = (
                EngineeringStatus.RESULT_VALID.value
                if accepted.passed and result_source == "odb"
                else EngineeringStatus.RESULT_SUSPICIOUS.value
                if accepted.passed
                else EngineeringStatus.RESULT_INVALID.value
            )
            evidence = EvidenceBundle((Evidence(
                kind="odb_summary", source="odb", locator=path, value=odb
            ), Evidence(
                kind="acceptance", source="acceptance", locator=job_name,
                value=accepted
            ))).extend(tuple(verification_evidence)).extend(tuple(benchmark_evidence)).extend(result_evidence)
            return run.with_state(
                AnalysisRunState.ACCEPTED if accepted.passed
                else AnalysisRunState.RESULTS_EXTRACTED,
                engineering_status=status_value,
                acceptance_passed=accepted.passed,
                evidence=evidence, artifacts=artifacts,
                metadata=dict(
                    run.metadata,
                    result_values=dict(result_values),
                    result_source=result_source,
                    experimental_validation=experimental_validation,
                    experimental_validation=experimental_validation,
                ))
        except Exception as exc:
            artifacts = _collect_artifacts(self.executor, job_name)
            diagnostics = _collect_diagnostics(self.executor, job_name)
            return run.with_state(
                AnalysisRunState.FAILED,
                engineering_status=EngineeringStatus.EXECUTION_FAILED.value,
                artifacts=artifacts,
                diagnostics=({"error": str(exc), "solver_artifacts": diagnostics},))


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


def _collect_diagnostics(executor, job_name):
    try:
        from .artifacts import inspect_job_diagnostics
        return inspect_job_diagnostics(executor, job_name)
    except Exception:
        return {}

def _collect_artifacts(executor, job_name):
    try:
        from .artifacts import inspect_job_artifacts
        return inspect_job_artifacts(executor, job_name).items
    except Exception:
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
