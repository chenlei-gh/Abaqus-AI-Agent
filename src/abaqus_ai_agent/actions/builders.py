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
def static_step(model, name="Step-1", previous="Initial", nlgeom=False): return _action("static_step", model, name=name, previous=previous, nlgeom=nlgeom)
def dynamic_explicit_step(model, name="Step-1", previous="Initial", time_period=1.0): return _action("dynamic_explicit_step", model, name=name, previous=previous, time_period=time_period)
def frequency_step(model, name="Step-1", previous="Initial", num_eigen=10): return _action("frequency_step", model, name=name, previous=previous, num_eigen=num_eigen)
def heat_transfer_step(model, name="Step-1", previous="Initial", response="TRANSIENT", time_period=1.0): return _action("heat_transfer_step", model, name=name, previous=previous, response=response, time_period=time_period)
def coupled_temp_displacement_step(model, name="Step-1", previous="Initial", response="TRANSIENT", time_period=1.0, nlgeom=False): return _action("coupled_temp_displacement_step", model, name=name, previous=previous, response=response, time_period=time_period, nlgeom=nlgeom)
def fixed_bc(model, name, region_expression, step="Initial"): return _action("fixed_bc", model, region_expression, name=name, region_expression=region_expression, step=step)
def displacement_bc(model, name, region_expression, step="Initial", **values): return _action("displacement_bc", model, region_expression, name=name, region_expression=region_expression, step=step, **values)
def symmetry_bc(model, name, region_expression, step="Initial", plane="X"): return _action("symmetry_bc", model, region_expression, name=name, region_expression=region_expression, step=step, plane=plane)
def temperature_bc(model, name, region_expression, magnitude, step="Step-1"): return _action("temperature_bc", model, region_expression, name=name, region_expression=region_expression, magnitude=magnitude, step=step)
def pressure_load(model, name, region_expression, magnitude, step="Step-1"): return _action("pressure_load", model, region_expression, name=name, region_expression=region_expression, magnitude=magnitude, step=step)
def concentrated_force(model, name, region_expression, cf1=0.0, cf2=0.0, cf3=0.0, step="Step-1"): return _action("concentrated_force", model, region_expression, name=name, region_expression=region_expression, cf1=cf1, cf2=cf2, cf3=cf3, step=step)
def body_force(model, name, region_expression, comp1=0.0, comp2=0.0, comp3=0.0, step="Step-1"): return _action("body_force", model, region_expression, name=name, region_expression=region_expression, comp1=comp1, comp2=comp2, comp3=comp3, step=step)
def body_heat_flux(model, name, region_expression, magnitude, step="Step-1"): return _action("body_heat_flux", model, region_expression, name=name, region_expression=region_expression, magnitude=magnitude, step=step)
def surface_heat_flux(model, name, region_expression, magnitude, step="Step-1"): return _action("surface_heat_flux", model, region_expression, name=name, region_expression=region_expression, magnitude=magnitude, step=step)
def field_output(model, variables=("S", "U", "RF"), request="F-Output-1", step="Initial"): return _action("field_output", model, variables=variables, request=request, step=step)
def history_output(model, variables=("ALLIE", "ALLKE", "ALLSE"), request="H-Output-1", region_expression=None, step="Step-1"): return _action("history_output", model, variables=variables, request=request, region_expression=region_expression, step=step)
def create_job(model, name, job_type="STANDARD"): return _action("create_job", model, name=name, job_type=job_type)
def submit_job(model, name): return _action("submit_job", model, name=name)
def tie(model, name, master_expression, slave_expression): return _action("tie", model, name=name, master_expression=master_expression, slave_expression=slave_expression)

def local_seed_size(model, part, region_expression, size, constraint="FREE"):
    return _action("local_seed_size", model, region_expression, part=part, region_expression=region_expression, size=size, constraint=constraint)

def local_seed_number(model, part, region_expression, number, constraint="FREE"):
    return _action("local_seed_number", model, region_expression, part=part, region_expression=region_expression, number=number, constraint=constraint)

def inspect_geometry(model, part, min_edge_length=None, min_face_size=None):
    return _action("inspect_geometry", model, part=part, min_edge_length=min_edge_length, min_face_size=min_face_size)

def ignore_entity(model, part, region_expression):
    return _action("ignore_entity", model, region_expression, part=part, region_expression=region_expression)

def restore_entity(model, part, region_expression):
    return _action("restore_entity", model, region_expression, part=part, region_expression=region_expression)

def repair_geometry(model, part):
    return _action("repair_geometry", model, part=part)

def remove_redundant_entities(model, part):
    return _action("remove_redundant_entities", model, part=part)

def inspect_mesh(model, part):
    return _action("inspect_mesh", model, part=part)

def mesh_quality(model, part, **params):
    return _action("mesh_quality", model, part=part, **params)

def contact_property(model, name, normal_behavior=True, pressure_overclosure="HARD", tangential_behavior=None):
    return _action("contact_property", model, name=name, normal_behavior=normal_behavior, pressure_overclosure=pressure_overclosure, tangential_behavior=tangential_behavior)

def contact(model, name, master_expression, slave_expression, property, sliding="FINITE", step="Initial"):
    return _action("contact", model, name=name, master_expression=master_expression, slave_expression=slave_expression, property=property, sliding=sliding, step=step)
