from dataclasses import dataclass


@dataclass(frozen=True)
class CriterionResult:
    name: str
    passed: bool
    actual: float
    operator: str
    limit: float
    unit: str = ""


@dataclass(frozen=True)
class AcceptanceResult:
    passed: bool
    criteria: tuple
    failures: tuple = ()


def evaluate_criteria(values, criteria):
    """Evaluate deterministic engineering acceptance criteria.

    A criterion is {name, value_key, operator, limit, unit}. Values must be
    supplied by an ODB/result extractor; this function never estimates them.
    """
    results, failures = [], []
    operators = {
        "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
        "==": lambda a, b: a == b,
    }
    for c in criteria or ():
        key = c.get("value_key")
        op = c.get("operator")
        if key not in values:
            raise KeyError("missing result value: %s" % key)
        if op not in operators:
            raise ValueError("unsupported operator: %s" % op)
        actual, limit = float(values[key]), float(c["limit"])
        passed = operators[op](actual, limit)
        item = CriterionResult(c.get("name", key), passed, actual, op, limit,
                               c.get("unit", ""))
        results.append(item)
        if not passed:
            failures.append(item)
    return AcceptanceResult(not failures, tuple(results), tuple(failures))
