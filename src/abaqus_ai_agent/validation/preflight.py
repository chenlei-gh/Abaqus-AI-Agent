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
                              "body_force", "section_assignment", "initial_temperature", "initial_stress"):
        check("region_expression", bool(action.parameters.get("region_expression")))

    if action.action_type == "tie":
        check("name", bool(action.parameters.get("name")))
        check("master_expression", bool(action.parameters.get("master_expression")))
        check("slave_expression", bool(action.parameters.get("slave_expression")))

    if action.action_type == "contact":
        check("name", bool(action.parameters.get("name")))
        check("master_expression", bool(action.parameters.get("master_expression")))
        check("slave_expression", bool(action.parameters.get("slave_expression")))
        check("property", bool(action.parameters.get("property")))

    if action.action_type in ("instance_translate", "instance_rotate"):
        instances = getattr(snapshot, "instances", ()) if snapshot is not None and not isinstance(snapshot, dict) else ((snapshot or {}).get("instances", ()) if isinstance(snapshot, dict) else ())
        check("instance_exists", action.parameters.get("instance") in instances, action.parameters.get("instance"))
    if action.action_type == "instance_linear_pattern":
        instances = getattr(snapshot, "instances", ()) if snapshot is not None and not isinstance(snapshot, dict) else ((snapshot or {}).get("instances", ()) if isinstance(snapshot, dict) else ())
        requested = tuple(action.parameters.get("instances", ()))
        check("instances_exist", all(x in instances for x in requested), requested)
    if action.action_type == "export_inp":
        check("job_name", bool(action.parameters.get("job_name")))
    if action.action_type == "export_odb_csv":
        check("odb_path", bool(action.parameters.get("odb_path")))

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
