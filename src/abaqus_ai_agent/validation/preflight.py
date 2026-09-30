from dataclasses import dataclass


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    checks: tuple
    blockers: tuple = ()


def preflight_action(action, snapshot=None):
    checks, blockers = [], []

    def check(name, ok, detail=None):
        item = {"name": name, "ok": bool(ok), "detail": detail}
        checks.append(item)
        if not ok:
            blockers.append(item)

    check("model_name", bool(action.model_name))
    if snapshot is not None:
        if isinstance(snapshot, dict):
            models = snapshot.get("models", ())
        else:
            models = getattr(snapshot, "models", ())
        check("model_exists", action.model_name in models, action.model_name)

    if action.action_type in ("fixed_bc", "displacement_bc", "symmetry_bc",
                              "pressure_load", "concentrated_force",
                              "body_force", "section_assignment", "tie"):
        check("region_expression", bool(action.parameters.get("region_expression")))

    for rule in action.preconditions:
        path = rule.get("path")
        value = snapshot
        for part in str(path).split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = getattr(value, part, None)
        if "exists" in rule:
            ok = (value is not None) == bool(rule["exists"])
        elif "contains" in rule:
            try:
                ok = value is not None and rule["contains"] in value
            except TypeError:
                ok = False
        else:
            ok = value == rule.get("equals")
        check("precondition:%s" % path, ok, value)

    return PreflightResult(not blockers, tuple(checks), tuple(blockers))
