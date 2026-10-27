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


#: Kernel status tokens mapped one-to-one. Matching these exactly keeps a
#: longer token from being decided by a substring it happens to contain.
_EXACT_STATUS = {
    "UNKNOWN": JobState.UNKNOWN,
    "CREATED": JobState.CREATED,
    "SUBMITTED": JobState.SUBMITTED,
    "RUNNING": JobState.RUNNING,
    "COMPLETED": JobState.COMPLETED,
    "ABORTED": JobState.ABORTED,
    "TERMINATED": JobState.TERMINATED,
    "ERROR": JobState.ERROR,
    "TIMEOUT": JobState.TIMEOUT,
}

#: Legacy fallback for wrapped or decorated forms (e.g. ``SymbolicConstant<
#: COMPLETED>``). ``CHECK_*`` is checked first because a datacheck result must
#: never be read as an analysis result.
_LEGACY_SUBSTRING = (
    ("CHECK_COMPLETED", JobState.UNKNOWN),
    ("CHECK_RUNNING", JobState.RUNNING),
    ("COMPLETED", JobState.COMPLETED),
    ("RUNNING", JobState.RUNNING),
    ("SUBMITTED", JobState.SUBMITTED),
    ("ABORTED", JobState.ABORTED),
    ("TERMINATED", JobState.TERMINATED),
    ("ERROR", JobState.ERROR),
    ("TIMEOUT", JobState.TIMEOUT),
    ("CREATED", JobState.CREATED),
)


def wait_for_completion_code(name, timeout):
    """Build the kernel snippet that waits with a bound instead of forever.

    The Abaqus scripting reference documents an optional ``timeOut`` argument in
    seconds; without it the call blocks indefinitely, and a host-side socket or
    RPC timeout cannot stop the kernel job -- only the wait. On timeout the
    kernel raises ``AbaqusException``, so the snippet turns that into a printable
    ``TIMEOUT`` status instead of letting it surface as an opaque execution
    failure that says nothing about the job's state. Only the documented timeout
    message is mapped; any other exception propagates unchanged so a real kernel
    error is never relabelled as a timeout.
    """
    bound = max(1, int(timeout)) if timeout else 3600
    return (
        "_ai_job = mdb.jobs[%r]\n"
        "try:\n"
        "    _ai_job.waitForCompletion(timeOut=%d)\n"
        "except Exception as _ai_exc:\n"
        "    if 'timeOut' not in str(_ai_exc):\n"
        "        raise\n"
        "    _ai_status = 'TIMEOUT'\n"
        "else:\n"
        "    _ai_status = str(_ai_job.status)\n"
        "print(_ai_status)" % (name, bound)
    )


def classify_job_status(name, raw):
    value = str(raw.get("status", raw.get("state", "")) if isinstance(raw, dict) else raw or "").upper()
    token = value.strip()
    if token.startswith("SYMBOLICCONSTANT<") and token.endswith(">"):
        token = token[len("SYMBOLICCONSTANT<"):-1].strip()
    if token == "CHECK_COMPLETED":
        # A finished datacheck/syntaxcheck is not a completed analysis. The
        # token contains "COMPLETED", so substring matching would promote it.
        return JobStatus(name, JobState.UNKNOWN, raw,
                         ("CHECK_COMPLETED is a datacheck/syntaxcheck result, "
                          "not an analysis completion",))
    if token == "CHECK_RUNNING":
        return JobStatus(name, JobState.RUNNING, raw,
                         ("CHECK_RUNNING is a datacheck/syntaxcheck run",))
    if token in _EXACT_STATUS:
        return JobStatus(name, _EXACT_STATUS[token], raw)
    for marker, state in _LEGACY_SUBSTRING:
        if marker in token:
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

    def submit(self, name, wait=False, timeout=3600):
        result = self.executor.execute("from abaqusConstants import ON; mdb.jobs[%r].submit(consistencyChecking=ON)" % name)
        if not wait:
            return JobStatus(name, JobState.SUBMITTED, result)
        return self.wait(name, timeout=timeout)

    def status(self, name):
        result = self.executor.execute("print(mdb.jobs[%r].status)" % name)
        return classify_job_status(name, result)

    def wait(self, name, poll_seconds=2.0, timeout=3600):
        if hasattr(self.executor, "monitor_job"):
            raw = self.executor.monitor_job(name, timeout=timeout, poll_seconds=poll_seconds)
        else:
            raw = self.executor.execute(wait_for_completion_code(name, timeout), timeout=timeout)
        return classify_job_status(name, raw)

    def cancel(self, name):
        return self.executor.execute("mdb.jobs[%r].kill()" % name)

    def artifacts(self, name, workdir=None):
        from .artifacts import inspect_job_artifacts
        return inspect_job_artifacts(self.executor, name, workdir=workdir)

    def diagnostics(self, name, workdir=None, tail_lines=80):
        from .artifacts import inspect_job_diagnostics
        return inspect_job_diagnostics(
            self.executor, name, workdir=workdir, tail_lines=tail_lines)
