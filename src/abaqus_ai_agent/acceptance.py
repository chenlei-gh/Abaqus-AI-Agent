from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class CriterionResult:
    name: str
    passed: bool
    actual: float
    operator: str
    limit: float
    unit: str = ""
    relative_error: Optional[float] = None

@dataclass(frozen=True)
class AcceptanceResult:
    passed: bool
    criteria: tuple
    failures: tuple = ()
    warnings: tuple = ()

def evaluate_criteria(values, criteria):
    """Evaluate deterministic engineering acceptance criteria."""
    results, failures, warnings = [], [], []
    operators = {"<": lambda a,b: a < b, "<=": lambda a,b: a <= b, ">": lambda a,b: a > b, ">=": lambda a,b: a >= b, "==": lambda a,b: a == b}
    for c in criteria or ():
        key, op = c.get("value_key"), c.get("operator")
        if key not in values: raise KeyError("missing result value: %s" % key)
        if op not in operators: raise ValueError("unsupported operator: %s" % op)
        actual, limit = float(values[key]), float(c["limit"])
        tolerance = float(c.get("relative_tolerance", 0.0))
        if tolerance < 0: raise ValueError("relative_tolerance must be >= 0")
        effective_limit = limit
        if tolerance and op in ("<", "<="): effective_limit = limit * (1.0 + tolerance)
        elif tolerance and op in (">", ">="): effective_limit = limit * (1.0 - tolerance)
        elif tolerance: warnings.append("relative_tolerance_ignored_for_%s" % op)
        passed = operators[op](actual, effective_limit)
        denominator = max(abs(limit), 1e-30)
        item = CriterionResult(c.get("name", key), passed, actual, op, limit, c.get("unit", ""), abs(actual-limit)/denominator)
        results.append(item)
        if not passed: failures.append(item)
    return AcceptanceResult(not failures, tuple(results), tuple(failures), tuple(warnings))
