from ..contracts.action import AbaqusAction

def _action(kind, model, target=None, **parameters):
    return AbaqusAction(kind, model, target, parameters, True)

def python_action(model, code): return _action("python", model, code=code)
def material_elastic(model, name, youngs_modulus, poisson): return _action("material_elastic", model, name=name, youngs_modulus=youngs_modulus, poisson=poisson)
def material_density(model, name, density): return _action("material_density", model, name=name, density=density)
def material_plastic(model, name, table): return _action("material_plastic", model, name=name, table=table)
def material_conductivity(model, name, table): return _action("material_conductivity", model, name=name, table=table)
def material_specific_heat(model, name, table): return _action("material_specific_heat", model, name=name, table=table)
def material_expansion(model, name, table): return _action("material_expansion", model, name=name, table=table)
def solid_section(model, name, material): return _action("solid_section", model, name=name, material=material)
def section_assignment(model, part, section, region_expression): return _action("section_assignment", model, part=part, section=section, region_expression=region_expression)
def mesh_controls(model, target, **params): return _action("mesh_controls", model, target, **params)
def seed_part(model, part, size, deviation_factor=0.1, min_size_factor=0.1): return _action("seed_part", model, part=part, size=size, deviation_factor=deviation_factor, min_size_factor=min_size_factor)
def generate_mesh(model, part): return _action("generate_mesh", model, part=part)
def element_type(model, part, region_expression, elem_code="C3D8R", library="STANDARD"): return _action("element_type", model, part=part, region_expression=region_expression, elem_code=elem_code, library=library)

def static_step(model, name="Step-1", previous="Initial", nlgeom=False, time_period=1.0,
                stabilization_method="NONE", stabilization_magnitude=None,
                time_incrementation_method="AUTOMATIC", max_num_inc=100,
                initial_inc=None, min_inc=None, max_inc=None, amplitude="RAMP"):
    return _action("static_step", model, name=name, previous=previous, nlgeom=nlgeom,
                   time_period=time_period, stabilization_method=stabilization_method,
                   stabilization_magnitude=stabilization_magnitude,
                   time_incrementation_method=time_incrementation_method,
                   max_num_inc=max_num_inc, initial_inc=initial_inc, min_inc=min_inc,
                   max_inc=max_inc, amplitude=amplitude)

def dynamic_explicit_step(model, name="Step-1", previous="Initial", time_period=1.0,
                           nlgeom=True, max_increment=None, improved_dt_method=True):
    return _action("dynamic_explicit_step", model, name=name, previous=previous,
                   time_period=time_period, nlgeom=nlgeom, max_increment=max_increment,
                   improved_dt_method=improved_dt_method)

def implicit_dynamic_step(model, name="Step-1", previous="Initial", time_period=1.0,
                          nlgeom=False, max_num_inc=100, initial_inc=None,
                          min_inc=None, max_inc=None, solution_technique="FULL_NEWTON",
                          reform_kernel=8, amplitude="STEP"):
    return _action("implicit_dynamic_step", model, name=name, previous=previous,
                   time_period=time_period, nlgeom=nlgeom, max_num_inc=max_num_inc,
                   initial_inc=initial_inc, min_inc=min_inc, max_inc=max_inc,
                   solution_technique=solution_technique, reform_kernel=reform_kernel,
                   amplitude=amplitude)

def frequency_step(model, name="Step-1", previous="Initial", num_eigen=10): return _action("frequency_step", model, name=name, previous=previous, num_eigen=num_eigen)
def heat_transfer_step(model, name="Step-1", previous="Initial", response="TRANSIENT", time_period=1.0,
                       max_num_inc=100, initial_inc=None, min_inc=None, max_inc=None,
                       time_incrementation_method="AUTOMATIC", amplitude="STEP"):
    return _action("heat_transfer_step", model, name=name, previous=previous, response=response,
                   time_period=time_period, max_num_inc=max_num_inc, initial_inc=initial_inc,
                   min_inc=min_inc, max_inc=max_inc, time_incrementation_method=time_incrementation_method,
                   amplitude=amplitude)
