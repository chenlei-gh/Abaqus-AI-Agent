from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    checks: tuple
    failures: tuple = ()


def verify_expected_state(snapshot, expected_state):
    """Deterministic verification for mapping or ModelSnapshot-like state."""
    checks, failures = [], []

    def lookup(root, path):
        value = root
        for part in str(path).split("."):
            if not part:
                continue
            if isinstance(value, dict):
                if part not in value:
                    return None
                value = value[part]
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                return None
        return value

    for rule in expected_state or ():
        actual = lookup(snapshot, rule.get("path"))
        if "contains" in rule:
            try:
                ok = actual is not None and rule["contains"] in actual
            except TypeError:
                ok = False
        elif "equals" in rule:
            ok = actual == rule["equals"]
        elif "exists" in rule:
            ok = (actual is not None) == bool(rule["exists"])
        else:
            ok = False
        item = {"path": rule.get("path"), "actual": actual, "ok": ok}
        checks.append(item)
        if not ok:
            failures.append(item)
    return VerificationResult(not failures, tuple(checks), tuple(failures))
