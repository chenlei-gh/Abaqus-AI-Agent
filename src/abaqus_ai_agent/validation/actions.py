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
        "concentrated_force", "body_force", "body_heat_flux", "surface_heat_flux", "temperature_bc", "section_assignment", "tie",
        "local_seed_size", "local_seed_number", "mesh_controls", "element_type", "contact"
    ) and not action.parameters.get("region_expression"):
        raise ValueError("region_expression is required for %s" % action.action_type)
    geometry = action.action_type in ("inspect_geometry", "ignore_entity", "restore_entity", "repair_geometry", "remove_redundant_entities", "inspect_mesh")
    if geometry:
        if not action.parameters.get("part"):
            raise ValueError("part is required for %s" % action.action_type)
        if action.action_type in ("ignore_entity", "restore_entity") and not action.parameters.get("region_expression"):
            raise ValueError("region_expression is required for %s" % action.action_type)
        if action.action_type == "inspect_geometry":
            for key in ("min_edge_length", "min_face_size"):
                if action.parameters.get(key) is not None and action.parameters[key] <= 0:
                    raise ValueError("%s must be positive" % key)
    mesh = action.action_type in ("seed_part", "local_seed_size", "local_seed_number", "mesh_controls", "element_type", "generate_mesh", "inspect_mesh")
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
    if action.action_type == "mesh_quality":
        if not action.parameters.get("part"):
            raise ValueError("part is required for mesh_quality")
        for key in ("max_aspect_ratio", "max_skew", "min_jacobian", "min_angle", "max_angle"):
            value = action.parameters.get(key)
            if value is not None and value < 0:
                raise ValueError("%s cannot be negative" % key)
        if action.parameters.get("max_aspect_ratio") == 0:
            raise ValueError("max_aspect_ratio must be positive")
    if action.action_type in ("body_heat_flux", "surface_heat_flux", "temperature_bc"):
        if not action.parameters.get("name"):
            raise ValueError("name is required for %s" % action.action_type)
        if action.parameters.get("magnitude") is None:
            raise ValueError("magnitude is required for %s" % action.action_type)
    if action.action_type in ("heat_transfer_step", "coupled_temp_displacement_step"):
        if not action.parameters.get("name"):
            raise ValueError("name is required for %s" % action.action_type)
        if action.parameters.get("time_period", 1.0) <= 0:
            raise ValueError("time_period must be positive")
    if action.action_type in ("material_conductivity", "material_specific_heat", "material_expansion"):
        if not action.parameters.get("name") or not action.parameters.get("table"):
            raise ValueError("%s requires name and table" % action.action_type)
    if action.action_type == "contact" and not action.parameters.get("property"):
        raise ValueError("property is required for contact")
    if action.action_type == "contact" and (not action.parameters.get("master_expression") or not action.parameters.get("slave_expression")):
        raise ValueError("master_expression and slave_expression are required for contact")
    if action.action_type == "contact":
        sliding = str(action.parameters.get("sliding", "FINITE")).upper()
        if sliding not in ("FINITE", "SMALL"):
            raise ValueError("sliding must be FINITE or SMALL")
    if action.action_type == "contact_property":
        formulation = str(action.parameters.get("tangential_behavior", {}).get("formulation", "PENALTY")).upper()
        if formulation not in ("FRICTIONLESS", "PENALTY", "LAGRANGE", "ROUGH", "EXPONENTIAL_DECAY", "USER_DEFINED"):
            raise ValueError("unsupported contact tangential formulation")
        if formulation in ("PENALTY", "LAGRANGE"):
            friction = action.parameters.get("tangential_behavior", {}).get("friction", 0.0)
            if friction < 0:
                raise ValueError("friction cannot be negative")
    if action.action_type == "element_type" and not action.parameters.get("elem_code"):
        raise ValueError("elem_code is required for element_type")
    if action.expected_state and not all(isinstance(x, dict) and x.get("path")
                                         for x in action.expected_state):
        raise ValueError("expected_state entries require a path")
    return True


def validate_plan(plan):
    for action in plan.actions:
        validate_action(action)
    return True
