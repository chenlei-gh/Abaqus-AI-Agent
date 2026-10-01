from .contracts.benchmarks import BenchmarkCase, BenchmarkResult


def evaluate_benchmark(case, observed, acceptance):
    failures = []
    for criterion in acceptance:
        key = criterion["value_key"]
        if key not in observed:
            failures.append("missing:%s" % key)
            continue
        actual = float(observed[key])
        limit = float(criterion["limit"])
        op = criterion.get("operator", "<=")
        passed = {
            "<": actual < limit,
            "<=": actual <= limit,
            ">": actual > limit,
            ">=": actual >= limit,
            "==": actual == limit,
        }.get(op)
        if passed is not True:
            failures.append("%s:%s" % (key, op))
    return BenchmarkResult(
        case=case,
        passed=not failures,
        observed=dict(observed),
        failures=tuple(failures),
    )
