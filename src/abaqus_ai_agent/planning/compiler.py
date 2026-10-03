"""R1: Agent-Native Engineering Intent Compiler.

Compiles high-level EngineeringIntent specifications into an executable,
ordered sequence of AbaqusActions, and renders them into native Abaqus/CAE Python scripts.
Eliminates hardcoded CAE scripts in favor of dynamic intent compilation.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts.action import AbaqusAction
from ..contracts.material import MaterialDefinition
from ..contracts.procedure import (
    BoltPretensionLifecycleSpec,
    BoltPretensionMethod,
    MomentLoadSpec,
    MomentTransferStrategy,
    MultiStepProcedureSpec,
    SpatialLoadField,
    StepDependency,
    validate_field_expression,
)
from ..actions import builders
from ..actions.script import action_to_script
from ..grounding.feature_grounding import GroundedRegion


@dataclass(frozen=True)
class IntentGeometrySpec:
    shape: str = "cantilever_box"             # "cantilever_box", "cylinder", "plate", "plate_with_hole", "step_file"
    length: float = 100.0                     # mm
    width: float = 10.0                       # mm
    height: float = 10.0                      # mm
    radius: Optional[float] = None
    thickness: Optional[float] = None
    step_file_path: Optional[str] = None


@dataclass(frozen=True)
class IntentBoundarySpec:
    name: str
    bc_type: str                              # "ENCASTRE", "PINNED", "DISPLACEMENT", "XSYMM", "YSYMM", "ZSYMM", "SYMMETRY"
    region: str                               # e.g. "FixedFace", "Root", "SYMMETRY_PLANE_X"
    values: Dict[str, float] = field(default_factory=dict)
    step: str = "Initial"
    plane: Optional[str] = None


@dataclass(frozen=True)
class IntentLoadSpec:
    name: str
    load_type: str                            # "concentrated_force", "pressure", "gravity", "moment"
    region: str                               # e.g. "TipFace", "TopSurface"
    magnitude: float
    direction: str = "CF2"                    # "CF1", "CF2", "CF3"
    step: Optional[str] = None
    field: Optional[str] = None
    distribution_type: str = "UNIFORM"
    axis: Optional[str] = None


@dataclass(frozen=True)
class IntentStepSpec:
    name: str = "Step-1"
    step_type: str = "static_general"         # "static_general", "frequency", "implicit_dynamic", "explicit_dynamic", "heat_transfer"
    nlgeom: bool = False
    time_period: float = 1.0
    previous: str = "Initial"


@dataclass(frozen=True)
class IntentMeshSpec:
    element_type: str = "C3D8R"
    global_size: float = 2.5
    deviation_factor: float = 0.1


@dataclass(frozen=True)
class CompiledAgentPlan:
    """The outcome of compiling an intent into native actions and executable CAE script."""
    model_name: str
    part_name: str
    job_name: str
    actions: Tuple[AbaqusAction, ...]
    cae_script: str
    intent_summary: Dict[str, Any]


def compile_intent_to_actions(
    model_name: str,
    part_name: str,
    job_name: str,
    geometry: IntentGeometrySpec,
    material: MaterialDefinition,
    step: Optional[IntentStepSpec] = None,
    bcs: Sequence[IntentBoundarySpec] = (),
    loads: Sequence[IntentLoadSpec] = (),
    mesh: IntentMeshSpec = IntentMeshSpec(),
    grounded_regions: Optional[Dict[str, GroundedRegion]] = None,
    steps: Optional[Sequence[IntentStepSpec]] = None,
    procedure: Optional[MultiStepProcedureSpec] = None,
    fields: Optional[Sequence[SpatialLoadField]] = None,
    bolt_pretensions: Optional[Sequence[BoltPretensionLifecycleSpec]] = None,
    moments: Optional[Sequence[MomentLoadSpec]] = None,
) -> CompiledAgentPlan:
    """Compile structured engineering intent into an ordered sequence of AbaqusActions."""
    actions: List[AbaqusAction] = []

    # 1. Geometry Construction (Native Python CAE Action)
    if geometry.shape == "plate_with_hole":
        p_width = geometry.width if geometry.width > 0 else 100.0
        p_height = geometry.height if geometry.height > 20.0 else (geometry.length if geometry.length > 20.0 else 100.0)
        p_depth = geometry.thickness if geometry.thickness is not None else 20.0
        p_radius = geometry.radius if geometry.radius is not None else 10.0
        geo_code = (
            f"s = mdb.models['{model_name}'].ConstrainedSketch(name='__profile__', sheetSize=200.0)\n"
            f"s.rectangle(point1=(0.0, 0.0), point2=({p_width}, {p_height}))\n"
            f"s.CircleByCenterPerimeter(center=({p_width/2.0}, {p_height/2.0}), "
            f"point1=({p_width/2.0 + p_radius}, {p_height/2.0}))\n"
            f"p = mdb.models['{model_name}'].Part(name='{part_name}', dimensionality=THREE_D, type=DEFORMABLE_BODY)\n"
            f"p.BaseSolidExtrude(sketch=s, depth={p_depth})\n"
            f"del mdb.models['{model_name}'].sketches['__profile__']\n"
        )
    elif geometry.shape == "cantilever_box":
        geo_code = (
            f"s = mdb.models['{model_name}'].ConstrainedSketch(name='__profile__', sheetSize=200.0)\n"
            f"s.rectangle(point1=(0.0, 0.0), point2=({geometry.width}, {geometry.height}))\n"
            f"p = mdb.models['{model_name}'].Part(name='{part_name}', dimensionality=THREE_D, type=DEFORMABLE_BODY)\n"
            f"p.BaseSolidExtrude(sketch=s, depth={geometry.length})\n"
            f"del mdb.models['{model_name}'].sketches['__profile__']\n"
        )
    else:
        geo_code = (
            f"s = mdb.models['{model_name}'].ConstrainedSketch(name='__profile__', sheetSize=200.0)\n"
            f"s.rectangle(point1=(0.0, 0.0), point2=({geometry.width}, {geometry.height}))\n"
            f"p = mdb.models['{model_name}'].Part(name='{part_name}', dimensionality=THREE_D, type=DEFORMABLE_BODY)\n"
            f"p.BaseSolidExtrude(sketch=s, depth={geometry.length})\n"
            f"del mdb.models['{model_name}'].sketches['__profile__']\n"
        )
    actions.append(builders.python_action(model_name, geo_code))

    # 2. Material Definition Actions
    if material.elastic:
        actions.append(builders.material_elastic(
            model=model_name,
            name=material.name,
            youngs_modulus=material.elastic.youngs_modulus,
            poisson=material.elastic.poisson_ratio,
        ))
    if material.density is not None:
        actions.append(builders.material_density(
            model=model_name,
            name=material.name,
            density=material.density,
        ))
    if material.plastic and material.plastic.hardening_table:
        actions.append(builders.material_plastic(
            model=model_name,
            name=material.name,
            table=material.plastic.hardening_table,
        ))

    # 3. Section and Assignment
    sec_name = f"{material.name}_Section"
    actions.append(builders.solid_section(model=model_name, name=sec_name, material=material.name))
    sec_assign_code = (
        f"p = mdb.models['{model_name}'].parts['{part_name}']\n"
        f"c = p.cells\n"
        f"region = p.Set(cells=c, name='AllCells')\n"
        f"p.SectionAssignment(region=region, sectionName='{sec_name}')\n"
    )
    actions.append(builders.python_action(model_name, sec_assign_code))

    # 4. Assembly Instance
    inst_name = f"{part_name}-1"
    inst_code = (
        f"a = mdb.models['{model_name}'].rootAssembly\n"
        f"a.DatumCsysByDefault(CARTESIAN)\n"
        f"a.Instance(name='{inst_name}', part=p, dependent=ON)\n"
    )
    actions.append(builders.python_action(model_name, inst_code))

    # 5. Spatial Expression Fields
    if fields:
        for f in fields:
            valid, err = validate_field_expression(f.expression)
            if not valid:
                raise ValueError(f"Invalid field expression '{f.expression}': {err}")
            actions.append(builders.expression_field(
                model=model_name,
                name=f.name,
                expression=f.expression,
            ))

    # 6. Analysis Steps Actions
    defined_steps: List[str] = []
    if procedure is not None:
        valid, errors = procedure.validate_dag()
        if not valid:
            raise ValueError(f"Invalid procedure DAG: {'; '.join(errors)}")
        for s in procedure.steps:
            proc_type = s.procedure.lower() if s.procedure else "static"
            nlgeom_val = s.nlgeom if s.nlgeom is not None else False
            if proc_type in ("static", "static_general"):
                actions.append(builders.static_step(
                    model=model_name,
                    name=s.name,
                    previous=s.previous,
                    nlgeom=nlgeom_val,
                    time_period=s.time_period,
                    initial_inc=s.initial_inc,
                    min_inc=s.min_inc,
                    max_inc=s.max_inc,
                    max_num_inc=s.max_num_inc,
                ))
            elif proc_type == "frequency":
                actions.append(builders.frequency_step(
                    model=model_name,
                    name=s.name,
                    previous=s.previous,
                ))
            elif proc_type in ("implicit_dynamic", "dynamic_implicit"):
                actions.append(builders.implicit_dynamic_step(
                    model=model_name,
                    name=s.name,
                    previous=s.previous,
                    nlgeom=nlgeom_val,
                    time_period=s.time_period,
                    initial_inc=s.initial_inc,
                    min_inc=s.min_inc,
                    max_inc=s.max_inc,
                    max_num_inc=s.max_num_inc,
                ))
            elif proc_type in ("explicit_dynamic", "dynamic_explicit"):
                actions.append(builders.dynamic_explicit_step(
                    model=model_name,
                    name=s.name,
                    previous=s.previous,
                    time_period=s.time_period,
                    nlgeom=nlgeom_val,
                ))
            elif proc_type == "heat_transfer":
                actions.append(builders.heat_transfer_step(
                    model=model_name,
                    name=s.name,
                    previous=s.previous,
                    time_period=s.time_period,
                    initial_inc=s.initial_inc,
                    min_inc=s.min_inc,
                    max_inc=s.max_inc,
                    max_num_inc=s.max_num_inc,
                ))
            else:
                actions.append(builders.static_step(
                    model=model_name,
                    name=s.name,
                    previous=s.previous,
                ))
            defined_steps.append(s.name)
        default_step_name = defined_steps[0]
    elif steps is not None and len(steps) > 0:
        for idx, s in enumerate(steps):
            prev = s.previous if (s.previous != "Initial" or idx == 0) else steps[idx - 1].name
            if s.step_type in ("static", "static_general"):
                actions.append(builders.static_step(
                    model=model_name,
                    name=s.name,
                    previous=prev,
                    nlgeom=s.nlgeom,
                    time_period=s.time_period,
                ))
            elif s.step_type == "frequency":
                actions.append(builders.frequency_step(
                    model=model_name,
                    name=s.name,
                    previous=prev,
                ))
            else:
                actions.append(builders.static_step(
                    model=model_name,
                    name=s.name,
                    previous=prev,
                ))
            defined_steps.append(s.name)
        default_step_name = defined_steps[0]
    else:
        active_step = step if step is not None else IntentStepSpec(name="Step-1")
        if active_step.step_type in ("static", "static_general"):
            actions.append(builders.static_step(
                model=model_name,
                name=active_step.name,
                previous=active_step.previous,
                nlgeom=active_step.nlgeom,
                time_period=active_step.time_period,
            ))
        elif active_step.step_type == "frequency":
            actions.append(builders.frequency_step(
                model=model_name,
                name=active_step.name,
                previous=active_step.previous,
                num_eigen=10,
            ))
        else:
            actions.append(builders.static_step(
                model=model_name,
                name=active_step.name,
                previous=active_step.previous,
            ))
        defined_steps.append(active_step.name)
        default_step_name = active_step.name

    # 7. Boundary Conditions Actions
    for bc in bcs:
        gr = grounded_regions.get(bc.region) if grounded_regions else None
        bc_step = bc.step if bc.step else "Initial"
        is_symm = bc.bc_type in ("XSYMM", "YSYMM", "ZSYMM") or bc.bc_type == "SYMMETRY"

        if gr is not None:
            pts = gr.anchor_points if gr.anchor_points else (gr.anchor_point,)
            find_at_str = ", ".join(f"(({p[0]}, {p[1]}, {p[2]}),)" for p in pts)
            if gr.entity_type.lower() == "face":
                bc_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"f = a.instances['{inst_name}'].faces\n"
                    f"target_faces = f.findAt({find_at_str})\n"
                    f"region = a.Set(faces=target_faces, name='{bc.region}')\n"
                )
            else:
                bc_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"v = a.instances['{inst_name}'].vertices\n"
                    f"target_verts = v.findAt({find_at_str})\n"
                    f"region = a.Set(vertices=target_verts, name='{bc.region}')\n"
                )

            if is_symm:
                plane = "X"
                if bc.bc_type in ("XSYMM", "YSYMM", "ZSYMM"):
                    plane = bc.bc_type[0]
                elif bc.plane:
                    plane = bc.plane.upper()
                elif bc.values.get("plane"):
                    plane = str(bc.values["plane"]).upper()
                elif gr.target_semantic and gr.target_semantic.upper().startswith("SYMMETRY_PLANE_"):
                    plane = gr.target_semantic.upper().split("_")[-1]

                method_name = {"X": "XsymmBC", "Y": "YsymmBC", "Z": "ZsymmBC"}.get(plane, "XsymmBC")
                bc_code += f"mdb.models['{model_name}'].{method_name}(name='{bc.name}', createStepName='{bc_step}', region=region)\n"
                actions.append(builders.python_action(model_name, bc_code))
                actions.append(builders.symmetry_bc(
                    model=model_name,
                    name=bc.name,
                    region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{bc.region}']",
                    step=bc_step,
                    plane=plane,
                ))
            elif bc.bc_type == "ENCASTRE":
                bc_code += f"mdb.models['{model_name}'].EncastreBC(name='{bc.name}', createStepName='{bc_step}', region=region)\n"
                actions.append(builders.python_action(model_name, bc_code))
                actions.append(builders.fixed_bc(
                    model=model_name,
                    name=bc.name,
                    region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{bc.region}']",
                    step=bc_step,
                ))
            elif bc.bc_type == "PINNED":
                bc_code += f"mdb.models['{model_name}'].PinnedBC(name='{bc.name}', createStepName='{bc_step}', region=region)\n"
                actions.append(builders.python_action(model_name, bc_code))
                actions.append(builders.displacement_bc(
                    model=model_name,
                    name=bc.name,
                    region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{bc.region}']",
                    step=bc_step,
                    u1=0.0, u2=0.0, u3=0.0,
                ))
            else:
                u1 = bc.values.get("u1", 0.0)
                u2 = bc.values.get("u2", 0.0)
                u3 = bc.values.get("u3", 0.0)
                bc_code += (
                    f"mdb.models['{model_name}'].DisplacementBC(name='{bc.name}', createStepName='{bc_step}', "
                    f"region=region, u1={u1}, u2={u2}, u3={u3})\n"
                )
                actions.append(builders.python_action(model_name, bc_code))
                actions.append(builders.displacement_bc(
                    model=model_name,
                    name=bc.name,
                    region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{bc.region}']",
                    step=bc_step,
                    u1=u1, u2=u2, u3=u3,
                ))
        else:
            if is_symm:
                plane = "X"
                if bc.bc_type in ("XSYMM", "YSYMM", "ZSYMM"):
                    plane = bc.bc_type[0]
                elif bc.plane:
                    plane = bc.plane.upper()
                elif bc.values.get("plane"):
                    plane = str(bc.values["plane"]).upper()
                method_name = {"X": "XsymmBC", "Y": "YsymmBC", "Z": "ZsymmBC"}.get(plane, "XsymmBC")
                bc_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"f = a.instances['{inst_name}'].faces\n"
                    f"symm_faces = f.findAt(((0.0, {geometry.height/2.0}, {geometry.length/2.0}),))\n"
                    f"region = a.Set(faces=symm_faces, name='{bc.region}')\n"
                    f"mdb.models['{model_name}'].{method_name}(name='{bc.name}', createStepName='{bc_step}', region=region)\n"
                )
                actions.append(builders.python_action(model_name, bc_code))
                actions.append(builders.symmetry_bc(
                    model=model_name,
                    name=bc.name,
                    region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{bc.region}']",
                    step=bc_step,
                    plane=plane,
                ))
            elif bc.bc_type == "ENCASTRE":
                bc_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"f = a.instances['{inst_name}'].faces\n"
                    f"fixed_faces = f.findAt((({geometry.width/2.0}, {geometry.height/2.0}, 0.0),))\n"
                    f"region = a.Set(faces=fixed_faces, name='{bc.region}')\n"
                    f"mdb.models['{model_name}'].EncastreBC(name='{bc.name}', createStepName='{bc_step}', region=region)\n"
                )
                actions.append(builders.python_action(model_name, bc_code))
                actions.append(builders.fixed_bc(
                    model=model_name,
                    name=bc.name,
                    region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{bc.region}']",
                    step=bc_step,
                ))

    # 8. Standard Loads Actions
    for ld in loads:
        gr = grounded_regions.get(ld.region) if grounded_regions else None
        target_step = ld.step if ld.step else default_step_name
        field_arg = f", distributionType=FIELD, field='{ld.field}'" if ld.field else ""

        if gr is not None:
            pts = gr.anchor_points if gr.anchor_points else (gr.anchor_point,)
            find_at_str = ", ".join(f"(({p[0]}, {p[1]}, {p[2]}),)" for p in pts)
            if ld.load_type == "pressure":
                load_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"f = a.instances['{inst_name}'].faces\n"
                    f"target_faces = f.findAt({find_at_str})\n"
                    f"surf = a.Surface(side1Faces=target_faces, name='{ld.region}_Surf')\n"
                    f"mdb.models['{model_name}'].Pressure(name='{ld.name}', createStepName='{target_step}', "
                    f"region=surf, magnitude={ld.magnitude}{field_arg})\n"
                )
                actions.append(builders.python_action(model_name, load_code))
                actions.append(builders.pressure_load(
                    model=model_name,
                    name=ld.name,
                    region_expression=f"mdb.models['{model_name}'].rootAssembly.surfaces['{ld.region}_Surf']",
                    magnitude=ld.magnitude,
                    step=target_step,
                    field=ld.field,
                ))
            elif ld.load_type == "concentrated_force":
                if gr.entity_type.lower() == "face":
                    p_width = geometry.width if geometry.width > 0 else 100.0
                    p_height = geometry.height if geometry.height > 20.0 else (geometry.length if geometry.length > 20.0 else 100.0)
                    p_radius = geometry.radius if geometry.radius is not None else 10.0
                    face_area = (p_width * p_height) - (math.pi * p_radius**2)
                    eq_pressure = abs(ld.magnitude) / face_area
                    load_code = (
                        f"# Total force {ld.magnitude} N on face converted to equivalent surface pressure: {eq_pressure:.6f} MPa\n"
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"f = a.instances['{inst_name}'].faces\n"
                        f"target_faces = f.findAt({find_at_str})\n"
                        f"surf = a.Surface(side1Faces=target_faces, name='{ld.region}_Surf')\n"
                        f"mdb.models['{model_name}'].Pressure(name='{ld.name}', createStepName='{target_step}', "
                        f"region=surf, magnitude={eq_pressure}{field_arg})\n"
                    )
                    actions.append(builders.python_action(model_name, load_code))
                    actions.append(builders.pressure_load(
                        model=model_name,
                        name=ld.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.surfaces['{ld.region}_Surf']",
                        magnitude=eq_pressure,
                        step=target_step,
                        field=ld.field,
                    ))
                else:
                    load_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"v = a.instances['{inst_name}'].vertices\n"
                        f"target_verts = v.findAt({find_at_str})\n"
                        f"region = a.Set(vertices=target_verts, name='{ld.region}')\n"
                        f"mdb.models['{model_name}'].ConcentratedForce(name='{ld.name}', createStepName='{target_step}', "
                        f"region=region, {ld.direction}={ld.magnitude})\n"
                    )
                    actions.append(builders.python_action(model_name, load_code))
                    cf_args = {ld.direction.lower(): ld.magnitude}
                    actions.append(builders.concentrated_force(
                        model=model_name,
                        name=ld.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{ld.region}']",
                        step=target_step,
                        **cf_args,
                    ))
        else:
            if ld.load_type == "concentrated_force":
                load_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"v = a.instances['{inst_name}'].vertices\n"
                    f"tip_verts = v.findAt((({geometry.width}, {geometry.height}, {geometry.length}),))\n"
                    f"region = a.Set(vertices=tip_verts, name='{ld.region}')\n"
                    f"cf_val = {ld.magnitude}\n"
                    f"mdb.models['{model_name}'].ConcentratedForce(name='{ld.name}', createStepName='{target_step}', "
                    f"region=region, {ld.direction}=cf_val)\n"
                )
                actions.append(builders.python_action(model_name, load_code))
                cf_args = {ld.direction.lower(): ld.magnitude}
                actions.append(builders.concentrated_force(
                    model=model_name,
                    name=ld.name,
                    region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{ld.region}']",
                    step=target_step,
                    **cf_args,
                ))
            elif ld.load_type == "pressure":
                load_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"f = a.instances['{inst_name}'].faces\n"
                    f"top_faces = f.findAt((({geometry.width/2.0}, {geometry.height/2.0}, {geometry.length}),))\n"
                    f"surf = a.Surface(side1Faces=top_faces, name='{ld.region}_Surf')\n"
                    f"mdb.models['{model_name}'].Pressure(name='{ld.name}', createStepName='{target_step}', "
                    f"region=surf, magnitude={ld.magnitude}{field_arg})\n"
                )
                actions.append(builders.python_action(model_name, load_code))
                actions.append(builders.pressure_load(
                    model=model_name,
                    name=ld.name,
                    region_expression=f"mdb.models['{model_name}'].rootAssembly.surfaces['{ld.region}_Surf']",
                    magnitude=ld.magnitude,
                    step=target_step,
                    field=ld.field,
                ))

    # 9. Moment / Torque Actions
    if moments:
        for m_spec in moments:
            m_step = m_spec.step if m_spec.step else default_step_name
            cm1 = m_spec.magnitude if m_spec.axis.upper() == "CM1" else 0.0
            cm2 = m_spec.magnitude if m_spec.axis.upper() == "CM2" else 0.0
            cm3 = m_spec.magnitude if m_spec.axis.upper() == "CM3" else 0.0

            if m_spec.strategy == MomentTransferStrategy.RP_COUPLING:
                gr = grounded_regions.get(m_spec.region_expression) if grounded_regions else None
                if gr is not None:
                    pts = gr.anchor_points if gr.anchor_points else (gr.anchor_point,)
                    find_at_str = ", ".join(f"(({p[0]}, {p[1]}, {p[2]}),)" for p in pts)
                    rp_pt = m_spec.rp_coordinates if m_spec.rp_coordinates else gr.anchor_point
                else:
                    rp_pt = m_spec.rp_coordinates if m_spec.rp_coordinates else (geometry.width / 2.0, geometry.height / 2.0, geometry.length)
                    find_at_str = f"(({rp_pt[0]}, {rp_pt[1]}, {rp_pt[2]}),)"

                rp_pt_str = f"({rp_pt[0]}, {rp_pt[1]}, {rp_pt[2]})"
                coupling_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"f = a.instances['{inst_name}'].faces\n"
                    f"target_faces = f.findAt({find_at_str})\n"
                    f"surf = a.Surface(side1Faces=target_faces, name='{m_spec.name}_Surf')\n"
                    f"rp_feat = a.ReferencePoint(point={rp_pt_str})\n"
                    f"rp_ref = a.referencePoints[rp_feat.id]\n"
                    f"rp_set = a.Set(name='{m_spec.name}_RP_Set', referencePoints=(rp_ref,))\n"
                    f"mdb.models['{model_name}'].Coupling(name='{m_spec.name}_Coupling', controlPoint=rp_set, "
                    f"surface=surf, influenceRadius=WHOLE_SURFACE, couplingType=KINEMATIC, "
                    f"u1=ON, u2=ON, u3=ON, ur1=ON, ur2=ON, ur3=ON)\n"
                    f"mdb.models['{model_name}'].Moment(name='{m_spec.name}', createStepName='{m_step}', "
                    f"region=rp_set, cm1={cm1}, cm2={cm2}, cm3={cm3})\n"
                )
                actions.append(builders.python_action(model_name, coupling_code))
                actions.append(builders.reference_point(model=model_name, name=f"{m_spec.name}_RP_Set", coordinates=rp_pt))
                actions.append(builders.coupling_constraint(
                    model=model_name,
                    name=f"{m_spec.name}_Coupling",
                    control_point_name=f"{m_spec.name}_RP_Set",
                    surface_name=f"{m_spec.name}_Surf",
                    coupling_type="KINEMATIC",
                ))
                actions.append(builders.concentrated_moment(
                    model=model_name,
                    name=m_spec.name,
                    region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{m_spec.name}_RP_Set']",
                    cm1=cm1, cm2=cm2, cm3=cm3,
                    step=m_step,
                    strategy="RP_COUPLING",
                ))
            else:
                actions.append(builders.concentrated_moment(
                    model=model_name,
                    name=m_spec.name,
                    region_expression=m_spec.region_expression,
                    cm1=cm1, cm2=cm2, cm3=cm3,
                    step=m_step,
                    strategy=m_spec.strategy.value if hasattr(m_spec.strategy, "value") else str(m_spec.strategy),
                ))

    # 10. Bolt Pretension Actions
    if bolt_pretensions:
        for b_spec in bolt_pretensions:
            gr = grounded_regions.get(b_spec.region_expression) if grounded_regions else None
            if gr is not None:
                pts = gr.anchor_points if gr.anchor_points else (gr.anchor_point,)
                find_at_str = ", ".join(f"(({p[0]}, {p[1]}, {p[2]}),)" for p in pts)
            else:
                find_at_str = f"(({geometry.width / 2.0}, {geometry.height / 2.0}, {geometry.length / 2.0}),)"

            bolt_surf_name = f"{b_spec.name}_BoltSection"
            bolt_code = (
                f"a = mdb.models['{model_name}'].rootAssembly\n"
                f"f = a.instances['{inst_name}'].faces\n"
                f"cut_faces = f.findAt({find_at_str})\n"
                f"bolt_surf = a.Surface(side1Faces=cut_faces, name='{bolt_surf_name}')\n"
            )
            if b_spec.direction_vector:
                v = b_spec.direction_vector
                bolt_code += (
                    f"d_axis = a.DatumAxisByTwoPoints(point1=(0.0, 0.0, 0.0), point2=({v[0]}, {v[1]}, {v[2]}))\n"
                    f"axis_obj = a.datums[d_axis.id]\n"
                    f"mdb.models['{model_name}'].BoltLoad(name='{b_spec.name}', createStepName='{b_spec.preload_step}', "
                    f"region=bolt_surf, magnitude={b_spec.preload_magnitude}, datumAxis=axis_obj, boltMethod=APPLY_FORCE)\n"
                )
            else:
                bolt_code += (
                    f"mdb.models['{model_name}'].BoltLoad(name='{b_spec.name}', createStepName='{b_spec.preload_step}', "
                    f"region=bolt_surf, magnitude={b_spec.preload_magnitude}, boltMethod=APPLY_FORCE)\n"
                )
            actions.append(builders.python_action(model_name, bolt_code))
            actions.append(builders.bolt_load(
                model=model_name,
                name=b_spec.name,
                region_expression=f"mdb.models['{model_name}'].rootAssembly.surfaces['{bolt_surf_name}']",
                magnitude=b_spec.preload_magnitude,
                step=b_spec.preload_step,
                bolt_method="APPLY_FORCE",
                direction_vector=b_spec.direction_vector,
            ))

            if b_spec.service_step:
                fix_code = (
                    f"mdb.models['{model_name}'].loads['{b_spec.name}'].setValuesInStep("
                    f"stepName='{b_spec.service_step}', boltMethod=FIX_LENGTH)\n"
                )
                actions.append(builders.python_action(model_name, fix_code))
                actions.append(builders.bolt_load_set_values(
                    model=model_name,
                    name=b_spec.name,
                    step=b_spec.service_step,
                    bolt_method="FIX_LENGTH",
                ))

    # 11. Mesh Generation Actions
    actions.append(builders.seed_part(
        model=model_name,
        part=part_name,
        size=mesh.global_size,
        deviation_factor=mesh.deviation_factor,
    ))
    if mesh.element_type.startswith("C3D10") or mesh.element_type.startswith("C3D4"):
        mesh_elem_code = (
            f"p = mdb.models['{model_name}'].parts['{part_name}']\n"
            f"p.setMeshControls(regions=p.cells, elemShape=TET, technique=FREE)\n"
            f"elemType1 = mesh.ElemType(elemCode={mesh.element_type}, elemLibrary=STANDARD)\n"
            f"p.setElementType(regions=(p.cells,), elemTypes=(elemType1,))\n"
            f"p.generateMesh()\n"
        )
    else:
        mesh_elem_code = (
            f"p = mdb.models['{model_name}'].parts['{part_name}']\n"
            f"elemType1 = mesh.ElemType(elemCode={mesh.element_type}, elemLibrary=STANDARD)\n"
            f"p.setElementType(regions=(p.cells,), elemTypes=(elemType1,))\n"
            f"p.generateMesh()\n"
        )
    actions.append(builders.python_action(model_name, mesh_elem_code))

    # 12. Output Requests & Job Creation
    job_code = (
        f"mdb.Job(name='{job_name}', model='{model_name}', type=ANALYSIS, "
        f"description='Autonomous Agent Compiled Job', waitMinutes=0, waitHours=0)\n"
    )
    actions.append(builders.python_action(model_name, job_code))

    # Render entire action list to executable script
    script_lines = [
        "from abaqus import *",
        "from abaqusConstants import *",
        "import mesh",
        f"if '{model_name}' not in mdb.models:",
        f"    mdb.Model(name='{model_name}')",
        "",
    ]
    for act in actions:
        code_str = action_to_script(act)
        script_lines.append(f"# Action: {act.action_type}")
        script_lines.append(code_str)
        script_lines.append("")

    full_script = "\n".join(script_lines)

    intent_summary = {
        "model_name": model_name,
        "part_name": part_name,
        "job_name": job_name,
        "geometry": {
            "shape": geometry.shape,
            "dimensions": [geometry.length, geometry.width, geometry.height],
            "step_file_path": geometry.step_file_path,
        },
        "material": material.name,
        "actions_count": len(actions),
        "grounded_regions_count": len(grounded_regions) if grounded_regions else 0,
        "steps_count": len(defined_steps),
        "fields_count": len(fields) if fields else 0,
        "bolt_pretensions_count": len(bolt_pretensions) if bolt_pretensions else 0,
        "moments_count": len(moments) if moments else 0,
    }

    return CompiledAgentPlan(
        model_name=model_name,
        part_name=part_name,
        job_name=job_name,
        actions=tuple(actions),
        cae_script=full_script,
        intent_summary=intent_summary,
    )
