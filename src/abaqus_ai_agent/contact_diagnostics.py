from .contracts.contact import (
    ContactDiagnostic,
    ContactDiagnosticReport,
    ExpectedContactBehavior,
)


def _field(evidence, name):
    return (evidence or {}).get("fields", {}).get(name)


def _available_values(field):
    if not isinstance(field, dict) or field.get("status") != "available":
        return ()
    return tuple(
        item.get("data")
        for item in field.get("values", ())
        if isinstance(item, dict) and item.get("data") is not None
    )


def _scalar(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (tuple, list)) and len(value) == 1:
        return _scalar(value[0])
    return None


def _numeric_values(field):
    values = []
    for data in _available_values(field):
        number = _scalar(data)
        if number is not None:
            values.append(number)
    return tuple(values)


def _status_values(field):
    values = []
    for data in _available_values(field):
        if isinstance(data, str):
            values.append(data.strip().lower())
        else:
            number = _scalar(data)
            if number is not None:
                values.append(number)
    return tuple(values)


def _is_open(value):
    if isinstance(value, str):
        return value.lower() == "open"
    return isinstance(value, (int, float)) and float(value) == 0.0


def _is_contact(value):
    if isinstance(value, str):
        return value.lower() in (
            "closed", "closed (sticking)", "closed (slipping)",
            "sticking", "slipping", "contact",
        )
    return isinstance(value, (int, float)) and float(value) in (0.5, 1.0)


def _status_kind(value):
    if _is_open(value):
        return "open"
    if _is_contact(value):
        return "contact"
    return None


def _required_output_names(expected):
    return tuple(dict.fromkeys(expected.required_outputs))


def contact_evidence_sufficiency(evidence, expected):
    """Determine whether the supplied ODB evidence can answer the contract."""
    if not isinstance(expected, ExpectedContactBehavior):
        raise TypeError("expected must be ExpectedContactBehavior")

    if not isinstance(evidence, dict):
        return ContactDiagnostic(
            "contact_evidence_sufficiency",
            "insufficient_evidence",
            message="contact evidence is not a mapping",
        )

    if expected.expected_regions:
        evidence_region = evidence.get("region")
        if evidence_region is None:
            return ContactDiagnostic(
                "contact_evidence_sufficiency",
                "insufficient_evidence",
                message="expected_regions declared but evidence has no region identity",
            )
        expected_regions = {str(region) for region in expected.expected_regions}
        if str(evidence_region) not in expected_regions:
            return ContactDiagnostic(
                "contact_evidence_sufficiency",
                "insufficient_evidence",
                message="evidence region does not match the declared expected region",
            )

    missing = []
    ambiguous = False
    for name in _required_output_names(expected):
        field = _field(evidence, name)
        if field is None:
            missing.append(name)
            continue
        if field.get("status") == "ambiguous":
            ambiguous = True
        elif field.get("status") != "available":
            missing.append(name)

    # History is auxiliary evidence; ambiguous history must not invalidate
    # sufficient field evidence unless history is explicitly required.
    if ambiguous:
        return ContactDiagnostic(
            "contact_evidence_sufficiency",
            "ambiguous",
            message="contact evidence maps to multiple history regions",
        )
    if missing:
        return ContactDiagnostic(
            "contact_evidence_sufficiency",
            "insufficient_evidence",
            message="required contact outputs unavailable: %s" % ", ".join(missing),
        )
    return ContactDiagnostic(
        "contact_evidence_sufficiency",
        "pass",
        message="required contact evidence is available",
    )


