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
    operators = {
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "==": lambda a, b: a == b,
    }
    for c in criteria or ():
        key, op = c.get("value_key"), c.get("operator")
        if key not in values:
            raise KeyError("missing result value: %s" % key)
        if op not in operators:
            raise ValueError("unsupported operator: %s" % op)
        actual, limit = float(values[key]), float(c["limit"])
        tolerance = float(c.get("relative_tolerance", 0.0))
        if tolerance < 0:
            raise ValueError("relative_tolerance must be >= 0")
        effective_limit = limit
        if tolerance and op in ("<", "<="):
            effective_limit = limit * (1.0 + tolerance)
        elif tolerance and op in (">", ">="):
            effective_limit = limit * (1.0 - tolerance)
        elif tolerance:
            warnings.append("relative_tolerance_ignored_for_%s" % op)
        passed = operators[op](actual, effective_limit)
        denominator = max(abs(limit), 1e-30)
        item = CriterionResult(
            c.get("name", key), passed, actual, op, limit, c.get("unit", ""),
            abs(actual - limit) / denominator
        )
        results.append(item)
        if not passed:
            failures.append(item)
    return AcceptanceResult(not failures, tuple(results), tuple(failures), tuple(warnings))


def evaluate_result_acceptance(result_status, numerical=None, engineering=None,
                               mesh_quality=None, convergence=None, fatigue=None, contact_diagnostics=None,
                               values=None, criteria=None):
    """Combine execution/result evidence with deterministic acceptance criteria.

    Missing upstream evidence prevents acceptance instead of being treated as a
    pass. Optional verification domains are gates only when supplied.
    """
    failures = []
    warnings = []
    if result_status != "completed":
        failures.append("solver_status:%s" % result_status)
    if numerical is not None and not getattr(numerical, "passed", False):
        failures.append("numerical_verification_failed")
    if engineering is not None and not getattr(engineering, "passed", False):
        failures.append("engineering_checks_failed")
    if mesh_quality is not None and getattr(mesh_quality, "status", None) not in ("pass",):
        failures.append("mesh_quality_failed")
    if convergence is not None and not getattr(convergence, "converged", False):
        failures.append("mesh_convergence_failed")
    if fatigue is not None:
        fatigue_status = getattr(fatigue, "status", None)
        if fatigue_status != "pass":
            failures.append("fatigue_verification_failed")
            if fatigue_status == "warning":
                warnings.append("fatigue_warning")
        warnings.extend(tuple(getattr(fatigue, "warnings", ()) or ()))
    if contact_diagnostics is not None:
        contact_statuses = tuple(
            getattr(d, "status", None)
            for d in getattr(contact_diagnostics, "diagnostics", ()) or ()
        )
        if not contact_statuses:
            failures.append("contact_diagnostics_insufficient_evidence")
        elif any(s not in ("pass", "not_applicable") for s in contact_statuses):
            failures.append("contact_diagnostics_failed")
        elif any(s == "not_applicable" for s in contact_statuses):
            warnings.append("contact_diagnostics_not_applicable")

    criteria_result = evaluate_criteria(values or {}, criteria or ())
    failures.extend("criterion:%s" % item.name for item in criteria_result.failures)
    warnings.extend(criteria_result.warnings)

    if not criteria and values is None:
        warnings.append("no_explicit_acceptance_criteria")

    return AcceptanceResult(
        passed=not failures,
        criteria=criteria_result.criteria,
        failures=tuple(failures),
        warnings=tuple(warnings),
    )
