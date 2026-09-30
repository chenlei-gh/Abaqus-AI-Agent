import json, uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple
from .jobs import JobController, JobState, JobStatus

class AnalysisRunState(str, Enum):
    CREATED="created"; PREFLIGHTED="preflighted"; SUBMITTED="submitted"; RUNNING="running"
    COMPLETED="completed"; ODB_VALIDATED="odb_validated"; RESULTS_EXTRACTED="results_extracted"
    ACCEPTED="accepted"; FAILED="failed"

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
        values=dict(id=self.id,model_name=self.model_name,job_name=self.job_name,state=state,
                    job_status=self.job_status,odb_path=self.odb_path,
                    engineering_status=self.engineering_status,acceptance_passed=self.acceptance_passed,
                    evidence=self.evidence,diagnostics=self.diagnostics,metadata=dict(self.metadata))
        values.update(changes); return AnalysisRun(**values)

    @property
    def solver_completed(self):
        return self.job_status is not None and self.job_status.state == JobState.COMPLETED


def discover_odb(executor, job_name):
    """Best-effort discovery; returns a path only when the file exists."""
    raw=executor.execute("import os; print(os.path.abspath(%r + '.odb') if os.path.exists(%r + '.odb') else '')" % (job_name, job_name))
    if isinstance(raw,dict):
        for key in ("path","odb_path","stdout","output"):
            value=raw.get(key)
            if isinstance(value,str) and value.strip(): return value.strip()
    if isinstance(raw,str) and raw.strip(): return raw.strip()
    return None


class AnalysisRunner:
    """Thin lifecycle orchestrator: job -> ODB -> results -> acceptance."""
    def __init__(self, executor): self.executor=executor

    def run(self, model_name, job_name, odb_path=None, criteria=(), result_values=None, timeout=3600):
        run=AnalysisRun(str(uuid.uuid4()), model_name, job_name, AnalysisRunState.PREFLIGHTED)
        jobs=JobController(self.executor)
        try:
            snapshot = self.executor.snapshot() if hasattr(self.executor, "snapshot") else None
            if snapshot is not None and job_name not in snapshot.jobs:
                jobs.create(job_name, model_name)
            status=jobs.submit(job_name, wait=True)
            run=run.with_state(AnalysisRunState.COMPLETED if status.state == JobState.COMPLETED else AnalysisRunState.FAILED,
                               job_status=status)
            if status.state != JobState.COMPLETED:
                return run
            path=odb_path or discover_odb(self.executor, job_name)
            if not path:
                return run.with_state(AnalysisRunState.FAILED, diagnostics=({"reason":"odb_missing"},))
            from .odb import inspect_odb
            odb=inspect_odb(self.executor, path)
            run=run.with_state(AnalysisRunState.ODB_VALIDATED, odb_path=path,
                               evidence=(odb,))
            if criteria:
                from ..acceptance import evaluate_criteria
                if result_values is None: raise ValueError("result_values required when criteria are supplied")
                accepted=evaluate_criteria(result_values, criteria)
                return run.with_state(AnalysisRunState.ACCEPTED if accepted.passed else AnalysisRunState.RESULTS_EXTRACTED,
                                      acceptance_passed=accepted.passed, evidence=(odb, accepted))
            return run.with_state(AnalysisRunState.RESULTS_EXTRACTED)
        except Exception as exc:
            return run.with_state(AnalysisRunState.FAILED, diagnostics=({"error":str(exc)},))
