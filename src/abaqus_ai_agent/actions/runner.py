from ..execution.client import AbaqusExecutor
from ..execution.journal import ExecutionJournal
from ..validation.preflight import preflight_action
from ..verification import verify_expected_state
from .script import action_to_script


def preview(action):
    return action_to_script(action)


def execute(executor, action, journal=None, snapshot_before=None, snapshot_after=None):
    if not isinstance(executor, AbaqusExecutor):
        raise TypeError("executor must implement AbaqusExecutor")
    preflight = preflight_action(action, snapshot_before)
    if not preflight.passed:
        raise ValueError("action preflight failed: %s" % (preflight.blockers,))
    journal = journal or ExecutionJournal()
    record = journal.start(action)
    try:
        result = executor.execute(action_to_script(action))
        verification = None
        if snapshot_after is not None and action.expected_state:
            verification = verify_expected_state(snapshot_after, action.expected_state)
            if not verification.passed:
                journal.finish(record, "VERIFICATION_FAILED", result=result,
                               error=str(verification.failures))
                raise ValueError("action post-verification failed: %s" %
                                 (verification.failures,))
        journal.finish(record, "COMPLETED", result=result)
        return {"result": result, "preflight": preflight, "verification": verification,
                "record": record}
    except Exception as exc:
        journal.finish(record, "FAILED", error=str(exc))
        raise
