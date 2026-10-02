from dataclasses import dataclass, field

from ..actions import builders


@dataclass(frozen=True)
class ThermalAnalysisPlan:
    model_name: str
    actions: tuple = field(default_factory=tuple)
    notes: tuple = field(default_factory=tuple)


def build_thermal_plan(model_name, material, region_map,
                       temperature_bcs=(), surface_heat_fluxes=(), body_heat_fluxes=(),
                       response="STEADY_STATE", time_period=1.0,
                       job_name="AI-ThermalJob", step_name="Step-1",
                       field_variables=("NT", "HFL", "RFL")):
    """Build an inspectable heat-transfer analysis plan without executing it.

    region_map must contain explicit Abaqus Python expressions.
    material must provide conductivity (either as float or tuple of tuples).
    """
    cond = material["conductivity"]
    cond_table = ((float(cond),),) if isinstance(cond, (int, float)) else tuple(cond)

    actions = [
        builders.material_conductivity(model_name, material["name"], cond_table),
        builders.heat_transfer_step(
            model_name, name=step_name, response=response, time_period=time_period
        ),
    ]

    if material.get("specific_heat") is not None:
        sh = material["specific_heat"]
        sh_table = ((float(sh),),) if isinstance(sh, (int, float)) else tuple(sh)
        actions.append(builders.material_specific_heat(model_name, material["name"], sh_table))

    if material.get("density") is not None:
        actions.append(builders.material_density(model_name, material["name"], material["density"]))

    if region_map.get("section"):
        actions.append(builders.solid_section(model_name, region_map["section"], material["name"]))

    for bc in temperature_bcs or ():
        actions.append(builders.temperature_bc(
            model_name,
            name=bc["name"],
            region_expression=bc["region"],
            magnitude=bc["magnitude"],
            step=bc.get("step", step_name),
        ))

    for flux in surface_heat_fluxes or ():
        actions.append(builders.surface_heat_flux(
            model_name,
            name=flux["name"],
            region_expression=flux["region"],
            magnitude=flux["magnitude"],
            step=flux.get("step", step_name),
        ))

    for bflux in body_heat_fluxes or ():
        actions.append(builders.body_heat_flux(
            model_name,
            name=bflux["name"],
            region_expression=bflux["region"],
            magnitude=bflux["magnitude"],
            step=bflux.get("step", step_name),
        ))

    actions.append(builders.field_output(
        model_name, variables=field_variables, request="F-Output-1", step=step_name
    ))
    actions.append(builders.create_job(model_name, job_name))
    return ThermalAnalysisPlan(
        model_name,
        tuple(actions),
        ("Geometry regions must be grounded before mutation.",),
    )
