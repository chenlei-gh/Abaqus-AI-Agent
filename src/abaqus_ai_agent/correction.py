from .contracts.correction import CorrectionPolicy, RepairCandidate


def select_repairs(diagnostic_class, candidates, policy=None):
    """Return policy-allowed repair candidates without authorizing execution."""
    policy = policy or CorrectionPolicy()
    if diagnostic_class not in policy.allowed_diagnostics:
        return ()
    return tuple(
        candidate for candidate in candidates
        if isinstance(candidate, RepairCandidate)
        and candidate.diagnostic_class == diagnostic_class
    )


def can_apply_repair(candidate, confirmed=False):
    """Gate repair execution; confirmation is mandatory by default."""
    if not isinstance(candidate, RepairCandidate):
        raise TypeError("candidate must be a RepairCandidate")
    return bool(confirmed) if candidate.requires_confirmation else True


def can_retry(attempt, policy=None):
    policy = policy or CorrectionPolicy()
    return int(attempt) < policy.max_attempts


def record_attempt(attempt, diagnostic_class, repair=None, status="proposed",
                   diagnostics=(), confirmed=False, policy=None):
    """Create an explicit correction-attempt evidence record.

    The record never executes a repair. Confirmation and retry eligibility are
    captured so a later executor cannot confuse proposal with authorization.
    """
    from .contracts.correction import CorrectionAttempt
    policy = policy or CorrectionPolicy()
    retry_allowed = can_retry(attempt, policy) and confirmed
    return CorrectionAttempt(
        attempt=int(attempt),
        diagnostic_class=diagnostic_class,
        repair=repair,
        status=status,
        diagnostics=tuple(diagnostics),
        confirmed=bool(confirmed),
        retry_allowed=retry_allowed,
    )
