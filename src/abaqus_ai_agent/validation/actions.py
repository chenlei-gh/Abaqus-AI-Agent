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
        "concentrated_force", "body_force", "body_heat_flux", "surface_heat_flux", "temperature_bc", "initial_temperature", "initial_stress", "section_assignment",
        "local_seed_size", "local_seed_number", "mesh_controls", "element_type"
    ) and not action.parameters.get("region_expression"):
        raise ValueError("region_expression is required for %s" % action.action_type)
    if action.action_type == "tie":
        if not action.parameters.get("name"):
            raise ValueError("name is required for tie")
        if not action.parameters.get("master_expression"):
            raise ValueError("master_expression is required for tie")
        if not action.parameters.get("slave_expression"):
            raise ValueError("slave_expression is required for tie")
    if action.action_type == "contact":
        if not action.parameters.get("name"):
            raise ValueError("name is required for contact")
        if not action.parameters.get("master_expression"):
            raise ValueError("master_expression is required for contact")
        if not action.parameters.get("slave_expression"):
            raise ValueError("slave_expression is required for contact")
        if not action.parameters.get("property"):
            raise ValueError("property is required for contact")
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
        for key in ("max_aspect_ratio", "max_skew", "min_jacobian", "min_angle", "max_angle", "max_angular_deviation", "max_geometric_deviation_factor"):
            value = action.parameters.get(key)
            if value is not None and value < 0:
                raise ValueError("%s cannot be negative" % key)
        if action.parameters.get("max_aspect_ratio") == 0:
            raise ValueError("max_aspect_ratio must be positive")
    if action.action_type in ("field_output", "history_output"):
        variables = action.parameters.get("variables", ())
        if not variables:
            raise ValueError("variables are required for %s" % action.action_type)
        if action.action_type == "history_output" and action.parameters.get("region_expression") and not action.parameters.get("step"):
            raise ValueError("step is required for regional history_output")
    if action.action_type in ("body_heat_flux", "surface_heat_flux", "temperature_bc", "initial_temperature"):
        if not action.parameters.get("name"):
            raise ValueError("name is required for %s" % action.action_type)
        if action.parameters.get("magnitude") is None:
            raise ValueError("magnitude is required for %s" % action.action_type)
    if action.action_type == "initial_stress" and not action.parameters.get("name"):
        raise ValueError("name is required for initial_stress")
    if action.action_type in ("static_step", "dynamic_explicit_step", "implicit_dynamic_step", "heat_transfer_step", "coupled_temp_displacement_step"):
        if action.action_type in ("static_step", "implicit_dynamic_step", "heat_transfer_step", "coupled_temp_displacement_step"):
            amplitude = action.parameters.get("amplitude")
            if amplitude is not None and amplitude not in ("RAMP", "STEP"):
                raise ValueError("step amplitude must be RAMP or STEP")
        if action.action_type == "dynamic_explicit_step":
            value = action.parameters.get("max_increment")
            if value is not None and value <= 0:
                raise ValueError("max_increment must be positive")
        if not action.parameters.get("name"):
            raise ValueError("name is required for %s" % action.action_type)
        if action.parameters.get("time_period", 1.0) <= 0:
            raise ValueError("time_period must be positive")
        if action.parameters.get("max_num_inc", 1) < 1:
            raise ValueError("max_num_inc must be positive")
        for key in ("initial_inc", "min_inc", "max_inc"):
            value = action.parameters.get(key)
            if value is not None and value <= 0:
                raise ValueError("%s must be positive" % key)
    if action.action_type in ("material_conductivity", "material_specific_heat", "material_expansion"):
        if not action.parameters.get("name") or not action.parameters.get("table"):
            raise ValueError("%s requires name and table" % action.action_type)
    if action.action_type == "contact" and not action.parameters.get("property"):
        raise ValueError("property is required for contact")
    if action.action_type == "contact" and (not action.parameters.get("master_expression") or not action.parameters.get("slave_expression")):
        raise ValueError("master_expression and slave_expression are required for contact")
    if action.action_type == "contact":
        sliding = str(action.parameters.get("sliding", "FINITE")).upper()
        if sliding not in ("FINITE", "SMALL", "SMALL_SLIDING"):
            raise ValueError("sliding must be FINITE, SMALL, or SMALL_SLIDING")
    if action.action_type == "contact_property":
        formulation = str(action.parameters.get("tangential_behavior", {}).get("formulation", "PENALTY")).upper()
        if formulation not in ("FRICTIONLESS", "PENALTY", "LAGRANGE", "ROUGH", "EXPONENTIAL_DECAY", "USER_DEFINED"):
            raise ValueError("unsupported contact tangential formulation")
        if formulation in ("PENALTY", "LAGRANGE"):
            friction = action.parameters.get("tangential_behavior", {}).get("friction", 0.0)
            if friction < 0:
                raise ValueError("friction cannot be negative")
    if action.action_type in ("tabular_amplitude", "smooth_step_amplitude", "periodic_amplitude"):
        data = action.parameters.get("data", ())
        if not data:
            raise ValueError("data is required for %s" % action.action_type)
        if action.parameters.get("time_span", "STEP") not in ("STEP", "TOTAL"):
            raise ValueError("time_span must be STEP or TOTAL")
        if action.action_type in ("tabular_amplitude", "smooth_step_amplitude"):
            if any(len(x) != 2 for x in data):
                raise ValueError("amplitude data must contain time/value pairs")
        if action.action_type == "periodic_amplitude":
            if action.parameters.get("frequency", 0) <= 0:
                raise ValueError("frequency must be positive")
            if any(len(x) != 2 for x in data):
                raise ValueError("periodic data must contain A_i/B_i pairs")
    if action.action_type == "equally_spaced_amplitude":
        if action.parameters.get("fixed_interval", 0) <= 0:
            raise ValueError("fixed_interval must be positive")
        if not action.parameters.get("data"):
            raise ValueError("data is required for equally_spaced_amplitude")
    if action.action_type == "gravity":
        if not any(action.parameters.get(k, 0.0) != 0.0 for k in ("comp1", "comp2", "comp3")):
            raise ValueError("gravity requires a non-zero acceleration vector")
    if action.action_type in ("assembly_inspect",):
        pass
    if action.action_type == "instance_translate":
        vector = action.parameters.get("vector")
        if not vector or len(vector) != 3:
            raise ValueError("vector must contain three components")
        if not action.parameters.get("instance"):
            raise ValueError("instance is required")
    if action.action_type == "instance_rotate":
        for key in ("axis_point", "axis_direction"):
            value = action.parameters.get(key)
            if not value or len(value) != 3:
                raise ValueError("%s must contain three components" % key)
        if not action.parameters.get("instance"):
            raise ValueError("instance is required")
    if action.action_type == "reference_point":
        if not action.parameters.get("name"):
            raise ValueError("name is required for reference_point")
        coords = action.parameters.get("coordinates")
        if not coords or len(coords) != 3:
            raise ValueError("coordinates must contain three components")
    if action.action_type == "rigid_body":
        if not action.parameters.get("name"):
            raise ValueError("name is required for rigid_body")
        if not action.parameters.get("ref_point_expression"):
            raise ValueError("ref_point_expression is required for rigid_body")
    if action.action_type == "connector_section":
        if not action.parameters.get("name"):
            raise ValueError("name is required for connector_section")
        asmb = action.parameters.get("assembled_type")
        trans = action.parameters.get("translational_type")
        rot = action.parameters.get("rotational_type")
        if not asmb and not trans and not rot:
            raise ValueError("connector_section requires assembled_type, translational_type, or rotational_type")
        valid_asmb = (
            "BEAM", "BUSHING", "CVJOINT", "CYLINDRICAL", "HINGE", "PLANAR",
            "RETRACTOR", "SLIPRING", "TRANSLATOR", "UJOINT", "WELD"
        )
        if asmb and asmb.upper() not in valid_asmb:
            raise ValueError("unsupported assembled_type for connector_section: %s" % asmb)
        valid_trans = (
            "ACCELEROMETER", "ALIGNTORQUE", "AXIAL", "CARTESIAN", "JOIN",
            "LINK", "PROJECTION_CARTESIAN", "RADIAL_THRUST", "SLIDER", "SLOT"
        )
        if trans and trans.upper() not in valid_trans:
            raise ValueError("unsupported translational_type for connector_section: %s" % trans)
        valid_rot = (
            "ALIGNTORQUE", "BEAM", "CARDAN", "CYLINDRICAL", "EULER",
            "FLEXION_TORSION", "FLOW_CONVERTER", "HINGE",
            "PROJECTION_FLEXION_TORSION", "REVOLUTE", "ROTATION",
            "ROTATION_ACCELEROMETER", "SLIPRING", "UJOINT",
            "UNCOUPLED_ANGULAR_ACCELEROMETER"
        )
        if rot and rot.upper() not in valid_rot:
            raise ValueError("unsupported rotational_type for connector_section: %s" % rot)
    if action.action_type == "wire_connector":
        if not action.parameters.get("name"):
            raise ValueError("name is required for wire_connector")
        if not action.parameters.get("section_name"):
            raise ValueError("section_name is required for wire_connector")
        has_p1 = bool(action.parameters.get("point1_name") or action.parameters.get("point1_expression"))
        if not has_p1:
            raise ValueError("point1_name or point1_expression is required for wire_connector")
        has_p2 = bool(action.parameters.get("point2_name") or action.parameters.get("point2_expression"))
        if not has_p2:
            raise ValueError("point2_name or point2_expression is required for wire_connector")
    if action.action_type == "instance_linear_pattern":
        if not action.parameters.get("instances"):
            raise ValueError("instances are required")
        if int(action.parameters.get("number1", 0)) < 1 or int(action.parameters.get("number2", 1)) < 1:
            raise ValueError("pattern counts must be positive")
        if action.parameters.get("spacing1", 0) < 0 or action.parameters.get("spacing2", 0) < 0:
            raise ValueError("pattern spacing cannot be negative")
    if action.action_type == "export_inp":
        if not action.parameters.get("job_name"):
            raise ValueError("job_name is required for export_inp")
    if action.action_type == "export_odb_csv":
        for key in ("odb_path", "output_path", "variable"):
            if not action.parameters.get(key):
                raise ValueError("%s is required for export_odb_csv" % key)
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
