"""Acceptance mapping for contact diagnostics.

The mapping is deliberately explicit: hard evidence failures block, warnings
remain visible, and non-applicable checks are neutral.
"""


def contact_acceptance_effect(contact_diagnostics):
    failures = []
    warnings = []
    for diagnostic in getattr(contact_diagnostics, "diagnostics", ()) or ():
        status = getattr(diagnostic, "status", None)
        name = getattr(diagnostic, "name", "contact_diagnostic")
        message = getattr(diagnostic, "message", "")
        if status in ("fail", "insufficient_evidence", "ambiguous"):
            failures.append("contact:%s:%s" % (name, status))
        elif status == "warning":
            warnings.append(
                "contact:%s:warning%s"
                % (name, (":" + message) if message else "")
            )
        elif status not in ("pass", "not_applicable"):
            failures.append(
                "contact:%s:unsupported_status:%s" % (name, status)
            )
    return tuple(failures), tuple(warnings)
