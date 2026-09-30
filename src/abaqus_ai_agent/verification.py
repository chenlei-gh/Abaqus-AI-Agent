from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    checks: tuple
    failures: tuple = ()


def verify_expected_state(snapshot, expected_state):
    """Deterministic verification of an action's expected post-state."""
    checks, failures = [], []

    def lookup(root, path):
        value = root
        for part in str(path).split("."):
            if not part:
                continue
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return value

    for rule in expected_state or ():
        actual = lookup(snapshot, rule.get("path"))
        if "contains" in rule:
            ok = actual is not None and rule["contains"] in actual
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