def expected_contact_state(evidence, expected):
    """Compare observed contact state with the explicitly declared expectation."""
    if not expected.contact_required:
        return ContactDiagnostic(
            "expected_contact_state",
            "not_applicable",
            message="contact is not required by the declared expectation",
        )

    cstatus = _field(evidence, "CSTATUS")
    statuses = _status_values(cstatus)
    if not statuses:
        return ContactDiagnostic(
            "expected_contact_state",
            "insufficient_evidence",
            message="CSTATUS is required to determine contact state",
        )

    kinds = tuple(_status_kind(value) for value in statuses)
    observed_contact = "contact" in kinds
    observed_open = "open" in kinds
    has_unknown = any(kind is None for kind in kinds)

    if expected.expected_state == "either":
        if has_unknown:
            return ContactDiagnostic(
                "expected_contact_state",
                "ambiguous",
                message="CSTATUS contains values whose contact state cannot be mapped confidently",
            )
        return ContactDiagnostic(
            "expected_contact_state",
            "pass",
            message="observed CSTATUS is compatible with either declared state",
        )
    if expected.expected_state == "contact":
        if observed_contact and not observed_open and not has_unknown:
            return ContactDiagnostic(
                "expected_contact_state", "pass",
                message="all supplied CSTATUS values indicate contact",
            )
        if observed_contact and observed_open:
            return ContactDiagnostic(
                "expected_contact_state", "ambiguous",
                message="CSTATUS contains both contact and open locations; mixed interface state is not sufficient to prove contact failure",
            )
        if observed_open and not observed_contact and not has_unknown:
            return ContactDiagnostic(
                "expected_contact_state", "fail",
                message="all supplied CSTATUS values are open although contact is required",
            )
    if expected.expected_state == "open":
        if observed_open and not observed_contact and not has_unknown:
            return ContactDiagnostic(
                "expected_contact_state", "pass",
                message="all supplied CSTATUS values are open as expected",
            )
        if observed_contact and not observed_open and not has_unknown:
            return ContactDiagnostic(
                "expected_contact_state", "fail",
                message="all supplied CSTATUS values indicate contact although separation is expected",
            )
        if observed_contact and observed_open:
            return ContactDiagnostic(
                "expected_contact_state",
                "ambiguous",
                message="CSTATUS contains both contact and open locations; the supplied evidence is not uniformly separated",
            )

    return ContactDiagnostic(
        "expected_contact_state",
        "ambiguous",
        message="CSTATUS does not map uniquely to the declared expected state",
    )


def unexpected_opening(evidence, expected):
    """Detect opening only against an explicitly declared separation limit."""
    if "COPEN" not in _required_output_names(expected):
        return ContactDiagnostic(
            "unexpected_opening", "not_applicable",
            message="COPEN was not required by the declared contact evidence contract",
        )
    if expected.expected_state != "contact" or not expected.contact_required:
        return ContactDiagnostic(
            "unexpected_opening",
            "not_applicable",
            message="maintained contact is not the declared expectation",
        )

    copen = _numeric_values(_field(evidence, "COPEN"))
    if not copen:
        return ContactDiagnostic(
            "unexpected_opening",
            "insufficient_evidence",
            message="COPEN is unavailable or non-numeric",
        )

    if expected.expected_separation is None:
        return ContactDiagnostic(
            "unexpected_opening",
            "insufficient_evidence",
            message="no problem-specific maximum separation was declared",
        )

    maximum = max(copen)
    if maximum > expected.expected_separation:
        return ContactDiagnostic(
            "unexpected_opening",
            "fail",
            value=maximum,
            limit=expected.expected_separation,
            unit="length",
            message="observed opening exceeds the explicitly declared separation limit",
        )
    return ContactDiagnostic(
        "unexpected_opening",
        "pass",
        value=maximum,
        limit=expected.expected_separation,
        unit="length",
        message="observed opening is within the explicitly declared limit",
    )


def unexpected_overclosure(evidence, expected):
    """Detect overclosure only against an explicitly declared interference limit."""
    if "COPEN" not in _required_output_names(expected):
        return ContactDiagnostic(
            "unexpected_overclosure", "not_applicable",
            message="COPEN was not required by the declared contact evidence contract",
        )
    copen = _numeric_values(_field(evidence, "COPEN"))
    if not copen:
        return ContactDiagnostic(
            "unexpected_overclosure",
            "insufficient_evidence",
            message="COPEN is unavailable or non-numeric",
        )

    negative = min(copen)
    if negative >= 0.0:
        return ContactDiagnostic(
            "unexpected_overclosure",
            "pass",
            value=negative,
            message="no negative contact opening was observed",
        )

    allowed = expected.allowed_initial_interference
    if allowed is None:
        return ContactDiagnostic(
            "unexpected_overclosure",
            "warning",
            value=negative,
            message="negative COPEN observed, but no interference tolerance was declared; this is not sufficient to call failure",
        )

    magnitude = abs(negative)
    if magnitude > allowed:
        return ContactDiagnostic(
            "unexpected_overclosure",
            "fail",
            value=magnitude,
            limit=allowed,
            unit="length",
            message="overclosure exceeds the explicitly declared interference allowance",
        )
    return ContactDiagnostic(
        "unexpected_overclosure",
        "pass",
        value=magnitude,
        limit=allowed,
        unit="length",
        message="overclosure is within the explicitly declared interference allowance",
    )


