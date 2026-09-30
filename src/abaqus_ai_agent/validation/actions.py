from ..contracts.action import AbaqusAction


def validate_action(action):
    if not isinstance(action, AbaqusAction):
        raise TypeError("expected AbaqusAction")
    if not action.model_name:
        raise ValueError("model_name is required")
    if not action.action_type:
        raise ValueError("action_type is required")
    if action.action_type in (
        "fixed_bc", "displacement_bc", "symmetry_bc", "pressure_load",
        "concentrated_force", "body_force", "section_assignment", "tie",
        "local_seed_size", "local_seed_number", "mesh_controls", "element_type"
    ) and not action.parameters.get("region_expression"):
        raise ValueError("region_expression is required for %s" % action.action_type)
    mesh = action.action_type in ("seed_part", "local_seed_size", "local_seed_number", "mesh_controls", "element_type", "generate_mesh")
    if mesh:
        part = action.parameters.get("part")
        if not part:
            raise ValueError("part is required for %s" % action.action_type)
    if action.action_type == "local_seed_size" and action.parameters.get("size", 0) <= 0:
        raise ValueError("size must be positive")
    if action.action_type == "local_seed_number" and int(action.parameters.get("number", 0)) < 1:
        raise ValueError("number must be positive")
    if action.action_type in ("local_seed_size", "local_seed_number", "mesh_controls", "element_type") and not action.parameters.get("region_expression"):
        raise ValueError("region_expression is required for %s" % action.action_type)
    if action.action_type == "mesh_controls" and not action.parameters.get("technique"):
        raise ValueError("technique is required for mesh_controls")
    if action.action_type == "element_type" and not action.parameters.get("elem_types"):
        raise ValueError("elem_types is required for element_type")
    if action.expected_state and not all(isinstance(x, dict) and x.get("path")
                                         for x in action.expected_state):
        raise ValueError("expected_state entries require a path")
    return True


def validate_plan(plan):
    for action in plan.actions:
        validate_action(action)
    return True
