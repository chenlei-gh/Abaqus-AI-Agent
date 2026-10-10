from dataclasses import dataclass, field
from typing import Any, Optional

from ..actions import builders


@dataclass(frozen=True)
class StaticAnalysisPlan:
    model_name: str
    actions: tuple = field(default_factory=tuple)
    notes: tuple = field(default_factory=tuple)
    material: Optional[Any] = None


def build_static_plan(model_name, material, region_map, force=None, pressure=None,
                      job_name="AI-Job", step_name="Step-1"):
    """Build an inspectable static-analysis plan without executing it.

    region_map must contain explicit Abaqus Python expressions, normally
    produced by the geometry-grounding layer or confirmed by a user.
    """
    from ..reasoning.material_catalog import resolve_material_to_definition
    mat_def = resolve_material_to_definition(material, fail_closed=False)
    if mat_def is not None:
        mat_name = mat_def.name
        mat_e = mat_def.elastic.youngs_modulus if mat_def.elastic else 210000.0
        mat_nu = mat_def.elastic.poisson_ratio if mat_def.elastic else 0.3
        mat_density = mat_def.density
    elif isinstance(material, dict):
        mat_name = material.get("name", "DefaultMaterial")
        mat_e = material.get("youngs_modulus") or material.get("elastic_modulus") or 210000.0
        mat_nu = (
            material.get("poisson")
            if material.get("poisson") is not None
            else (material.get("poisson_ratio") if material.get("poisson_ratio") is not None else 0.3)
        )
        mat_density = material.get("density")
    else:
        raise ValueError(f"Cannot resolve material: {material}")

    actions = [
        builders.material_elastic(model_name, mat_name, mat_e, mat_nu),
        builders.static_step(model_name, step_name),
    ]
    if mat_density is not None:
        actions.append(builders.material_density(model_name, mat_name, mat_density))
    if region_map.get("section"):
        actions.append(builders.solid_section(model_name, region_map["section"], mat_name))
    if region_map.get("fixed"):
        actions.append(builders.fixed_bc(model_name, "AI-Fixed", region_map["fixed"], step="Initial"))
    if force:
        actions.append(builders.concentrated_force(model_name, "AI-Force", region_map["load"], **force))
    if pressure:
        actions.append(builders.pressure_load(model_name, "AI-Pressure", region_map["load"], pressure["magnitude"], step=step_name))
    actions.append(builders.field_output(model_name))
    actions.append(builders.create_job(model_name, job_name))
    return StaticAnalysisPlan(
        model_name,
        tuple(actions),
        ("Geometry regions must be grounded before mutation.",),
        material=mat_def or material,
    )
