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


def benchmark_result_criteria(case, result_overrides=None):
    """Build deterministic ODB result requirements for an executable benchmark."""
    criteria = []
    overrides = dict(result_overrides or {})
    for criterion in case.acceptance:
        source = dict(criterion.get("result") or {})
        source.update(dict(overrides.get(criterion["value_key"], {}) or {}))
        source_key = criterion.get("observed_value_key", criterion["value_key"])
        source["value_key"] = source_key
        source.setdefault("name", source_key)
        source["operator"] = criterion.get("operator", "<=")
        source["limit"] = criterion.get("limit", 0.0)
        criteria.append(source)
    return tuple(criteria)


def derive_benchmark_observations(case, result_values, reference_values=None):
    """Derive explicit benchmark metrics from extracted ODB values."""
    references = dict(reference_values or {})
    observed, evidence, failures = {}, [], []
    for criterion in case.acceptance:
        key = criterion["value_key"]
        source_key = criterion.get("observed_value_key", key)
        if source_key not in result_values:
            failures.append("missing:%s" % source_key)
            evidence.append({"value_key": key, "status": "missing"})
            continue
        actual = float(result_values[source_key])
        metric = criterion.get("metric")
        if metric is None:
            observed[key] = actual
            evidence.append({"value_key": key, "actual": actual, "metric": "identity", "status": "available"})
            continue
        if metric not in ("relative_error", "absolute_error"):
            raise ValueError("unsupported benchmark metric: %s" % metric)
        reference_key = criterion.get("reference_key", key)
        if reference_key not in references:
            failures.append("missing_reference:%s" % reference_key)
            evidence.append({"value_key": key, "reference_key": reference_key, "status": "missing_reference"})
            continue
        reference_record = references[reference_key]
        if isinstance(reference_record, dict):
            if "value" not in reference_record:
                failures.append("invalid_reference:%s" % reference_key)
                evidence.append({
                    "value_key": key, "reference_key": reference_key,
                    "status": "invalid_reference",
                })
                continue
            reference = float(reference_record["value"])
            reference_source = reference_record.get("source")
            reference_unit = reference_record.get("unit")
        else:
            reference = float(reference_record)
            reference_source = None
            reference_unit = None
        if metric == "relative_error":
            if reference == 0.0:
                failures.append("zero_reference_requires_absolute_error:%s" % reference_key)
                evidence.append({
                    "value_key": key, "reference_key": reference_key,
                    "status": "invalid_reference", "reason": "zero_reference",
                })
                continue
            value = abs(actual - reference) / abs(reference)
        else:
            value = abs(actual - reference)
        observed[key] = value
        evidence.append({
            "value_key": key, "actual": actual, "reference": reference,
            "reference_key": reference_key, "reference_source": reference_source,
            "reference_unit": reference_unit, "metric": metric,
            "derived": value, "status": "available",
        })
    return observed, tuple(evidence), tuple(failures)


def evaluate_benchmark(case, observed, acceptance=None, pre_failures=()):
    """Evaluate deterministic benchmark criteria without inferring physics."""
    acceptance = tuple(acceptance if acceptance is not None else case.acceptance)
    failures = list(pre_failures)
    evidence = []
    for criterion in acceptance:
        key = criterion["value_key"]
        if key not in observed:
            derived_failure = any(
                failure.endswith(":%s" % key)
                for failure in failures
                if failure.startswith(("missing_reference:", "zero_reference_requires_absolute_error:"))
            )
            if not derived_failure and "missing:%s" % key not in failures:
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
    failures = tuple(dict.fromkeys(failures))
    return BenchmarkResult(
        case=case,
        passed=not failures,
        observed=dict(observed),
        failures=tuple(failures),
        evidence=tuple(evidence),
    )
