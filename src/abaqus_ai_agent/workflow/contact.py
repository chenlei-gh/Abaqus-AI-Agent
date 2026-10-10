from dataclasses import dataclass, field

from ..actions import builders


@dataclass(frozen=True)
class ContactAnalysisPlan:
    model_name: str
    actions: tuple = field(default_factory=tuple)
    notes: tuple = field(default_factory=tuple)


def build_contact_plan(
    model_name,
    material,
    region_map,
    contact_property_name="ContactProp-1",
    normal_behavior=True,
    pressure_overclosure="HARD",
    friction_coefficient=None,
    sliding="FINITE",
    step_name="Step-1",
    job_name="AI-ContactJob",
    field_variables=("S", "U", "RF", "CSTRESS", "CDISP", "CSTATUS"),
    nlgeom=True,
):
    """Build an inspectable contact-analysis plan without executing it.

    region_map must declare 'master_surface' and 'slave_surface', and optionally
    'fixed_base' and 'moving_slider'.
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

    tangential = (
        {"formulation": "PENALTY", "friction": float(friction_coefficient)}
        if friction_coefficient is not None
        else {"formulation": "FRICTIONLESS"}
    )
    actions = [
        builders.material_elastic(
            model_name,
            mat_name,
            mat_e,
            mat_nu,
        ),
        builders.contact_property(
            model_name,
            name=contact_property_name,
            normal_behavior=normal_behavior,
            pressure_overclosure=pressure_overclosure,
            tangential_behavior=tangential,
        ),
        builders.contact(
            model_name,
            name="Contact-1",
            master_expression=region_map["master_surface"],
            slave_expression=region_map["slave_surface"],
            property=contact_property_name,
            sliding=sliding,
            step="Initial",
        ),
        builders.static_step(model_name, step_name, nlgeom=nlgeom),
    ]

    if mat_density is not None:
        actions.append(
            builders.material_density(model_name, mat_name, mat_density)
        )

    if region_map.get("fixed_base"):
        actions.append(
            builders.fixed_bc(
                model_name,
                "FixedBaseBC",
                region_map["fixed_base"],
                step="Initial",
            )
        )

    actions.append(
        builders.field_output(
            model_name,
            variables=field_variables,
            request="F-Output-1",
            step=step_name,
        )
    )
    actions.append(builders.create_job(model_name, job_name))

    return ContactAnalysisPlan(
        model_name,
        tuple(actions),
        ("Geometry surfaces and contact regions must be grounded before mutation.",),
    )
