from dataclasses import dataclass
from enum import Enum


class JobState(str, Enum):
    UNKNOWN = "UNKNOWN"
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    TERMINATED = "TERMINATED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class JobStatus:
    name: str
    state: JobState
    raw: object = None
    diagnostics: tuple = ()


def classify_job_status(name, raw):
    value = str(raw.get("status", raw.get("state", "")) if isinstance(raw, dict) else raw or "").upper()
    for marker, state in (
        ("COMPLETED", JobState.COMPLETED), ("RUNNING", JobState.RUNNING),
        ("SUBMITTED", JobState.SUBMITTED), ("ABORTED", JobState.ABORTED),
        ("TERMINATED", JobState.TERMINATED), ("ERROR", JobState.ERROR),
        ("TIMEOUT", JobState.TIMEOUT), ("CREATED", JobState.CREATED)):
        if marker in value:
            return JobStatus(name, state, raw)
    return JobStatus(name, JobState.UNKNOWN, raw)


class JobController:
    """Thin orchestration wrapper; solver behavior remains in the bridge."""

    def __init__(self, executor):
        self.executor = executor

    def create(self, name, model, **kwargs):
        code = "mdb.Job(name=%r, model=%r" % (name, model)
        for key, value in sorted(kwargs.items()):
            code += ", %s=%r" % (key, value)
        return self.executor.execute(code + ")")

    def submit(self, name, wait=False):
        result = self.executor.execute("mdb.jobs[%r].submit(consistencyChecking=OFF)" % name)
        if not wait:
            return JobStatus(name, JobState.SUBMITTED, result)
        return self.wait(name)

    def status(self, name):
        result = self.executor.execute("print(mdb.jobs[%r].status)" % name)
        return classify_job_status(name, result)

    def wait(self, name, poll_seconds=2.0, timeout=3600):
        if hasattr(self.executor, "monitor_job"):
            raw = self.executor.monitor_job(name, timeout=timeout, poll_seconds=poll_seconds)
        else:
            raw = self.executor.execute("print(mdb.jobs[%r].status)" % name, timeout=timeout)
        return classify_job_status(name, raw)

    def cancel(self, name):
        return self.executor.execute("mdb.jobs[%r].kill()" % name)
