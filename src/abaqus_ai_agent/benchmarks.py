from .contracts.benchmarks import BenchmarkCase, BenchmarkResult


_OPERATORS = {
    "<": lambda actual, limit: actual < limit,
    "<=": lambda actual, limit: actual <= limit,
    ">": lambda actual, limit: actual > limit,
    ">=": lambda actual, limit: actual >= limit,
    "==": lambda actual, limit: actual == limit,
}


def _criterion_passes(actual, criterion):
    operator = criterion.get("operator", "<=")
    if operator not in _OPERATORS:
        raise ValueError("unsupported benchmark operator: %s" % operator)
    limit = float(criterion["limit"])
    tolerance = float(criterion.get("relative_tolerance", 0.0))
    if tolerance < 0:
        raise ValueError("relative_tolerance must be >= 0")
    if operator in ("<", "<="):
        effective_limit = limit * (1.0 + tolerance)
    elif operator in (">", ">="):
        effective_limit = limit * (1.0 - tolerance)
    else:
        if tolerance:
            return abs(actual - limit) <= max(abs(limit), 1e-30) * tolerance
        effective_limit = limit
    return _OPERATORS[operator](actual, effective_limit)


def evaluate_benchmark(case, observed, acceptance):
    """Evaluate deterministic benchmark criteria without inferring physics."""
    failures = []
    evidence = []
    for criterion in acceptance:
        key = criterion["value_key"]
        if key not in observed:
            failures.append("missing:%s" % key)
            evidence.append({"value_key": key, "status": "missing"})
            continue
        actual = float(observed[key])
        passed = _criterion_passes(actual, criterion)
        evidence.append({
            "value_key": key,
            "actual": actual,
            "limit": float(criterion["limit"]),
            "operator": criterion.get("operator", "<="),
            "relative_tolerance": float(criterion.get("relative_tolerance", 0.0)),
            "passed": passed,
        })
        if not passed:
            failures.append("%s:%s" % (key, criterion.get("operator", "<=")))
    return BenchmarkResult(
        case=case,
        passed=not failures,
        observed=dict(observed),
        failures=tuple(failures),
        evidence=tuple(evidence),
    )