def coupled_temp_displacement_step(model, name="Step-1", previous="Initial", response="TRANSIENT", time_period=1.0,
                                    nlgeom=False, max_num_inc=100, initial_inc=None, min_inc=None, max_inc=None,
                                    time_incrementation_method="AUTOMATIC", amplitude="STEP"):
    return _action("coupled_temp_displacement_step", model, name=name, previous=previous,
                   response=response, time_period=time_period, nlgeom=nlgeom,
                   max_num_inc=max_num_inc, initial_inc=initial_inc, min_inc=min_inc,
                   max_inc=max_inc, time_incrementation_method=time_incrementation_method,
                   amplitude=amplitude)

def tabular_amplitude(model, name, data, time_span="STEP", smooth=None):
    return _action("tabular_amplitude", model, name=name, data=data, time_span=time_span, smooth=smooth)
def smooth_step_amplitude(model, name, data, time_span="STEP"):
    return _action("smooth_step_amplitude", model, name=name, data=data, time_span=time_span)
def periodic_amplitude(model, name, frequency, start, a0, data, time_span="STEP"):
    return _action("periodic_amplitude", model, name=name, frequency=frequency, start=start,
                   a0=a0, data=data, time_span=time_span)
def equally_spaced_amplitude(model, name, fixed_interval, data, begin=0.0, time_span="STEP", smooth=None):
    return _action("equally_spaced_amplitude", model, name=name, fixed_interval=fixed_interval,
                   data=data, begin=begin, time_span=time_span, smooth=smooth)

def fixed_bc(model, name, region_expression, step="Initial"): return _action("fixed_bc", model, region_expression, name=name, region_expression=region_expression, step=step)
def displacement_bc(model, name, region_expression, step="Initial", **values): return _action("displacement_bc", model, region_expression, name=name, region_expression=region_expression, step=step, **values)
def symmetry_bc(model, name, region_expression, step="Initial", plane="X"): return _action("symmetry_bc", model, region_expression, name=name, region_expression=region_expression, step=step, plane=plane)
def temperature_bc(model, name, region_expression, magnitude, step="Step-1"): return _action("temperature_bc", model, region_expression, name=name, region_expression=region_expression, magnitude=magnitude, step=step)
def initial_temperature(model, name, region_expression, magnitude, amplitude=None):
    return _action("initial_temperature", model, region_expression, name=name,
                   region_expression=region_expression, magnitude=magnitude, amplitude=amplitude)
def initial_stress(model, name, region_expression, sigma11=0.0, sigma22=0.0, sigma33=0.0, sigma12=0.0, sigma13=0.0, sigma23=0.0):
    return _action("initial_stress", model, region_expression, name=name,
                   region_expression=region_expression, sigma11=sigma11, sigma22=sigma22,
                   sigma33=sigma33, sigma12=sigma12, sigma13=sigma13, sigma23=sigma23)

def pressure_load(model, name, region_expression, magnitude, step="Step-1", amplitude=None): return _action("pressure_load", model, region_expression, name=name, region_expression=region_expression, magnitude=magnitude, step=step, amplitude=amplitude)
def concentrated_force(model, name, region_expression, cf1=0.0, cf2=0.0, cf3=0.0, step="Step-1", amplitude=None): return _action("concentrated_force", model, region_expression, name=name, region_expression=region_expression, cf1=cf1, cf2=cf2, cf3=cf3, step=step, amplitude=amplitude)
def body_force(model, name, region_expression, comp1=0.0, comp2=0.0, comp3=0.0, step="Step-1", amplitude=None): return _action("body_force", model, region_expression, name=name, region_expression=region_expression, comp1=comp1, comp2=comp2, comp3=comp3, step=step, amplitude=amplitude)
def gravity(model, name, comp1=0.0, comp2=0.0, comp3=0.0, step="Step-1", region_expression=None, amplitude=None):
    return _action("gravity", model, region_expression, name=name, region_expression=region_expression,
                   comp1=comp1, comp2=comp2, comp3=comp3, step=step, amplitude=amplitude)
