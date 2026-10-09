from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

# Canonical order of engineering gates G1 ~ G14 plus composite required_results
CANONICAL_GATE_ORDER = (
    "execution",              # Gate 1
    "odb",                    # Gate 2
    "evidence_sufficiency",   # Gate 3
    "numerical_verification", # Gate 4
    "engineering_checks",     # Gate 5
    "mesh_quality",           # Gate 6
    "convergence",            # Gate 7
    "fatigue",                # Gate 8
    "contact",                # Gate 9
    "procedure",              # Gate 10
    "thermal_balance",        # Gate 11
    "criteria",               # Gate 12
    "connector_kinematics",   # Gate 13
    "fmbd_dynamics",          # Gate 14
    "required_results",       # Composite Results Gate
)


class ResultValidity(str):
    """String subclass representing result validity while maintaining backward compatibility with RESULT_INVALID."""
    def __eq__(self, other):
        if str.__eq__(self, str(other)):
            return True
        if other == "RESULT_INVALID" and str(self) in (
            "RESULT_INVALID",
            "EVIDENCE_TAMPERED",
            "EVIDENCE_CORRUPT",
            "EVIDENCE_STALE",
            "INCOMPLETE",
        ):
            return True
        return False

    def __hash__(self):
        return str.__hash__(self)


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
class AcceptanceFindings:
    failures: tuple = ()
    blocked: tuple = ()
    evidence_errors: tuple = ()
    warnings: tuple = ()
    missing_gates: tuple = ()


