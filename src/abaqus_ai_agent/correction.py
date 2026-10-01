from .contracts.correction import CorrectionAttempt, CorrectionPolicy, RepairCandidate


def select_repairs(diagnostic_class, candidates, policy=None):
    policy = policy or CorrectionPolicy()
    if diagnostic_class not in policy.allowed_diagnostics:
        return ()
    return tuple(
        candidate for candidate in candidates
        if isinstance(candidate, RepairCandidate)
        and candidate.diagnostic_class == diagnostic_class
    )


def can_apply_repair(candidate, confirmed=False):
    if not isinstance(candidate, RepairCandidate):
        raise TypeError("candidate must be a RepairCandidate")
    return bool(confirmed) if candidate.requires_confirmation else True


def can_retry(attempt, policy=None):
    policy = policy or CorrectionPolicy()
    return int(attempt) < policy.max_attempts


def record_attempt(attempt, diagnostic_class, repair=None, status="proposed",
                   diagnostics=(), confirmed=False, policy=None):
    policy = policy or CorrectionPolicy()
    retry_allowed = can_retry(attempt, policy) and confirmed
    return CorrectionAttempt(
        attempt=int(attempt), diagnostic_class=diagnostic_class, repair=repair,
        status=status, diagnostics=tuple(diagnostics),
        confirmed=bool(confirmed), retry_allowed=retry_allowed,
    )


def execute_authorized_correction(
    executor, runner, candidate, model_name, job_name, attempt=0,
    confirmed=False, policy=None, runner_kwargs=None,
):
    """Execute one confirmed repair and require the rerun to pass acceptance.

    The repair must be an existing Action and confirmation is explicit. The
    rerun stays on the normal AnalysisRunner path. Solver/ODB completion alone
    is not treated as correction success.
    """
    policy = policy or CorrectionPolicy()
    if not isinstance(candidate, RepairCandidate):
        raise TypeError("candidate must be a RepairCandidate")
    if candidate.diagnostic_class not in policy.allowed_diagnostics:
        raise ValueError(
            "correction diagnostic is not allowed by policy: %s"
            % candidate.diagnostic_class
        )
    if not can_retry(attempt, policy):
        raise ValueError("correction attempt exceeds policy max_attempts")
    if not can_apply_repair(candidate, confirmed=confirmed):
        raise PermissionError("explicit correction confirmation required")

    payload = candidate.action or {}
    action = payload.get("action")
    actions = payload.get("actions")
    if action is not None and actions is not None:
        raise ValueError("candidate action must use either 'action' or 'actions'")
    if action is not None:
        actions = (action,)
    actions = tuple(actions or ())
    if not actions:
        raise ValueError("candidate action must contain an existing Action")

    from .actions.runner import execute as execute_action

    authorized = record_attempt(
        attempt, candidate.diagnostic_class, candidate.name,
        status="authorized", confirmed=True, policy=policy,
    )
    action_results = []
    try:
        for repair_action in actions:
            action_results.append(execute_action(executor, repair_action))
    except Exception as exc:
        failed = record_attempt(
            attempt, candidate.diagnostic_class, candidate.name,
            status="failed",
            diagnostics=({"reason": "repair_action_failed", "error": str(exc)},),
            confirmed=True, policy=policy,
        )
        return {
            "attempt": failed, "authorized": authorized,
            "action_results": tuple(action_results), "run": None,
        }

    try:
        run = runner.run(model_name, job_name, **dict(runner_kwargs or {}))
    except Exception as exc:
        failed = record_attempt(
            attempt, candidate.diagnostic_class, candidate.name,
            status="failed",
            diagnostics=({"reason": "analysis_run_failed", "error": str(exc)},),
            confirmed=True, policy=policy,
        )
        return {
            "attempt": failed, "authorized": authorized,
            "action_results": tuple(action_results), "run": None,
        }

    state = getattr(run, "state", None)
    state = getattr(state, "value", state)
    acceptance = getattr(run, "acceptance_passed", None)
    if state == "accepted" and acceptance is True:
        final_status = "completed"
    elif state == "failed" or acceptance is False:
        final_status = "failed"
    else:
        final_status = "verification_pending"
    final = record_attempt(
        attempt, candidate.diagnostic_class, candidate.name,
        status=final_status,
        diagnostics=getattr(run, "diagnostics", ()),
        confirmed=True, policy=policy,
    )
    return {
        "attempt": final, "authorized": authorized,
        "action_results": tuple(action_results), "run": run,
    }
