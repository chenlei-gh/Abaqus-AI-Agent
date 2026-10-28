from ..execution.client import AbaqusExecutor
from ..execution.errors import AbaqusExecutionError
from ..execution.journal import ExecutionJournal
from ..validation.preflight import preflight_action
from ..verification import verify_expected_state
from ..evidence.model import Evidence, EvidenceBundle
from ..state_diff import diff_snapshots
from .script import action_to_script


def preview(action):
    return action_to_script(action)


def _record_correction(category, stage, message, source="", metadata=None):
    """Telemetry must not change the exception the caller already earned."""
    try:
        from ..telemetry.correction import record_correction_event
        record_correction_event(
            category, stage, message=message, source=source, first_pass=False,
            metadata=metadata or {},
        )
    except Exception:
        pass


def _require_compilable(action):
    """Refuse a fragment ``compile()`` rejects before the kernel sees it.

    ``action_to_script`` can raise for illegal action parameters. That is not a
    syntax verdict and is left to the caller. Only a fragment that exists and
    fails ``compile()`` is blocked here.
    """
    from ..execution.script_syntax import check_python_source

    source = action_to_script(action)
    label = "<action:%s>" % getattr(action, "action_type", "unknown")
    error = check_python_source(source, label)
    if error is None:
        return source
    _record_correction("syntax", "action_syntax_gate", error.format(), label, error.to_dict())
    raise AbaqusExecutionError(
        error.format(), category="syntax", source_line=error.line,
        code_excerpt=error.excerpt, context=error.to_dict(),
    )


def execute(executor, action):
    """Backward-compatible execution API: returns the native bridge result."""
    if not isinstance(executor, AbaqusExecutor):
        raise TypeError("executor must implement AbaqusExecutor")
    preflight = preflight_action(action)
    if not preflight.passed:
        message = "action preflight failed: %s" % (preflight.blockers,)
        _record_correction("preflight", "action_preflight", message,
                           getattr(action, "action_type", ""))
        raise ValueError(message)
    return executor.execute(_require_compilable(action))


def execute_verified(executor, action, journal=None, snapshot_before=None,
                     snapshot_after=None):
    """Execute with journal + optional deterministic post-state verification."""
    if not isinstance(executor, AbaqusExecutor):
        raise TypeError("executor must implement AbaqusExecutor")
    preflight = preflight_action(action, snapshot_before)
    if not preflight.passed:
        message = "action preflight failed: %s" % (preflight.blockers,)
        _record_correction("preflight", "action_preflight", message,
                           getattr(action, "action_type", ""))
        raise ValueError(message)
    source = _require_compilable(action)
    journal = journal or ExecutionJournal()
    record = journal.start(action)
    try:
        result = executor.execute(source)
        verification = None
        if snapshot_after is not None and action.expected_state:
            verification = verify_expected_state(snapshot_after, action.expected_state)
            if not verification.passed:
                journal.finish(record, "VERIFICATION_FAILED", result=result,
                               error=str(verification.failures))
                raise RuntimeError("action post-verification failed: %s" %
                                   (verification.failures,))
        journal.finish(record, "COMPLETED", result=result)
        evidence = EvidenceBundle()
        if snapshot_before is not None and snapshot_after is not None:
            try:
                delta = diff_snapshots(snapshot_before, snapshot_after)
                evidence = evidence.add(Evidence(
                    kind="state_diff", source=action.action_type,
                    locator=action.target or action.parameters.get("part", ""),
                    value={"added": delta.added, "removed": delta.removed,
                           "changed_metadata": delta.changed_metadata},
                ))
            except TypeError:
                pass
        evidence = evidence.add(Evidence(
            kind="action_execution",
            source=action.action_type,
            locator=action.target or action.parameters.get("part", ""),
            value=result,
            metadata={"model": action.model_name, "requested_evidence": action.evidence},
        ))
        if verification is not None:
            evidence = evidence.add(Evidence(
                kind="post_verification",
                source=action.action_type,
                locator=action.target or action.parameters.get("part", ""),
                value={"passed": verification.passed, "failures": verification.failures},
            ))
        return {"result": result, "preflight": preflight,
                "verification": verification, "record": record,
                "evidence": evidence}
    except Exception as exc:
        if record.status == "PENDING":
            journal.finish(record, "FAILED", error=str(exc))
        raise
