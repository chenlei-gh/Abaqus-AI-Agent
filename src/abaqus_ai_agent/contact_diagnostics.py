from .contracts.contact import ContactDiagnostic, ContactDiagnosticReport


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
