from ..execution.client import AbaqusExecutor
from ..execution.journal import ExecutionJournal
from ..validation.preflight import preflight_action
from ..verification import verify_expected_state
from ..evidence.model import Evidence, EvidenceBundle
from ..state_diff import diff_snapshots
from .script import action_to_script


def preview(action):
    return action_to_script(action)


def execute(executor, action):
    """Backward-compatible execution API: returns the native bridge result."""
    if not isinstance(executor, AbaqusExecutor):
        raise TypeError("executor must implement AbaqusExecutor")
    preflight = preflight_action(action)
    if not preflight.passed:
        raise ValueError("action preflight failed: %s" % (preflight.blockers,))
    return executor.execute(action_to_script(action))


def execute_verified(executor, action, journal=None, snapshot_before=None,
                     snapshot_after=None):
    """Execute with journal + optional deterministic post-state verification."""
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
        # Native mesh verification is already the authoritative quality check.
        # Preserve its raw result as a typed evidence item instead of converting
        # it into a synthetic score or silently treating execution as quality.
        if action.action_type == "verify_mesh_quality":
            evidence = evidence.add(Evidence(
                kind="mesh_quality_verification",
                source="abaqus_native_verify",
                locator=action.parameters.get("part", ""),
                value=result,
                metadata={
                    "model": action.model_name,
                    "criterion": action.parameters.get("criterion", "ANALYSIS_CHECKS"),
                    "threshold": action.parameters.get("threshold"),
                    "element_shape": action.parameters.get("elem_shape"),
                    "regions_expression": action.parameters.get("regions_expression"),
                },
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
