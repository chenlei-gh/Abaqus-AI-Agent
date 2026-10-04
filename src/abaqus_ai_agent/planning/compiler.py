"""R1: Agent-Native Engineering Intent Compiler.

Compiles high-level EngineeringIntent specifications into an executable,
ordered sequence of AbaqusActions, and renders them into native Abaqus/CAE Python scripts.
Eliminates hardcoded CAE scripts in favor of dynamic intent compilation.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts.action import AbaqusAction
from ..contracts.fatigue import IntentFatigueSpec
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
    step_modifications: Optional[Dict[str, Dict[str, Any]]] = None


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
    element_library: str = "STANDARD"  # "STANDARD", "EXPLICIT"


@dataclass(frozen=True)
class IntentInteractionSpec:
    name: str
    interaction_type: str = "surface_to_surface_contact"
    master_region: str = ""
    slave_region: str = ""
    friction_coefficient: float = 0.0
    normal_behavior: str = "HARD"
    step: str = "Initial"


@dataclass(frozen=True)
class IntentPredefinedFieldSpec:
    name: str
    field_type: str = "temperature"
    region: str = "AllCells"
    distribution_type: str = "FROM_FILE"
    file_name: Optional[str] = None
    begin_step: int = 1
    interpolate: bool = True
    magnitudes: Optional[float] = None
    step: str = "Initial"


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
    interactions: Optional[Sequence[IntentInteractionSpec]] = None,
    predefined_fields: Optional[Sequence[IntentPredefinedFieldSpec]] = None,
    fatigue: Optional[IntentFatigueSpec] = None,
    submit_job: bool = False,
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
    elif geometry.shape == "two_blocks_contact":
        base_w = geometry.width if geometry.width > 0 else 100.0
        base_h = geometry.height if geometry.height > 0 else 20.0
        base_l = geometry.length if geometry.length > 0 else 10.0
        geo_code = (
            f"s1 = mdb.models['{model_name}'].ConstrainedSketch(name='__profile_base__', sheetSize=200.0)\n"
            f"s1.rectangle(point1=(0.0, 0.0), point2=({base_w}, {base_h}))\n"
            f"p_base = mdb.models['{model_name}'].Part(name='Base', dimensionality=THREE_D, type=DEFORMABLE_BODY)\n"
            f"p_base.BaseSolidExtrude(sketch=s1, depth={base_l})\n"
            f"del mdb.models['{model_name}'].sketches['__profile_base__']\n"
            f"s2 = mdb.models['{model_name}'].ConstrainedSketch(name='__profile_slider__', sheetSize=200.0)\n"
            f"s2.rectangle(point1=(30.0, 0.0), point2=(60.0, {base_h}))\n"
            f"p_slider = mdb.models['{model_name}'].Part(name='Slider', dimensionality=THREE_D, type=DEFORMABLE_BODY)\n"
            f"p_slider.BaseSolidExtrude(sketch=s2, depth={base_l})\n"
            f"del mdb.models['{model_name}'].sketches['__profile_slider__']\n"
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

    # 1b. Bolt Partition (if bolt_pretensions exist on primitive shapes)
    if bolt_pretensions and geometry.shape in ("cantilever_box", "cylinder", "plate"):
        part_partition_code = f"p = mdb.models['{model_name}'].parts['{part_name}']\n"
        for b_spec in bolt_pretensions:
            gr = grounded_regions.get(b_spec.region_expression) if grounded_regions else None
            cut_z = gr.anchor_point[2] if (gr and gr.anchor_point) else (geometry.length / 2.0)
            part_partition_code += (
                f"d_plane_{b_spec.name} = p.DatumPlaneByPrincipalPlane(principalPlane=XYPLANE, offset={cut_z})\n"
                f"p.PartitionCellByDatumPlane(datumPlane=p.datums[d_plane_{b_spec.name}.id], cells=p.cells)\n"
            )
        actions.append(builders.python_action(model_name, part_partition_code))

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
    if material.thermal is not None:
        if material.thermal.conductivity is not None:
            actions.append(builders.material_conductivity(
                model=model_name,
                name=material.name,
                table=((material.thermal.conductivity,),),
            ))
        if material.thermal.specific_heat is not None:
            actions.append(builders.material_specific_heat(
                model=model_name,
                name=material.name,
                table=((material.thermal.specific_heat,),),
            ))
        if material.thermal.expansion_coefficient is not None:
            actions.append(builders.material_expansion(
                model=model_name,
                name=material.name,
                table=((material.thermal.expansion_coefficient,),),
            ))

    # 3. Section and Assignment
    sec_name = f"{material.name}_Section"
    actions.append(builders.solid_section(model=model_name, name=sec_name, material=material.name))
    if geometry.shape != "two_blocks_contact":
        sec_assign_code = (
            f"p = mdb.models['{model_name}'].parts['{part_name}']\n"
            f"c = p.cells\n"
            f"region = p.Set(cells=c, name='AllCells')\n"
            f"p.SectionAssignment(region=region, sectionName='{sec_name}')\n"
        )
    else:
        sec_assign_code = (
            f"p_base = mdb.models['{model_name}'].parts['Base']\n"
            f"p_slider = mdb.models['{model_name}'].parts['Slider']\n"
            f"reg_b = p_base.Set(cells=p_base.cells, name='AllCells')\n"
            f"p_base.SectionAssignment(region=reg_b, sectionName='{sec_name}')\n"
            f"reg_s = p_slider.Set(cells=p_slider.cells, name='AllCells')\n"
            f"p_slider.SectionAssignment(region=reg_s, sectionName='{sec_name}')\n"
        )
    actions.append(builders.python_action(model_name, sec_assign_code))

    # 4. Assembly Instance
    if geometry.shape != "two_blocks_contact":
        inst_name = f"{part_name}-1"
        inst_code = (
            f"a = mdb.models['{model_name}'].rootAssembly\n"
            f"a.DatumCsysByDefault(CARTESIAN)\n"
            f"a.Instance(name='{inst_name}', part=p, dependent=ON)\n"
        )
    else:
        base_w = geometry.width if geometry.width > 0 else 100.0
        base_h = geometry.height if geometry.height > 0 else 20.0
        base_l = geometry.length if geometry.length > 0 else 10.0
        inst_name = "Base-1"
        inst_code = (
            f"a = mdb.models['{model_name}'].rootAssembly\n"
            f"a.DatumCsysByDefault(CARTESIAN)\n"
            f"a.Instance(name='Base-1', part=p_base, dependent=ON)\n"
            f"a.Instance(name='Slider-1', part=p_slider, dependent=ON)\n"
            f"a.translate(instanceList=('Slider-1',), vector=(0.0, 0.0, {base_l}))\n"
            f"f_base_top = a.instances['Base-1'].faces.findAt((({base_w/2.0}, {base_h/2.0}, {base_l}),))\n"
            f"a.Surface(side1Faces=f_base_top, name='BaseSurf')\n"
            f"f_slider_bot = a.instances['Slider-1'].faces.findAt(((45.0, {base_h/2.0}, {base_l}),))\n"
            f"a.Surface(side1Faces=f_slider_bot, name='SliderSurf')\n"
            f"f_base_bot = a.instances['Base-1'].faces.findAt((({base_w/2.0}, {base_h/2.0}, 0.0),))\n"
            f"a.Set(faces=f_base_bot, name='BaseFixed')\n"
            f"f_slider_top = a.instances['Slider-1'].faces.findAt(((45.0, {base_h/2.0}, {2.0 * base_l}),))\n"
            f"a.Set(faces=f_slider_top, name='SliderTop')\n"
            f"a.Surface(side1Faces=f_slider_top, name='SliderTop_Surf')\n"
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
                resp_val = s.metadata.get("response", "STEADY_STATE") if (hasattr(s, "metadata") and s.metadata) else "STEADY_STATE"
                actions.append(builders.heat_transfer_step(
                    model=model_name,
                    name=s.name,
                    previous=s.previous,
                    response=resp_val,
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

    # 6b. Contact Interactions
    if interactions:
        for inter in interactions:
            prop_name = f"{inter.name}_Prop"
            inter_code = f"mdb.models['{model_name}'].ContactProperty('{prop_name}')\n"
            if inter.friction_coefficient > 0.0:
                inter_code += (
                    f"mdb.models['{model_name}'].interactionProperties['{prop_name}'].TangentialBehavior("
                    f"formulation=PENALTY, directionality=ISOTROPIC, slipRateDependency=OFF, "
                    f"pressureDependency=OFF, temperatureDependency=OFF, dependencies=0, "
                    f"table=(({inter.friction_coefficient}, ),), shearStressLimit=None, maximumElasticSlip=FRACTION, "
                    f"fraction=0.005, elasticSlipStiffness=None)\n"
                )
            if inter.normal_behavior == "HARD":
                inter_code += (
                    f"mdb.models['{model_name}'].interactionProperties['{prop_name}'].NormalBehavior("
                    f"pressureOverclosure=HARD, allowSeparation=ON, constraintEnforcementMethod=DEFAULT)\n"
                )
            inter_code += (
                f"a = mdb.models['{model_name}'].rootAssembly\n"
                f"m_surf = a.surfaces['{inter.master_region}']\n"
                f"s_surf = a.surfaces['{inter.slave_region}']\n"
                f"try:\n"
                f"    mdb.models['{model_name}'].SurfaceToSurfaceContactStd(name='{inter.name}', "
                f"createStepName='{inter.step}', main=m_surf, secondary=s_surf, sliding=FINITE, "
                f"interactionProperty='{prop_name}')\n"
                f"except (TypeError, NameError):\n"
                f"    mdb.models['{model_name}'].SurfaceToSurfaceContactStd(name='{inter.name}', "
                f"createStepName='{inter.step}', master=m_surf, slave=s_surf, sliding=FINITE, "
                f"interactionProperty='{prop_name}')\n"
            )
            actions.append(builders.python_action(model_name, inter_code))

    # 6c. Predefined Fields (Initial Temperature, Imported Temperature Field)
    if predefined_fields:
        for pf in predefined_fields:
            if pf.field_type == "temperature":
                if pf.distribution_type == "FROM_FILE":
                    interp_str = "ON" if pf.interpolate else "OFF"
                    pf_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"c_all = a.instances['{inst_name}'].cells\n"
                        f"reg = a.Set(cells=c_all, name='{pf.region}')\n"
                        f"mdb.models['{model_name}'].Temperature(name='{pf.name}', createStepName='{pf.step}', "
                        f"region=reg, distributionType=FROM_FILE, fileName='{pf.file_name}', "
                        f"beginStep={pf.begin_step}, interpolate={interp_str})\n"
                    )
                else:
                    pf_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"c_all = a.instances['{inst_name}'].cells\n"
                        f"reg = a.Set(cells=c_all, name='{pf.region}')\n"
                        f"mdb.models['{model_name}'].Temperature(name='{pf.name}', createStepName='{pf.step}', "
                        f"region=reg, distributionType=UNIFORM, magnitudes=({pf.magnitudes},))\n"
                    )
                actions.append(builders.python_action(model_name, pf_code))

    # 7. Moment / Torque & Coupling Actions (defined before BCs so BCs can attach to RP if coupled)
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

    # 8. Boundary Conditions Actions
    for bc in bcs:
        bc_step = bc.step if bc.step else "Initial"
        gr = grounded_regions.get(bc.region) if grounded_regions else None
        plane = bc.plane or (gr.target_semantic.split("_")[-1] if gr and "SYMMETRY_PLANE" in gr.target_semantic else "X")

        if gr is not None:
            pts = gr.anchor_points if gr.anchor_points else (gr.anchor_point,)
            find_at_str = ", ".join(f"(({p[0]}, {p[1]}, {p[2]}),)" for p in pts)
            if bc.bc_type in ("SYMMETRY", "XSYMM", "YSYMM", "ZSYMM"):
                method_name = {"X": "XsymmBC", "Y": "YsymmBC", "Z": "ZsymmBC"}.get(plane, "XsymmBC")
                bc_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"f = a.instances['{inst_name}'].faces\n"
                    f"symm_faces = f.findAt({find_at_str})\n"
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
                    f"fixed_faces = f.findAt({find_at_str})\n"
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
            elif bc.bc_type == "TEMPERATURE":
                mag = bc.values.get("magnitude", bc.values.get("temp", 0.0))
                bc_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"f = a.instances['{inst_name}'].faces\n"
                    f"target_faces = f.findAt({find_at_str})\n"
                    f"region = a.Set(faces=target_faces, name='{bc.region}')\n"
                    f"mdb.models['{model_name}'].TemperatureBC(name='{bc.name}', createStepName='{bc_step}', "
                    f"region=region, distributionType=UNIFORM, magnitude={mag})\n"
                )
                actions.append(builders.python_action(model_name, bc_code))
            elif bc.bc_type == "DISPLACEMENT":
                # Check if region is an RP set or matches a moment RP coupling
                rp_coupled_moment = None
                if moments:
                    for m_spec in moments:
                        if m_spec.strategy == MomentTransferStrategy.RP_COUPLING and (m_spec.region_expression == bc.region or bc.region == f"{m_spec.name}_RP_Set"):
                            rp_coupled_moment = m_spec
                            break

                dof_args = []
                for dof in ("u1", "u2", "u3", "ur1", "ur2", "ur3"):
                    if dof in bc.values:
                        dof_args.append(f"{dof}={bc.values[dof]}")
                dof_str = ", ".join(dof_args) if dof_args else "u1=0.0, u2=0.0, u3=0.0"

                if rp_coupled_moment:
                    bc_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"region = a.sets['{rp_coupled_moment.name}_RP_Set']\n"
                        f"mdb.models['{model_name}'].DisplacementBC(name='{bc.name}', createStepName='{bc_step}', "
                        f"region=region, {dof_str})\n"
                    )
                    actions.append(builders.python_action(model_name, bc_code))
                    actions.append(builders.displacement_bc(
                        model=model_name,
                        name=bc.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{rp_coupled_moment.name}_RP_Set']",
                        step=bc_step,
                        u1=bc.values.get("u1", 0.0), u2=bc.values.get("u2", 0.0), u3=bc.values.get("u3", 0.0),
                    ))
                else:
                    bc_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"f = a.instances['{inst_name}'].faces\n"
                        f"disp_faces = f.findAt({find_at_str})\n"
                        f"region = a.Set(faces=disp_faces, name='{bc.region}')\n"
                        f"mdb.models['{model_name}'].DisplacementBC(name='{bc.name}', createStepName='{bc_step}', "
                        f"region=region, {dof_str})\n"
                    )
                    actions.append(builders.python_action(model_name, bc_code))
                    actions.append(builders.displacement_bc(
                        model=model_name,
                        name=bc.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{bc.region}']",
                        step=bc_step,
                        u1=bc.values.get("u1", 0.0), u2=bc.values.get("u2", 0.0), u3=bc.values.get("u3", 0.0),
                    ))
        elif geometry.shape == "two_blocks_contact" and bc.region in ("BaseFixed", "SliderTop"):
            dof_args = []
            for dof in ("u1", "u2", "u3", "ur1", "ur2", "ur3"):
                if dof in bc.values:
                    dof_args.append(f"{dof}={bc.values[dof]}")
            dof_str = ", ".join(dof_args) if dof_args else "u1=0.0, u2=0.0, u3=0.0"
            bc_code = (
                f"a = mdb.models['{model_name}'].rootAssembly\n"
                f"region = a.sets['{bc.region}']\n"
            )
            if bc.bc_type == "ENCASTRE":
                bc_code += f"mdb.models['{model_name}'].EncastreBC(name='{bc.name}', createStepName='{bc_step}', region=region)\n"
            elif bc.bc_type == "DISPLACEMENT":
                bc_code += f"mdb.models['{model_name}'].DisplacementBC(name='{bc.name}', createStepName='{bc_step}', region=region, {dof_str})\n"
            actions.append(builders.python_action(model_name, bc_code))
        else:
            # Fallback for primitive geometric models without explicit GroundedRegion mapping
            if bc.bc_type in ("SYMMETRY", "XSYMM", "YSYMM", "ZSYMM"):
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
            elif bc.bc_type == "TEMPERATURE":
                mag = bc.values.get("magnitude", bc.values.get("temp", 0.0))
                z_loc = geometry.length if "TOP" in bc.region.upper() else 0.0
                target_faces = f"(({geometry.width/2.0}, {geometry.height/2.0}, {z_loc}),)"
                bc_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"f = a.instances['{inst_name}'].faces\n"
                    f"disp_faces = f.findAt({target_faces})\n"
                    f"region = a.Set(faces=disp_faces, name='{bc.region}')\n"
                    f"mdb.models['{model_name}'].TemperatureBC(name='{bc.name}', createStepName='{bc_step}', "
                    f"region=region, distributionType=UNIFORM, magnitude={mag})\n"
                )
                actions.append(builders.python_action(model_name, bc_code))
            elif bc.bc_type == "DISPLACEMENT":
                # Check if region is an RP set or matches a moment RP coupling
                rp_coupled_moment = None
                if moments:
                    for m_spec in moments:
                        if m_spec.strategy == MomentTransferStrategy.RP_COUPLING and (m_spec.region_expression == bc.region or bc.region == f"{m_spec.name}_RP_Set"):
                            rp_coupled_moment = m_spec
                            break

                dof_args = []
                for dof in ("u1", "u2", "u3", "ur1", "ur2", "ur3"):
                    if dof in bc.values:
                        dof_args.append(f"{dof}={bc.values[dof]}")
                dof_str = ", ".join(dof_args) if dof_args else "u1=0.0, u2=0.0, u3=0.0"

                if rp_coupled_moment:
                    bc_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"region = a.sets['{rp_coupled_moment.name}_RP_Set']\n"
                        f"mdb.models['{model_name}'].DisplacementBC(name='{bc.name}', createStepName='{bc_step}', "
                        f"region=region, {dof_str})\n"
                    )
                    actions.append(builders.python_action(model_name, bc_code))
                    actions.append(builders.displacement_bc(
                        model=model_name,
                        name=bc.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{rp_coupled_moment.name}_RP_Set']",
                        step=bc_step,
                        u1=bc.values.get("u1", 0.0), u2=bc.values.get("u2", 0.0), u3=bc.values.get("u3", 0.0),
                    ))
                else:
                    z_loc = geometry.length if "TOP" in bc.region.upper() else 0.0
                    target_faces = f"(({geometry.width/2.0}, {geometry.height/2.0}, {z_loc}),)"
                    bc_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"f = a.instances['{inst_name}'].faces\n"
                        f"disp_faces = f.findAt({target_faces})\n"
                        f"region = a.Set(faces=disp_faces, name='{bc.region}')\n"
                        f"mdb.models['{model_name}'].DisplacementBC(name='{bc.name}', createStepName='{bc_step}', "
                        f"region=region, {dof_str})\n"
                    )
                    actions.append(builders.python_action(model_name, bc_code))
                    actions.append(builders.displacement_bc(
                        model=model_name,
                        name=bc.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{bc.region}']",
                        step=bc_step,
                        u1=bc.values.get("u1", 0.0), u2=bc.values.get("u2", 0.0), u3=bc.values.get("u3", 0.0),
                    ))

        # Multi-Step BC Modifications (e.g. freeing DOF in subsequent service steps)
        if bc.step_modifications:
            mod_code = ""
            for mod_step, mod_vals in bc.step_modifications.items():
                mod_args = []
                for k, v in mod_vals.items():
                    if str(v).upper() == "FREED":
                        mod_args.append(f"{k}=FREED")
                    else:
                        mod_args.append(f"{k}={v}")
                mod_args_str = ", ".join(mod_args)
                mod_code += f"mdb.models['{model_name}'].boundaryConditions['{bc.name}'].setValuesInStep(stepName='{mod_step}', {mod_args_str})\n"
            actions.append(builders.python_action(model_name, mod_code))

    # 9. Standard Loads Actions
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
                        f"region=region, cf3={ld.magnitude}{field_arg})\n"
                    )
                    actions.append(builders.python_action(model_name, load_code))
                    actions.append(builders.concentrated_force(
                        model=model_name,
                        name=ld.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{ld.region}']",
                        cf3=ld.magnitude,
                        step=target_step,
                    ))
        elif geometry.shape == "two_blocks_contact" and ld.region in ("SliderTop_Surf", "BaseSurf", "SliderSurf"):
            load_code = (
                f"a = mdb.models['{model_name}'].rootAssembly\n"
                f"surf = a.surfaces['{ld.region}']\n"
                f"mdb.models['{model_name}'].Pressure(name='{ld.name}', createStepName='{target_step}', "
                f"region=surf, magnitude={ld.magnitude}{field_arg})\n"
            )
            actions.append(builders.python_action(model_name, load_code))
        else:
            if ld.load_type == "pressure":
                z_loc = geometry.length if "TOP" in ld.region.upper() else 0.0
                target_faces = f"(({geometry.width/2.0}, {geometry.height/2.0}, {z_loc}),)"
                load_code = (
                    f"a = mdb.models['{model_name}'].rootAssembly\n"
                    f"f = a.instances['{inst_name}'].faces\n"
                    f"target_faces = f.findAt({target_faces})\n"
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
                    f"d_axis = a.DatumAxisByTwoPoint(point1=(0.0, 0.0, 0.0), point2=({v[0]}, {v[1]}, {v[2]}))\n"
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
                datum_axis="axis_obj" if b_spec.direction_vector else None,
            ))

            if b_spec.service_step:
                actions.append(builders.bolt_load_set_values(
                    model=model_name,
                    name=b_spec.name,
                    step=b_spec.service_step,
                    bolt_method="FIX_LENGTH",
                ))

    # 11. Mesh Generation Actions
    if geometry.shape == "two_blocks_contact":
        mesh_elem_code = (
            f"p_base = mdb.models['{model_name}'].parts['Base']\n"
            f"p_slider = mdb.models['{model_name}'].parts['Slider']\n"
            f"p_base.seedPart(size={mesh.global_size}, deviationFactor={mesh.deviation_factor})\n"
            f"elemType1 = mesh.ElemType(elemCode={mesh.element_type}, elemLibrary={mesh.element_library})\n"
            f"p_base.setElementType(regions=(p_base.cells,), elemTypes=(elemType1,))\n"
            f"p_base.generateMesh()\n"
            f"p_slider.seedPart(size={mesh.global_size}, deviationFactor={mesh.deviation_factor})\n"
            f"p_slider.setElementType(regions=(p_slider.cells,), elemTypes=(elemType1,))\n"
            f"p_slider.generateMesh()\n"
        )
        actions.append(builders.python_action(model_name, mesh_elem_code))
    else:
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
                f"elemType1 = mesh.ElemType(elemCode={mesh.element_type}, elemLibrary={mesh.element_library})\n"
                f"p.setElementType(regions=(p.cells,), elemTypes=(elemType1,))\n"
                f"p.generateMesh()\n"
            )
        else:
            mesh_elem_code = (
                f"p = mdb.models['{model_name}'].parts['{part_name}']\n"
                f"elemType1 = mesh.ElemType(elemCode={mesh.element_type}, elemLibrary={mesh.element_library})\n"
                f"p.setElementType(regions=(p.cells,), elemTypes=(elemType1,))\n"
                f"p.generateMesh()\n"
            )
        actions.append(builders.python_action(model_name, mesh_elem_code))

    # 12. Output Requests & Job Creation
    if fatigue is not None:
        fatigue_out_req = (
            f"for _for_name in list(mdb.models['{model_name}'].fieldOutputRequests.keys()):\n"
            f"    _cur_vars = list(mdb.models['{model_name}'].fieldOutputRequests[_for_name].variables)\n"
            f"    if 'S' not in _cur_vars:\n"
            f"        _cur_vars.append('S')\n"
            f"    mdb.models['{model_name}'].fieldOutputRequests[_for_name].setValues(variables=tuple(_cur_vars))\n"
        )
        actions.append(builders.python_action(model_name, fatigue_out_req))

    if any("explicit" in s.lower() for s in defined_steps):
        out_req_code = (
            f"if 'F-Output-1' in mdb.models['{model_name}'].fieldOutputRequests:\n"
            f"    mdb.models['{model_name}'].fieldOutputRequests['F-Output-1'].setValues(variables=('S', 'U', 'V', 'A'), numIntervals=10)\n"
            f"if 'H-Output-1' in mdb.models['{model_name}'].historyOutputRequests:\n"
            f"    mdb.models['{model_name}'].historyOutputRequests['H-Output-1'].setValues(variables=('ALLKE', 'ALLIE', 'ALLVD', 'ALLAE', 'ALLWK', 'ETOTAL'))\n"
        )
        actions.append(builders.python_action(model_name, out_req_code))

    job_code = (
        f"mdb.Job(name='{job_name}', model='{model_name}', type=ANALYSIS, "
        f"description='Autonomous Agent Compiled Job', waitMinutes=0, waitHours=0)\n"
        f"mdb.jobs['{job_name}'].writeInput()\n"
    )
    if submit_job:
        job_code += f"mdb.jobs['{job_name}'].submit(consistencyChecking=OFF)\nmdb.jobs['{job_name}'].waitForCompletion()\n"
    actions.append(builders.python_action(model_name, job_code))

    # Render entire action list to executable script
    script_lines = [
        "from abaqus import *",
        "from abaqusConstants import *",
        "import part, material, section, assembly, step, interaction, load, mesh, job, regionToolset",
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
        "interactions_count": len(interactions) if interactions else 0,
        "predefined_fields_count": len(predefined_fields) if predefined_fields else 0,
        "fatigue": fatigue.to_dict() if fatigue else None,
    }

    return CompiledAgentPlan(
        model_name=model_name,
        part_name=part_name,
        job_name=job_name,
        actions=tuple(actions),
        cae_script=full_script,
        intent_summary=intent_summary,
    )
