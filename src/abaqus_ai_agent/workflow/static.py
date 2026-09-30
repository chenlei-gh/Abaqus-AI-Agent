from dataclasses import dataclass, field

from ..actions import builders


@dataclass(frozen=True)
class StaticAnalysisPlan:
    model_name: str
    actions: tuple = field(default_factory=tuple)
    notes: tuple = field(default_factory=tuple)


def build_static_plan(model_name, material, region_map, force=None, pressure=None,
                      job_name="AI-Job", step_name="Step-1"):
    """Build an inspectable static-analysis plan without executing it.

    region_map must contain explicit Abaqus Python expressions, normally
    produced by the geometry-grounding layer or confirmed by a user.
    """
    actions = [
        builders.material_elastic(model_name, material["name"], material["youngs_modulus"], material["poisson"]),
        builders.static_step(model_name, step_name),
    ]
    if material.get("density") is not None:
        actions.append(builders.material_density(model_name, material["name"], material["density"]))
    if region_map.get("section"):
        actions.append(builders.solid_section(model_name, region_map["section"], material["name"]))
    if region_map.get("fixed"):
        actions.append(builders.fixed_bc(model_name, "AI-Fixed", region_map["fixed"], step="Initial"))
    if force:
        actions.append(builders.concentrated_force(model_name, "AI-Force", region_map["load"], **force))
    if pressure:
        actions.append(builders.pressure_load(model_name, "AI-Pressure", region_map["load"], pressure["magnitude"], step=step_name))
    actions.append(builders.field_output(model_name))
    actions.append(builders.create_job(model_name, job_name))
    return StaticAnalysisPlan(model_name, tuple(actions), ("Geometry regions must be grounded before mutation.",))