def contact_behavior_consistency(evidence, expected):
    """Check only directly contradictory contact observations."""
    required = set(_required_output_names(expected))
    if "CSTATUS" not in required or not ({"CPRESS", "COPEN"} & required):
        return ContactDiagnostic(
            "contact_behavior_consistency", "not_applicable",
            message="insufficient contact variables were requested for a cross-variable consistency check",
        )

    cpress = _numeric_values(_field(evidence, "CPRESS"))
    copen = _numeric_values(_field(evidence, "COPEN"))
    cstatus = _status_values(_field(evidence, "CSTATUS"))

    if not cstatus or (not cpress and not copen):
        return ContactDiagnostic(
            "contact_behavior_consistency",
            "insufficient_evidence",
            message="insufficient overlapping CSTATUS/COPEN/CPRESS evidence",
        )

    closed = any(_is_contact(value) for value in cstatus)
    opened = any(_is_open(value) for value in cstatus)
    positive_pressure = any(value > 0.0 for value in cpress)
    positive_opening = any(value > 0.0 for value in copen)

    if opened and positive_pressure:
        return ContactDiagnostic(
            "contact_behavior_consistency",
            "warning",
            message="CSTATUS includes open locations while CPRESS is positive elsewhere; localization/frame alignment is insufficient for a failure claim",
        )

    if closed and positive_opening:
        return ContactDiagnostic(
            "contact_behavior_consistency",
            "warning",
            message="CSTATUS includes contact while COPEN is positive elsewhere; mixed contact states are possible and are not by themselves contradictory",
        )

    return ContactDiagnostic(
        "contact_behavior_consistency",
        "pass",
        message="no direct contradiction was detected in the supplied contact evidence",
    )


def diagnose_contact(evidence, expected):
    """Run the bounded first-version contact diagnostic set."""
    if not isinstance(expected, ExpectedContactBehavior):
        raise TypeError("expected must be ExpectedContactBehavior")
    if not expected.contact_required:
        return ContactDiagnosticReport((
            ContactDiagnostic("contact_evidence_sufficiency", "not_applicable",
                              message="contact is not required by the declared expectation"),
            ContactDiagnostic("expected_contact_state", "not_applicable",
                              message="contact is not required by the declared expectation"),
            ContactDiagnostic("unexpected_opening", "not_applicable",
                              message="contact is not required by the declared expectation"),
            ContactDiagnostic("unexpected_overclosure", "not_applicable",
                              message="contact is not required by the declared expectation"),
            ContactDiagnostic("contact_behavior_consistency", "not_applicable",
                              message="contact is not required by the declared expectation"),
        ))

    sufficiency = contact_evidence_sufficiency(evidence, expected)
    if sufficiency.status in ("insufficient_evidence", "ambiguous"):
        return ContactDiagnosticReport((sufficiency,))

    diagnostics = (
        sufficiency,
        expected_contact_state(evidence, expected),
        unexpected_opening(evidence, expected),
        unexpected_overclosure(evidence, expected),
        contact_behavior_consistency(evidence, expected),
    )
    return ContactDiagnosticReport(diagnostics)


def evaluate_contact_checks(checks):
    normalized = []
    for check in checks:
        if isinstance(check, ContactDiagnostic):
            normalized.append(check)
        else:
            normalized.append(ContactDiagnostic(
                name=check["name"],
                status=check.get("status", "unknown"),
                value=check.get("value"),
                limit=check.get("limit"),
                unit=check.get("unit", ""),
                message=check.get("message", ""),
            ))
    return ContactDiagnosticReport(tuple(normalized))
