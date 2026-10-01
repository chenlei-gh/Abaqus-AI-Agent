from .contracts.correction import CorrectionPolicy, RepairCandidate


def select_repairs(diagnostic_class, candidates, policy=None):
    policy = policy or CorrectionPolicy()
    if diagnostic_class not in policy.allowed_diagnostics:
        return ()
    return tuple(
        candidate for candidate in candidates
        if isinstance(candidate, RepairCandidate)
        and candidate.diagnostic_class == diagnostic_class
    )


def can_retry(attempt, policy=None):
    policy = policy or CorrectionPolicy()
    return int(attempt) < policy.max_attempts
