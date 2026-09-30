from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple
from .jobs import JobState, JobStatus

class AnalysisRunState(str, Enum):
    CREATED="created"; PREFLIGHTED="preflighted"; SUBMITTED="submitted"; RUNNING="running"
    COMPLETED="completed"; ODB_VALIDATED="odb_validated"; RESULTS_EXTRACTED="results_extracted"
    ACCEPTED="accepted"; FAILED="failed"

@dataclass(frozen=True)
class AnalysisRun:
    """End-to-end analysis lifecycle record; solver policy stays outside this contract."""
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