@dataclass(frozen=True)
class AcceptanceResult:
    passed: bool
    criteria: tuple
    failures: tuple = ()
    warnings: tuple = ()
    status: str = "PASS"  # PASS, WARNING, FAIL, BLOCKED, RESULT_INVALID
    blocked: tuple = ()
    gates: Dict[str, Any] = field(default_factory=dict)
    gate_justifications: Dict[str, str] = field(default_factory=dict)
    missing_required_metrics: tuple = ()
    missing_required_gates: tuple = ()
    missing_required_fields: tuple = ()
    result_validity: str = "VALID"  # VALID, RESULT_INVALID, SOLVER_FAILED, CRITERIA_FAILED, EVIDENCE_TAMPERED, EVIDENCE_CORRUPT, EVIDENCE_STALE, INCOMPLETE
    audit_summary: str = ""
    odb_status: str = "valid"
    evidence_status: str = "NOT_SPECIFIED"  # VALID, TAMPERED, INCOMPLETE, STALE, MISSING, NOT_SPECIFIED
    acceptance_status: str = "PASS"  # Decoupled acceptance status: PASS | FAIL | BLOCKED | RESULT_INVALID
    deliverable: bool = False  # Strictly True iff acceptance_status == "PASS" and result_validity == "VALID"
    findings: AcceptanceFindings = field(default_factory=AcceptanceFindings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "status": self.status,
            "acceptance_status": self.acceptance_status,
            "deliverable": self.deliverable,
            "result_validity": self.result_validity,
            "audit_summary": self.audit_summary,
            "odb_status": self.odb_status,
            "evidence_status": self.evidence_status,
            "failures": list(self.failures),
            "warnings": list(self.warnings),
            "blocked": list(self.blocked),
            "missing_required_metrics": list(self.missing_required_metrics),
            "missing_required_gates": list(self.missing_required_gates),
            "missing_required_fields": list(self.missing_required_fields),
            "gates": dict(self.gates),
            "gate_justifications": dict(self.gate_justifications),
            "findings": {
                "failures": list(self.findings.failures),
                "blocked": list(self.findings.blocked),
                "evidence_errors": list(self.findings.evidence_errors),
                "warnings": list(self.findings.warnings),
                "missing_gates": list(self.findings.missing_gates),
            },
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

    # Derive deterministic status: physical failures take absolute precedence
    if failures and blocked:
        status = "FAIL"
        passed = False
    elif failures:
        status = "FAIL"
        passed = False
    elif blocked:
        status = "BLOCKED"
        passed = False
    elif warnings:
        status = "WARNING"
        passed = True
    else:
        status = "PASS"
        passed = True

    failure_names = tuple(f.name if hasattr(f, "name") else str(f) for f in failures)
    findings = AcceptanceFindings(
        failures=failure_names,
        blocked=tuple(blocked),
        warnings=tuple(warnings),
    )
    all_failures = tuple(failures) + tuple(blocked)
    return AcceptanceResult(
        passed=passed,
        criteria=tuple(results),
        failures=all_failures,
        warnings=tuple(warnings),
        status=status,
        blocked=tuple(blocked),
        acceptance_status=status,
        deliverable=(status == "PASS"),
        findings=findings,
    )


def evaluate_result_acceptance(result_status, numerical=None, engineering=None,
                               mesh_quality=None, convergence=None, fatigue=None, contact_diagnostics=None,
                               values=None, criteria=None, required_metrics=None, evidence=None,
                               require_evidence=False,
                               required_gates=None, physics_domain=None, result_requirements=None,
                               odb_status=None, gate_justifications=None, procedure_verification=None,
                               thermal_balance=None, connector_kinematics=None, fmbd_dynamics=None, odb_fields=None, required_fields=None,
                               evidence_manifest=None, expected_run_id=None, base_dir=None,
                               max_age_seconds=None, mandatory_roles=None):
    """Combine execution/result evidence with deterministic acceptance criteria.

    - ResultRequirement & Physics Domain profile drive mandatory gates & required metrics.
    - Mandatory gates can NEVER be silently SKIPPED (missing mandatory gate -> BLOCKED / RESULT_INVALID).
    - Non-mandatory gates may be SKIPPED with an explicit engineering justification.
    - Missing required outputs block acceptance and mark result_validity as RESULT_INVALID.
    - EvidenceManifestV2 cryptographically verified against tampering, stale reuse, and missing files.
    - Produces a tamper-proof audit_summary: Solver PASS/FAIL | ODB PASS/FAIL | Required Result PASS/FAIL | Engineering Acceptance PASS/FAIL.
    """
    from .contracts.results import get_physics_result_profile

    failures = []
    warnings = []
    blocked = []
    evidence_errors = []
    gates = {}
    missing_required_gates = []
    missing_required_metrics = []
    missing_required_fields = []

    effective_required_gates = set(required_gates or ())
    effective_required_metrics = list(required_metrics or ())
    effective_required_fields = list(required_fields or ())
    effective_justifications = dict(gate_justifications or {})

    # If physics_domain is specified, incorporate canonical domain profile
    if physics_domain:
        prof = get_physics_result_profile(physics_domain)
        effective_required_gates.update(prof.required_gates)
        for rm in prof.required_metrics:
            if rm not in effective_required_metrics:
                effective_required_metrics.append(rm)
        for rf in getattr(prof, "required_fields", ()) or ():
            if rf not in effective_required_fields:
                effective_required_fields.append(rf)
        for g_k, g_v in prof.gate_justifications.items():
            effective_justifications.setdefault(g_k, g_v)

    # If result_requirements are supplied, extract required output identifiers
    if result_requirements:
        for r in result_requirements:
            req_name = getattr(r, "name", None) or (r.get("name") if isinstance(r, dict) else None)
            req_key = getattr(r, "value_key", None) or (r.get("value_key") if isinstance(r, dict) else None)
            is_req = getattr(r, "required", True) if hasattr(r, "required") else (r.get("required", True) if isinstance(r, dict) else True)
            if is_req:
                m_ident = req_name or req_key
                if m_ident and m_ident not in effective_required_metrics:
                    effective_required_metrics.append(m_ident)

    # Gate 1: Execution Gate
    if result_status != "completed":
        failures.append("solver_status:%s" % result_status)
        blocked.append("solver_not_completed:%s" % result_status)
        if result_status in ("unsubmitted", "probe_only"):
            evidence_errors.append("solver_execution:job_not_submitted")
        gates["execution"] = "FAIL"
    else:
        gates["execution"] = "PASS"

    # Gate 2: ODB Status Gate
    effective_odb_status = "valid" if (odb_status is None and result_status == "completed") else str(odb_status or "unavailable")
    if odb_status is not None:
        if str(odb_status).lower() in ("valid", "completed", "available"):
            gates["odb"] = "PASS"
        else:
            failures.append("odb_status:%s" % odb_status)
            blocked.append("odb_status:%s" % odb_status)
            gates["odb"] = "FAIL"
    elif "odb" in effective_required_gates:
        if result_status == "completed":
            gates["odb"] = "PASS"
        else:
            gates["odb"] = "BLOCKED"
            failures.append("missing_required_odb")
            blocked.append("missing_required_odb")
            missing_required_gates.append("odb")
    else:
        gates["odb"] = "PASS" if result_status == "completed" else "NOT_SPECIFIED"

    def _is_v2_manifest(target):
        if target is None:
            return False
        if hasattr(target, "schema_version") and getattr(target, "schema_version") == "evidence_manifest_v2":
            return True
        if isinstance(target, dict) and (
            target.get("schema_version") == "evidence_manifest_v2"
            or ("artifacts" in target and "run_id" in target and isinstance(target.get("artifacts"), dict))
        ):
            return True
        return False

    # Gate 3: Evidence Sufficiency Gate
    manifest_target = evidence_manifest
    if manifest_target is None and evidence is not None:
        if _is_v2_manifest(evidence) or isinstance(evidence, dict):
            manifest_target = evidence
    evidence_status = "NOT_SPECIFIED"

    if manifest_target is not None:
        if _is_v2_manifest(manifest_target):
            from .contracts.evidence import verify_evidence_integrity
            m_roles = mandatory_roles if mandatory_roles is not None else ("inp", "odb", "msg", "dat", "sta", "log")
            verif_rep = verify_evidence_integrity(
                manifest_target,
                base_dir=base_dir,
                expected_run_id=expected_run_id,
                max_age_seconds=max_age_seconds,
                mandatory_roles=m_roles,
            )
            evidence_status = verif_rep.validity
            if not verif_rep.valid:
                gates["evidence_sufficiency"] = "FAIL"
                failures.extend(verif_rep.failures)
                blocked.extend(verif_rep.failures)
                evidence_errors.extend(verif_rep.failures)
            else:
                gates["evidence_sufficiency"] = "PASS"
        elif isinstance(manifest_target, dict) and (
            manifest_target.get("manifest_version") == "1.0"
            or manifest_target.get("rc_evidence_eligible") is False
            or manifest_target.get("schema_version") == "golden_matrix_manifest_v1"
        ):
            from .contracts.evidence import verify_evidence_integrity
            verif_rep = verify_evidence_integrity(manifest_target)
            gates["evidence_sufficiency"] = "FAIL"
            rep_failures = verif_rep.failures or ("unsupported_legacy_manifest:schema_v1_deprecated_for_rc",)
            failures.extend(rep_failures)
            blocked.extend(rep_failures)
            evidence_errors.extend(rep_failures)
            evidence_status = verif_rep.validity or "INVALID"
        else:
            # Bare unvalidated dictionary or unsupported evidence format: FAIL CLOSED
            err = "unsupported_evidence_format:bare_dict_not_permitted"
            failures.append(err)
            blocked.append(err)
            evidence_errors.append(err)
            gates["evidence_sufficiency"] = "FAIL"
            evidence_status = "EVIDENCE_CORRUPT"
    elif require_evidence or "evidence_sufficiency" in effective_required_gates:
        err = "missing_required_evidence"
        failures.append(err)
        blocked.append(err)
        evidence_errors.append(err)
        gates["evidence_sufficiency"] = "BLOCKED"
        missing_required_gates.append("evidence_sufficiency")
        evidence_status = "MISSING"
    else:
        gates["evidence_sufficiency"] = "SKIPPED"

    # Gate 4: Numerical Verification Gate
    if numerical is not None:
        if getattr(numerical, "passed", False):
            gates["numerical_verification"] = "PASS"
        else:
            failures.append("numerical_verification_failed")
            gates["numerical_verification"] = "FAIL"
    elif "numerical_verification" in effective_required_gates:
        gates["numerical_verification"] = "BLOCKED"
        failures.append("missing_mandatory_gate:numerical_verification")
        blocked.append("missing_mandatory_gate:numerical_verification")
        missing_required_gates.append("numerical_verification")
    else:
        gates["numerical_verification"] = "SKIPPED"

    # Gate 5: Engineering Checks Gate
    if engineering is not None:
        if getattr(engineering, "passed", False):
            gates["engineering_checks"] = "PASS"
        else:
            failures.append("engineering_checks_failed")
            gates["engineering_checks"] = "FAIL"
    elif "engineering_checks" in effective_required_gates:
        gates["engineering_checks"] = "BLOCKED"
        failures.append("missing_mandatory_gate:engineering_checks")
        blocked.append("missing_mandatory_gate:engineering_checks")
        missing_required_gates.append("engineering_checks")
    else:
        gates["engineering_checks"] = "SKIPPED"

    # Gate 6: Mesh Quality Gate
    if mesh_quality is not None:
        mq_status = mesh_quality.get("status") if isinstance(mesh_quality, dict) else getattr(mesh_quality, "status", None)
        if mq_status in ("pass",):
            gates["mesh_quality"] = "PASS"
        else:
            failures.append("mesh_quality_failed")
            gates["mesh_quality"] = "FAIL"
    elif "mesh_quality" in effective_required_gates:
        gates["mesh_quality"] = "BLOCKED"
        failures.append("missing_mandatory_gate:mesh_quality")
        blocked.append("missing_mandatory_gate:mesh_quality")
        missing_required_gates.append("mesh_quality")
    else:
        gates["mesh_quality"] = "SKIPPED"

    # Gate 7: Convergence Gate
    if convergence is not None:
        if getattr(convergence, "converged", False):
            gates["convergence"] = "PASS"
        else:
            failures.append("mesh_convergence_failed")
            gates["convergence"] = "FAIL"
    elif "convergence" in effective_required_gates:
        gates["convergence"] = "BLOCKED"
        failures.append("missing_mandatory_gate:convergence")
        blocked.append("missing_mandatory_gate:convergence")
        missing_required_gates.append("convergence")
    else:
        gates["convergence"] = "SKIPPED"

    # Gate 8: Fatigue Gate
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
    elif "fatigue" in effective_required_gates:
        gates["fatigue"] = "BLOCKED"
        failures.append("missing_mandatory_gate:fatigue")
        blocked.append("missing_mandatory_gate:fatigue")
        missing_required_gates.append("fatigue")
    else:
        gates["fatigue"] = "SKIPPED"

    # Gate 9: Contact Diagnostics Gate
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
    elif "contact" in effective_required_gates:
        gates["contact"] = "BLOCKED"
        err = "missing_mandatory_gate:contact_diagnostics"
        failures.append(err)
        blocked.append(err)
        missing_required_gates.append("contact")
    else:
        gates["contact"] = "SKIPPED"

    # Gate 10: Procedure Verification Gate (Multi-step DAG)
    if procedure_verification is not None:
        proc_ok = getattr(procedure_verification, "verified", False) or getattr(procedure_verification, "passed", False) or (procedure_verification is True)
        if proc_ok:
            gates["procedure"] = "PASS"
        else:
            failures.append("procedure_verification_failed")
            gates["procedure"] = "FAIL"
    elif "procedure" in effective_required_gates:
        gates["procedure"] = "BLOCKED"
        failures.append("missing_mandatory_gate:procedure")
        blocked.append("missing_mandatory_gate:procedure")
        missing_required_gates.append("procedure")
    else:
        gates["procedure"] = "SKIPPED"

    # Gate 11: Thermal Balance Gate
    if thermal_balance is not None:
        therm_ok = getattr(thermal_balance, "passed", False) or (thermal_balance is True)
        if therm_ok:
            gates["thermal_balance"] = "PASS"
        else:
            failures.append("thermal_balance_failed")
            gates["thermal_balance"] = "FAIL"
    elif "thermal_balance" in effective_required_gates:
        gates["thermal_balance"] = "BLOCKED"
        failures.append("missing_mandatory_gate:thermal_balance")
        blocked.append("missing_mandatory_gate:thermal_balance")
        missing_required_gates.append("thermal_balance")
    else:
        gates["thermal_balance"] = "SKIPPED"

    # Required Metrics Evaluation against Values Map
    values_map = values or {}
    for rm in effective_required_metrics:
        if rm not in values_map:
            missing_required_metrics.append(rm)
            blocked.append("missing_required_metric:%s" % rm)

    # Required ODB Fields Evaluation against odb_fields
    if odb_fields is not None and effective_required_fields:
        norm_available = [str(f).upper() for f in odb_fields]
        for rf in effective_required_fields:
            rf_upper = str(rf).upper()
            matched = any(rf_upper == f or rf_upper in f for f in norm_available)
            if not matched:
                missing_required_fields.append(rf)
                failures.append("missing_required_field:%s" % rf)
                blocked.append("missing_required_field:%s" % rf)

    if missing_required_metrics or missing_required_fields:
        gates["required_results"] = "BLOCKED"
    elif effective_required_metrics or effective_required_fields:
        gates["required_results"] = "PASS"
    else:
        gates["required_results"] = "NOT_SPECIFIED"

    # Gate 12: Criteria Gate
    criteria_result = evaluate_criteria(values_map, criteria or (), required_keys=effective_required_metrics)
    failures.extend(
        "criterion:%s" % item.name for item in criteria_result.criteria if not item.passed
    )
    warnings.extend(criteria_result.warnings)
    # Deduplicate blocked entries from criteria_result that were already added
    for b in criteria_result.blocked:
        if b not in blocked:
            blocked.append(b)

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

    # Gate 13: Connector Kinematics Gate
    if connector_kinematics is not None:
        conn_ok = False
        conn_status = None
        if isinstance(connector_kinematics, bool):
            conn_ok = connector_kinematics
            conn_status = "pass" if conn_ok else "fail"
        elif isinstance(connector_kinematics, dict):
            conn_status = connector_kinematics.get("status")
            conn_ok = conn_status == "pass" or connector_kinematics.get("passed", False) is True
            warnings.extend(tuple(connector_kinematics.get("warnings", ()) or ()))
            failures.extend(tuple(connector_kinematics.get("failures", ()) or ()))
        else:
            conn_status = getattr(connector_kinematics, "status", None)
            conn_ok = conn_status == "pass" or getattr(connector_kinematics, "passed", False) is True
            warnings.extend(tuple(getattr(connector_kinematics, "warnings", ()) or ()))
            failures.extend(tuple(getattr(connector_kinematics, "failures", ()) or ()))

        if conn_ok:
            gates["connector_kinematics"] = "PASS"
        else:
            failures.append("connector_kinematics_failed")
            gates["connector_kinematics"] = "FAIL"
            if conn_status == "warning":
                warnings.append("connector_kinematics_warning")
    elif "connector_kinematics" in effective_required_gates:
        gates["connector_kinematics"] = "BLOCKED"
        failures.append("missing_mandatory_gate:connector_kinematics")
        blocked.append("missing_mandatory_gate:connector_kinematics")
        missing_required_gates.append("connector_kinematics")
    else:
        gates["connector_kinematics"] = "SKIPPED"

    # Gate 14: FMBD Dynamics Gate
    if fmbd_dynamics is not None:
        fmbd_ok = False
        fmbd_status = None
        if isinstance(fmbd_dynamics, bool):
            fmbd_ok = fmbd_dynamics
            fmbd_status = "pass" if fmbd_ok else "fail"
        elif isinstance(fmbd_dynamics, dict):
            fmbd_status = fmbd_dynamics.get("status")
            fmbd_ok = fmbd_status == "pass" or fmbd_dynamics.get("passed", False) is True
            warnings.extend(tuple(fmbd_dynamics.get("warnings", ()) or ()))
            failures.extend(tuple(fmbd_dynamics.get("failures", ()) or ()))
        else:
            fmbd_status = getattr(fmbd_dynamics, "status", None)
            fmbd_ok = fmbd_status == "pass" or getattr(fmbd_dynamics, "passed", False) is True
            warnings.extend(tuple(getattr(fmbd_dynamics, "warnings", ()) or ()))
            failures.extend(tuple(getattr(fmbd_dynamics, "failures", ()) or ()))

        if fmbd_ok:
            gates["fmbd_dynamics"] = "PASS"
        else:
            failures.append("fmbd_dynamics_failed")
            gates["fmbd_dynamics"] = "FAIL"
            if fmbd_status == "warning":
                warnings.append("fmbd_dynamics_warning")
    elif "fmbd_dynamics" in effective_required_gates:
        gates["fmbd_dynamics"] = "BLOCKED"
        failures.append("missing_mandatory_gate:fmbd_dynamics")
        blocked.append("missing_mandatory_gate:fmbd_dynamics")
        missing_required_gates.append("fmbd_dynamics")
    else:
        gates["fmbd_dynamics"] = "SKIPPED"

    # Status & Result Validity & Deliverability Synthesis (S1 ~ S8)
    criteria_failed = any(not item.passed for item in criteria_result.criteria)
    physical_criteria_failed = criteria_failed or any(
        ("failed" in f or "exceeded" in f or "violation" in f or "limit" in f)
        and not f.startswith("missing_")
        and not f.startswith("solver_")
        and not f.startswith("unsupported_")
        and not f.startswith("evidence_")
        and not f.startswith("corrupt_")
        for f in failures
    )

    if evidence_status in ("TAMPERED", "EVIDENCE_TAMPERED"):
        acceptance_status = "RESULT_INVALID"
        result_validity = ResultValidity("EVIDENCE_TAMPERED")
        passed = False
        deliverable = False
        status = "BLOCKED"
    elif evidence_status in ("CORRUPT", "EVIDENCE_CORRUPT"):
        acceptance_status = "RESULT_INVALID"
        result_validity = ResultValidity("EVIDENCE_CORRUPT")
        passed = False
        deliverable = False
        status = "BLOCKED"
    elif evidence_status in ("STALE", "EVIDENCE_STALE"):
        acceptance_status = "RESULT_INVALID"
        result_validity = ResultValidity("EVIDENCE_STALE")
        passed = False
        deliverable = False
        status = "BLOCKED"
    elif evidence_status in ("INCOMPLETE", "EVIDENCE_INCOMPLETE"):
        acceptance_status = "RESULT_INVALID"
        result_validity = ResultValidity("INCOMPLETE")
        passed = False
        deliverable = False
        status = "BLOCKED"
    elif result_status not in ("completed",):
        acceptance_status = "RESULT_INVALID" if result_status in ("unsubmitted", "probe_only") else "BLOCKED"
        result_validity = ResultValidity("SOLVER_FAILED")
        passed = False
        deliverable = False
        status = "BLOCKED"
    elif physical_criteria_failed:
        # S1 & S2: Valid evidence confirmed physical failure!
        # Physical failure takes absolute precedence over missing gates (never masked by BLOCKED)
        acceptance_status = "FAIL"
        result_validity = ResultValidity("VALID")
        passed = False
        deliverable = False
        status = "FAIL"
    elif blocked or missing_required_metrics or missing_required_fields or missing_required_gates:
        # S3 / S5: Missing mandatory gates or prerequisites blocks acceptance while data itself remains VALID
        acceptance_status = "BLOCKED"
        if missing_required_metrics or missing_required_fields:
            result_validity = ResultValidity("RESULT_INVALID")
        elif evidence_status == "MISSING":
            result_validity = ResultValidity("INCOMPLETE")
        else:
            result_validity = ResultValidity("VALID")
        passed = False
        deliverable = False
        status = "BLOCKED"
    elif warnings:
        acceptance_status = "WARNING"
        result_validity = ResultValidity("VALID")
        passed = True
        deliverable = False
        status = "WARNING"
    else:
        # S4: Golden Pass
        acceptance_status = "PASS"
        result_validity = ResultValidity("VALID")
        passed = True
        deliverable = True
        status = "PASS"

    # Deterministic Audit Summary Line
    s_part = "PASS" if result_status == "completed" else "FAIL"
    o_part = gates.get("odb", "PASS" if s_part == "PASS" else "FAIL")
    r_part = "FAIL" if (missing_required_metrics or missing_required_fields or gates.get("required_results") == "BLOCKED" or gates.get("evidence_sufficiency") in ("FAIL", "BLOCKED")) else "PASS"
    e_part = "PASS" if passed else "FAIL"
    audit_summary = f"Solver: {s_part} | ODB: {o_part} | Required Result: {r_part} | Engineering Acceptance: {e_part}"

    # Canonical gate order enforcement
    ordered_gates = {}
    for g_key in CANONICAL_GATE_ORDER:
        if g_key in gates:
            ordered_gates[g_key] = gates[g_key]
    for g_key, g_val in gates.items():
        if g_key not in ordered_gates:
            ordered_gates[g_key] = g_val

    findings = AcceptanceFindings(
        failures=tuple(failures),
        blocked=tuple(blocked),
        evidence_errors=tuple(evidence_errors),
        warnings=tuple(warnings),
        missing_gates=tuple(missing_required_gates),
    )

    return AcceptanceResult(
        passed=passed,
        criteria=criteria_result.criteria,
        failures=tuple(failures),
        warnings=tuple(warnings),
        status=status,
        blocked=tuple(blocked),
        gates=ordered_gates,
        gate_justifications=effective_justifications,
        missing_required_metrics=tuple(missing_required_metrics),
        missing_required_gates=tuple(missing_required_gates),
        missing_required_fields=tuple(missing_required_fields),
        result_validity=result_validity,
        audit_summary=audit_summary,
        odb_status=effective_odb_status,
        evidence_status=evidence_status,
        acceptance_status=acceptance_status,
        deliverable=deliverable,
        findings=findings,
    )