def body_heat_flux(model, name, region_expression, magnitude, step="Step-1"): return _action("body_heat_flux", model, region_expression, name=name, region_expression=region_expression, magnitude=magnitude, step=step)
def surface_heat_flux(model, name, region_expression, magnitude, step="Step-1"): return _action("surface_heat_flux", model, region_expression, name=name, region_expression=region_expression, magnitude=magnitude, step=step)

def field_output(model, variables=("S", "U", "RF"), request="F-Output-1", step="Initial",
                 frequency=None, num_intervals=None):
    return _action("field_output", model, variables=variables, request=request, step=step,
                   frequency=frequency, num_intervals=num_intervals)
def history_output(model, variables=("ALLIE", "ALLKE", "ALLSE"), request="H-Output-1", region_expression=None, step="Step-1"): return _action("history_output", model, variables=variables, request=request, region_expression=region_expression, step=step)
def create_job(model, name, job_type="STANDARD"): return _action("create_job", model, name=name, job_type=job_type)
def submit_job(model, name): return _action("submit_job", model, name=name)

def assembly_inspect(model): return _action("assembly_inspect", model)
def instance_translate(model, instance, vector):
    return _action("instance_translate", model, target=instance, instance=instance, vector=vector)
def instance_rotate(model, instance, axis_point, axis_direction, angle):
    return _action("instance_rotate", model, target=instance, instance=instance,
                   axis_point=axis_point, axis_direction=axis_direction, angle=angle)
def instance_linear_pattern(model, instances, number1, spacing1, number2=1, spacing2=0.0, direction1=(1.0, 0.0, 0.0), direction2=(0.0, 1.0, 0.0)):
    return _action("instance_linear_pattern", model, instances=tuple(instances), number1=number1,
                   spacing1=spacing1, number2=number2, spacing2=spacing2,
                   direction1=direction1, direction2=direction2)

def export_inp(model, job_name, output_path=None):
    return _action("export_inp", model, job_name=job_name, output_path=output_path)
def export_odb_csv(model, odb_path, output_path, step=None, frame=-1, variable="U", component=None, position=None):
    return _action("export_odb_csv", model, odb_path=odb_path, output_path=output_path,
                   step=step, frame=frame, variable=variable, component=component, position=position)

def tie(model, name, master_expression, slave_expression): return _action("tie", model, name=name, master_expression=master_expression, slave_expression=slave_expression)

def local_seed_size(model, part, region_expression, size, constraint="FREE"):
    return _action("local_seed_size", model, region_expression, part=part, region_expression=region_expression, size=size, constraint=constraint)
def local_seed_number(model, part, region_expression, number, constraint="FREE"):
    return _action("local_seed_number", model, region_expression, part=part, region_expression=region_expression, number=number, constraint=constraint)
def inspect_geometry(model, part, min_edge_length=None, min_face_size=None): return _action("inspect_geometry", model, part=part, min_edge_length=min_edge_length, min_face_size=min_face_size)
def ignore_entity(model, part, region_expression): return _action("ignore_entity", model, region_expression, part=part, region_expression=region_expression)
def restore_entity(model, part, region_expression): return _action("restore_entity", model, region_expression, part=part, region_expression=region_expression)
def repair_geometry(model, part): return _action("repair_geometry", model, part=part)
def remove_redundant_entities(model, part): return _action("remove_redundant_entities", model, part=part)
def inspect_mesh(model, part): return _action("inspect_mesh", model, part=part)
def mesh_quality(model, part, **params): return _action("mesh_quality", model, part=part, **params)
def contact_property(model, name, normal_behavior=True, pressure_overclosure="HARD", tangential_behavior=None): return _action("contact_property", model, name=name, normal_behavior=normal_behavior, pressure_overclosure=pressure_overclosure, tangential_behavior=tangential_behavior)
def contact(model, name, master_expression, slave_expression, property, sliding="FINITE", step="Initial"): return _action("contact", model, name=name, master_expression=master_expression, slave_expression=slave_expression, property=property, sliding=sliding, step=step)

