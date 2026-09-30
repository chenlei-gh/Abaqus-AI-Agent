import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .jobs import JobController, JobState, JobStatus
from ..engineering_status import EngineeringStatus
from ..evidence.result import summarize_odb


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
    evidence: Tuple[Any, ...] = ()
    diagnostics: Tuple[Dict[str, Any], ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    def with_state(self, state, **changes):
        values = dict(
            id=self.id, model_name=self.model_name, job_name=self.job_name,
            state=state, job_status=self.job_status, odb_path=self.odb_path,
            engineering_status=self.engineering_status,
            acceptance_passed=self.acceptance_passed, evidence=self.evidence,
            diagnostics=self.diagnostics, metadata=dict(self.metadata))
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
    """Thin lifecycle: job -> ODB validation -> optional result acceptance."""
    def __init__(self, executor):
        self.executor = executor

    def run(self, model_name, job_name, odb_path=None, criteria=(),
            result_values=None, timeout=3600):
        run = AnalysisRun(str(uuid.uuid4()), model_name, job_name,
                          AnalysisRunState.PREFLIGHTED)
        jobs = JobController(self.executor)
        try:
            snapshot = self.executor.snapshot() if hasattr(self.executor, "snapshot") else None
            if snapshot is not None and job_name not in snapshot.jobs:
                jobs.create(job_name, model_name)

            status = jobs.submit(job_name, wait=True, timeout=timeout)
            if status.state != JobState.COMPLETED:
                engineering = (
                    EngineeringStatus.SOLVER_FAILED
                    if status.state in (JobState.ABORTED, JobState.TERMINATED,
                                         JobState.ERROR, JobState.TIMEOUT)
                    else EngineeringStatus.EXECUTION_FAILED)
                return run.with_state(
                    AnalysisRunState.FAILED,
                    job_status=status,
                    engineering_status=engineering.value)

            run = run.with_state(
                AnalysisRunState.COMPLETED,
                job_status=status,
                engineering_status=EngineeringStatus.RESULT_SUSPICIOUS.value)

            path = odb_path or discover_odb(self.executor, job_name)
            if not path:
                return run.with_state(
                    AnalysisRunState.FAILED,
                    engineering_status=EngineeringStatus.ODB_MISSING.value,
                    diagnostics=({"reason": "odb_missing"},))

            raw_odb = self.executor.inspect_odb(path) if hasattr(
                self.executor, "inspect_odb") else None
            odb = summarize_odb(raw_odb) if raw_odb is not None else {"status": "unavailable"}
            if odb.get("status") != "available" or not odb.get("steps"):
                return run.with_state(
                    AnalysisRunState.FAILED,
                    odb_path=path,
                    engineering_status=EngineeringStatus.RESULT_INVALID.value,
                    diagnostics=({"reason": "odb_invalid", "odb": odb},),
                    evidence=(odb,))

            run = run.with_state(
                AnalysisRunState.ODB_VALIDATED,
                odb_path=path,
                engineering_status=EngineeringStatus.RESULT_SUSPICIOUS.value,
                evidence=(odb,))

            if not criteria:
                return run.with_state(AnalysisRunState.RESULTS_EXTRACTED)

            if result_values is None:
                raise ValueError("result_values required when criteria are supplied")

            from ..acceptance import evaluate_criteria
            accepted = evaluate_criteria(result_values, criteria)
            status_value = (EngineeringStatus.RESULT_VALID.value
                            if accepted.passed else EngineeringStatus.RESULT_INVALID.value)
            return run.with_state(
                AnalysisRunState.ACCEPTED if accepted.passed
                else AnalysisRunState.RESULTS_EXTRACTED,
                engineering_status=status_value,
                acceptance_passed=accepted.passed,
                evidence=(odb, accepted))
        except Exception as exc:
            return run.with_state(
                AnalysisRunState.FAILED,
                engineering_status=EngineeringStatus.EXECUTION_FAILED.value,
                diagnostics=({"error": str(exc)},))
