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
