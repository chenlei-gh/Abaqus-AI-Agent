from ..contracts.action import AbaqusAction


def validate_action(action):
    if not isinstance(action, AbaqusAction):
        raise TypeError("expected AbaqusAction")
    if not action.model_name:
        raise ValueError("model_name is required")
    if not action.action_type:
        raise ValueError("action_type is required")
    if action.action_type in ("fixed_bc", "displacement_bc", "pressure_load", "concentrated_force", "section_assignment"):
        if not action.parameters.get("region_expression"):
            raise ValueError("region_expression is required for %s" % action.action_type)
    return True


def validate_plan(plan):
    for action in plan.actions:
        validate_action(action)
    return True