def reference_point(model, name, coordinates, part=None):
    return _action("reference_point", model, name=name, coordinates=tuple(coordinates), part=part)

def rigid_body(model, name, ref_point_expression, body_expression=None, tie_region=None, pin_region=None, **kwargs):
    params = {"name": name, "ref_point_expression": ref_point_expression}
    if body_expression is not None:
        params["body_expression"] = body_expression
    if tie_region is not None:
        params["tie_region"] = tie_region
    if pin_region is not None:
        params["pin_region"] = pin_region
    params.update(kwargs)
    return _action("rigid_body", model, **params)


def coupling_constraint(
    model,
    name,
    control_point=None,
    surface=None,
    control_point_name=None,
    surface_name=None,
    control_point_expression=None,
    surface_expression=None,
    coupling_type="KINEMATIC",
    influence_radius=None,
    u1=True,
    u2=True,
    u3=True,
    ur1=True,
    ur2=True,
    ur3=True,
    **kwargs,
):
    params = {
        "name": name,
        "coupling_type": str(coupling_type).upper(),
        "u1": bool(u1),
        "u2": bool(u2),
        "u3": bool(u3),
        "ur1": bool(ur1),
        "ur2": bool(ur2),
        "ur3": bool(ur3),
    }
    cp_name = control_point_name or (control_point if isinstance(control_point, str) else None)
    if cp_name:
        params["control_point_name"] = cp_name
    elif control_point_expression:
        params["control_point_expression"] = control_point_expression
    elif control_point is not None:
        params["control_point_expression"] = control_point

    surf_name = surface_name or (surface if isinstance(surface, str) else None)
    if surf_name:
        params["surface_name"] = surf_name
    elif surface_expression:
        params["surface_expression"] = surface_expression
    elif surface is not None:
        params["surface_expression"] = surface

    if influence_radius is not None:
        params["influence_radius"] = float(influence_radius)
    params.update(kwargs)
    return _action("coupling_constraint", model, **params)


def connector_section(
    model,
    name,
    assembled_type=None,
    translational_type=None,
    rotational_type=None,
    behavior_name=None,
    **kwargs,
):
    params = {"name": name}
    if assembled_type is not None:
        params["assembled_type"] = assembled_type
    if translational_type is not None:
        params["translational_type"] = translational_type
    if rotational_type is not None:
        params["rotational_type"] = rotational_type
    if behavior_name is not None:
        params["behavior_name"] = behavior_name
    params.update(kwargs)
    return _action("connector_section", model, **params)


def wire_connector(
    model,
    name,
    section_name,
    point1=None,
    point2=None,
    point1_name=None,
    point2_name=None,
    point1_expression=None,
    point2_expression=None,
    wire_feature_name=None,
    wire_set_name=None,
    orientation=None,
    **kwargs,
):
    params = {"name": name, "section_name": section_name}
    if orientation is not None:
        params["orientation"] = orientation
    p1_name = point1_name or (point1 if isinstance(point1, str) else None)
    p2_name = point2_name or (point2 if isinstance(point2, str) else None)
    if p1_name:
        params["point1_name"] = p1_name
    elif point1_expression:
        params["point1_expression"] = point1_expression
    if p2_name:
        params["point2_name"] = p2_name
    elif point2_expression:
        params["point2_expression"] = point2_expression
    if wire_feature_name is not None:
        params["wire_feature_name"] = wire_feature_name
    if wire_set_name is not None:
        params["wire_set_name"] = wire_set_name
    params.update(kwargs)
    return _action("wire_connector", model, **params)
