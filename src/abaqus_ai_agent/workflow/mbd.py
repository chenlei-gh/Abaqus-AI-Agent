from dataclasses import dataclass, field

from ..actions import builders


@dataclass(frozen=True)
class MultiBodyAnalysisPlan:
    model_name: str
    actions: tuple = field(default_factory=tuple)
    notes: tuple = field(default_factory=tuple)


def build_mbd_plan(
    model_name,
    part_name,
    material,
    pivot_coords,
    body_set_expression,
    step_name="Step-1",
    job_name="AI-MBDJob",
    time_period=2.0,
    gravity_vector=(0.0, -9810.0, 0.0),
    field_variables=("U", "UR", "V", "VR", "RF", "RM"),
    history_variables=("ALLIE", "ALLKE", "ALLWK", "ALLSE", "ETOTAL"),
    nlgeom=True,
    num_intervals=50,
):
    """Build an inspectable Multi-Body Dynamics analysis plan."""
    actions = [
        builders.material_elastic(
            model_name,
            material["name"],
            material["youngs_modulus"],
            material["poisson"],
        ),
        builders.material_density(
            model_name,
            material["name"],
            material["density"],
        ),
        builders.solid_section(
            model_name,
            "SolidSection",
            material=material["name"],
        ),
        builders.section_assignment(
            model_name,
            part_name,
            "SolidSection",
            body_set_expression,
        ),
        builders.reference_point(
            model_name,
            name="RP_Pivot",
            coordinates=pivot_coords,
        ),
        builders.rigid_body(
            model_name,
            name="RigidBody-1",
            ref_point_expression="mdb.models['%s'].rootAssembly.sets['RP_Pivot']" % model_name,
            body_expression=body_set_expression,
        ),
        builders.displacement_bc(
            model_name,
            name="HingeBC",
            region_expression="mdb.models['%s'].rootAssembly.sets['RP_Pivot']" % model_name,
            step="Initial",
            u1=0.0,
            u2=0.0,
            u3=0.0,
            ur1=0.0,
            ur2=0.0,
            ur3="UNSET",
        ),
        builders.implicit_dynamic_step(
            model_name,
            name=step_name,
            previous="Initial",
            time_period=time_period,
            nlgeom=nlgeom,
            max_num_inc=500,
        ),
        builders.gravity(
            model_name,
            name="Gravity",
            comp1=gravity_vector[0],
            comp2=gravity_vector[1],
            comp3=gravity_vector[2],
            step=step_name,
        ),
        builders.field_output(
            model_name,
            variables=field_variables,
            request="F-Output-1",
            step=step_name,
            num_intervals=num_intervals,
        ),
        builders.history_output(
            model_name,
            variables=history_variables,
            request="H-Output-1",
            step=step_name,
        ),
        builders.create_job(model_name, job_name, job_type="STANDARD"),
    ]
    notes = (
        "Multi-body rigid body dynamics with hinge/revolute kinematic constraint at reference point.",
        "Gravity driven nonlinear implicit dynamic oscillation.",
    )
    return MultiBodyAnalysisPlan(model_name=model_name, actions=tuple(actions), notes=notes)
