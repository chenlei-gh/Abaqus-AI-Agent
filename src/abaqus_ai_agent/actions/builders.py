from ..contracts.action import AbaqusAction


def _action(kind, model, target, **parameters):
    return AbaqusAction(kind, model, target, parameters, True)


def material_elastic(model, name, youngs_modulus, poisson):
    return _action("material_elastic", model, None, name=name, youngs_modulus=youngs_modulus, poisson=poisson)


def material_density(model, name, density):
    return _action("material_density", model, None, name=name, density=density)


def solid_section(model, name, material):
    return _action("solid_section", model, None, name=name, material=material)


def mesh_controls(model, target, **params):
    return _action("mesh_controls", model, target, **params)


def static_step(model, name="Step-1", previous="Initial", nlgeom=False):
    return _action("static_step", model, None, name=name, previous=previous, nlgeom=nlgeom)


def fixed_bc(model, name, region_expression, step="Initial"):
    return _action("fixed_bc", model, region_expression, name=name, region_expression=region_expression, step=step)


def displacement_bc(model, name, region_expression, step="Initial", **values):
    return _action("displacement_bc", model, region_expression, name=name, region_expression=region_expression, step=step, **values)


def pressure_load(model, name, region_expression, magnitude, step="Step-1"):
    return _action("pressure_load", model, region_expression, name=name, region_expression=region_expression, magnitude=magnitude, step=step)


def concentrated_force(model, name, region_expression, cf1=0.0, cf2=0.0, cf3=0.0, step="Step-1"):
    return _action("concentrated_force", model, region_expression, name=name, region_expression=region_expression, cf1=cf1, cf2=cf2, cf3=cf3, step=step)


def field_output(model, variables=("S", "U", "RF"), request="F-Output-1"):
    return _action("field_output", model, None, variables=variables, request=request)


def create_job(model, name):
    return _action("create_job", model, None, name=name)


def submit_job(model, name):
    return _action("submit_job", model, None, name=name)
