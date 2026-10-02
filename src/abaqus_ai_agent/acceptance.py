from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple


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
    status: str = "PASS"  # PASS, WARNING, FAIL, BLOCKED
    blocked: tuple = ()
    gates: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "status": self.status,
            "failures": list(self.failures),
            "warnings": list(self.warnings),
            "blocked": list(self.blocked),
            "gates": dict(self.gates),
            "criteria": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "actual": c.actual,
                    "operator": c.operator,
                    "limit": c.limit,
                    "unit": c.unit,
                    "relative_error": c.relative_error,
                }
                for c in self.criteria
            ],
        }


def evaluate_criteria(values, criteria, required_keys: Optional[Sequence[str]] = None):
    """Evaluate deterministic engineering acceptance criteria."""
    results, failures, warnings, blocked = [], [], [], []
    operators = {
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "==": lambda a, b: a == b,
    }
    values_map = values or {}

    # Check required keys if supplied
    if required_keys:
        for rk in required_keys:
            if rk not in values_map:
                blocked.append("missing_required_metric:%s" % rk)

    for c in criteria or ():
        key, op = c.get("value_key"), c.get("operator")
        if key not in values_map:
            if c.get("required", True):
                blocked.append("missing_required_metric:%s" % key)
                continue
            else:
                warnings.append("missing_optional_metric:%s" % key)
                continue
        if op not in operators:
            raise ValueError("unsupported operator: %s" % op)
        actual, limit = float(values_map[key]), float(c["limit"])
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

    # Derive deterministic status
    if blocked:
        status = "BLOCKED"
        passed = False
    elif failures:
        status = "FAIL"
        passed = False
    elif warnings:
        status = "WARNING"
        passed = True
    else:
        status = "PASS"
        passed = True

    all_failures = tuple(failures) + tuple(blocked)
    return AcceptanceResult(
        passed=passed,
        criteria=tuple(results),
        failures=all_failures,
        warnings=tuple(warnings),
        status=status,
        blocked=tuple(blocked),
    )


def evaluate_result_acceptance(result_status, numerical=None, engineering=None,
                               mesh_quality=None, convergence=None, fatigue=None, contact_diagnostics=None,
                               values=None, criteria=None, required_metrics=None, evidence=None,
                               require_evidence=False):
    """Combine execution/result evidence with deterministic acceptance criteria.

    Missing upstream evidence blocks acceptance instead of being treated as a
    pass. Optional verification domains are gates only when supplied.
    """
    failures = []
    warnings = []
    blocked = []
    gates = {}

    # Gate 1: Execution Gate
    if result_status != "completed":
        failures.append("solver_status:%s" % result_status)
        blocked.append("solver_not_completed:%s" % result_status)
        gates["execution"] = "FAIL"
    else:
        gates["execution"] = "PASS"

    # Gate 2: Evidence Sufficiency Gate
    if require_evidence and not evidence:
        failures.append("missing_required_evidence")
        blocked.append("missing_required_evidence")
        gates["evidence_sufficiency"] = "BLOCKED"
    elif evidence:
        gates["evidence_sufficiency"] = "PASS"
    else:
        gates["evidence_sufficiency"] = "NOT_SPECIFIED"

    # Gate 3: Numerical Verification Gate
    if numerical is not None:
        if getattr(numerical, "passed", False):
            gates["numerical_verification"] = "PASS"
        else:
            failures.append("numerical_verification_failed")
            gates["numerical_verification"] = "FAIL"
    else:
        gates["numerical_verification"] = "SKIPPED"

    # Gate 4: Engineering Checks Gate
    if engineering is not None:
        if getattr(engineering, "passed", False):
            gates["engineering_checks"] = "PASS"
        else:
            failures.append("engineering_checks_failed")
            gates["engineering_checks"] = "FAIL"
    else:
        gates["engineering_checks"] = "SKIPPED"

    # Gate 5: Mesh Quality Gate
    if mesh_quality is not None:
        mq_status = mesh_quality.get("status") if isinstance(mesh_quality, dict) else getattr(mesh_quality, "status", None)
        if mq_status in ("pass",):
            gates["mesh_quality"] = "PASS"
        else:
            failures.append("mesh_quality_failed")
            gates["mesh_quality"] = "FAIL"
    else:
        gates["mesh_quality"] = "SKIPPED"

    # Gate 6: Convergence Gate
    if convergence is not None:
        if getattr(convergence, "converged", False):
            gates["convergence"] = "PASS"
        else:
            failures.append("mesh_convergence_failed")
            gates["convergence"] = "FAIL"
    else:
        gates["convergence"] = "SKIPPED"

    # Gate 7: Fatigue Gate
    if fatigue is not None:
        fatigue_status = getattr(fatigue, "status", None)
        if fatigue_status == "pass":
            gates["fatigue"] = "PASS"
        else:
            failures.append("fatigue_verification_failed")
            gates["fatigue"] = "FAIL"
            if fatigue_status == "warning":
                warnings.append("fatigue_warning")
        warnings.extend(tuple(getattr(fatigue, "warnings", ()) or ()))
    else:
        gates["fatigue"] = "SKIPPED"

    # Gate 8: Contact Diagnostics Gate
    if contact_diagnostics is not None:
        contact_statuses = tuple(
            getattr(d, "status", None)
            for d in getattr(contact_diagnostics, "diagnostics", ()) or ()
        )
        if not contact_statuses:
            failures.append("contact_diagnostics_insufficient_evidence")
            blocked.append("contact_diagnostics_insufficient_evidence")
            gates["contact"] = "BLOCKED"
        elif any(s not in ("pass", "not_applicable") for s in contact_statuses):
            failures.append("contact_diagnostics_failed")
            gates["contact"] = "FAIL"
        elif any(s == "not_applicable" for s in contact_statuses):
            warnings.append("contact_diagnostics_not_applicable")
            gates["contact"] = "WARNING"
        else:
            gates["contact"] = "PASS"
    else:
        gates["contact"] = "SKIPPED"

    # Gate 9: Criteria Gate
    criteria_result = evaluate_criteria(values or {}, criteria or (), required_keys=required_metrics)
    failures.extend(
        "criterion:%s" % item.name for item in criteria_result.criteria if not item.passed
    )
    warnings.extend(criteria_result.warnings)
    blocked.extend(criteria_result.blocked)
    if criteria_result.blocked:
        gates["criteria"] = "BLOCKED"
    elif any(not item.passed for item in criteria_result.criteria):
        gates["criteria"] = "FAIL"
    elif criteria:
        gates["criteria"] = "PASS"
    else:
        gates["criteria"] = "SKIPPED"

    if not criteria and values is None:
        warnings.append("no_explicit_acceptance_criteria")

    # Final deterministic status synthesis
    if blocked:
        status = "BLOCKED"
        passed = False
    elif failures:
        status = "FAIL"
        passed = False
    elif warnings:
        status = "WARNING"
        passed = True
    else:
        status = "PASS"
        passed = True

    return AcceptanceResult(
        passed=passed,
        criteria=criteria_result.criteria,
        failures=tuple(failures),
        warnings=tuple(warnings),
        status=status,
        blocked=tuple(blocked),
        gates=gates,
    )
