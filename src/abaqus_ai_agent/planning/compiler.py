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
from ..contracts.connector import (
    IntentConnectorSpec,
    ConnectorEndpointSpec,
    ConnectorOrientationSpec,
    ConnectorBehaviorSpec,
    CONNECTOR_TYPES_REQUIRING_ORIENTATION,
)
from ..contracts.fmbd import (
    IntentFMBDSpec,
    RigidBodySpec,
    FlexibleInterfaceSpec,
)
from ..contracts.intent import EngineeringIntent
from ..contracts.material import (
    MaterialDefinition,
    ElasticProperties,
    PlasticProperties,
    ThermalProperties,
)
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
    connectors: Optional[Sequence[IntentConnectorSpec]] = None,
    fmbd: Optional[IntentFMBDSpec] = None,
    submit_job: bool = False,
) -> CompiledAgentPlan:
    """Compile structured engineering intent into an ordered sequence of AbaqusActions."""
    actions: List[AbaqusAction] = []

    # 1. Geometry Construction (Native Python CAE Action)
    model_init = (
        f"if '{model_name}' not in mdb.models:\n"
        f"    mdb.Model(name='{model_name}')\n"
    )
    if geometry.shape == "plate_with_hole":
        p_width = geometry.width if geometry.width > 0 else 100.0
        p_height = geometry.height if geometry.height > 20.0 else (geometry.length if geometry.length > 20.0 else 100.0)
        p_depth = geometry.thickness if geometry.thickness is not None else 20.0
        p_radius = geometry.radius if geometry.radius is not None else 10.0
        geo_code = (
            model_init +
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
            model_init +
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
            model_init +
            f"s = mdb.models['{model_name}'].ConstrainedSketch(name='__profile__', sheetSize=200.0)\n"
            f"s.rectangle(point1=(0.0, 0.0), point2=({geometry.width}, {geometry.height}))\n"
            f"p = mdb.models['{model_name}'].Part(name='{part_name}', dimensionality=THREE_D, type=DEFORMABLE_BODY)\n"
            f"p.BaseSolidExtrude(sketch=s, depth={geometry.length})\n"
            f"del mdb.models['{model_name}'].sketches['__profile__']\n"
        )
    else:
        geo_code = (
            model_init +
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

    # 6d. Kinematic Connectors & Joints
    all_connectors = list(connectors or ())
    if fmbd and fmbd.connectors:
        for fc in fmbd.connectors:
            if fc not in all_connectors:
                all_connectors.append(fc)

    if all_connectors:
        for c_spec in all_connectors:
            p1_name = c_spec.endpoint_a.reference_point_name or c_spec.endpoint_a.semantic_region or f"{c_spec.name}_RP_A"
            p2_name = c_spec.endpoint_b.reference_point_name or c_spec.endpoint_b.semantic_region or f"{c_spec.name}_RP_B"

            if c_spec.endpoint_a.point_coords is not None:
                pt1 = c_spec.endpoint_a.point_coords
                actions.append(builders.reference_point(model=model_name, name=p1_name, coordinates=pt1))
            if c_spec.endpoint_b.point_coords is not None:
                pt2 = c_spec.endpoint_b.point_coords
                actions.append(builders.reference_point(model=model_name, name=p2_name, coordinates=pt2))

            orient_ref = None
            conn_init_lines = [f"a = mdb.models['{model_name}'].rootAssembly"]
            has_init_code = False

            if c_spec.orientation is not None:
                cs = c_spec.orientation
                csys_name = cs.name or f"Csys_{c_spec.name}"
                conn_init_lines.append(
                    f"d_csys_{c_spec.name} = a.DatumCsysByThreePoints(\n"
                    f"    name='{csys_name}',\n"
                    f"    coordSysType=CARTESIAN,\n"
                    f"    origin=({cs.origin[0]}, {cs.origin[1]}, {cs.origin[2]}),\n"
                    f"    point1=({cs.point1[0]}, {cs.point1[1]}, {cs.point1[2]}),\n"
                    f"    point2=({cs.point2[0]}, {cs.point2[1]}, {cs.point2[2]}),\n"
                    f")"
                )
                orient_ref = csys_name
                has_init_code = True

            if has_init_code:
                actions.append(builders.python_action(model_name, "\n".join(conn_init_lines) + "\n"))

            actions.append(builders.connector_section(
                model=model_name,
                name=c_spec.section_name,
                assembled_type=c_spec.connector_type,
            ))

            if c_spec.behavior is not None:
                bs = c_spec.behavior
                behavior_opts = []
                if bs.elasticity is not None:
                    el = bs.elasticity
                    comp_str = f"components={tuple(el.components)}" if len(el.components) > 1 else f"components=({el.components[0]},)"
                    stiff_str = f"table=(({', '.join(str(s) for s in el.stiffness)},),)"
                    behavior_opts.append(f"connectorBehavior.ConnectorElasticity({comp_str}, {stiff_str})")
                if bs.damping is not None:
                    damp = bs.damping
                    comp_str = f"components={tuple(damp.components)}" if len(damp.components) > 1 else f"components=({damp.components[0]},)"
                    damp_str = f"table=(({', '.join(str(d) for d in damp.damping_coefficient)},),)"
                    behavior_opts.append(f"connectorBehavior.ConnectorDamping({comp_str}, {damp_str})")
                if behavior_opts:
                    behav_code = (
                        f"import connectorBehavior\n"
                        f"mdb.models['{model_name}'].sections['{c_spec.section_name}'].setValues(\n"
                        f"    behaviorOptions=({', '.join(behavior_opts)},)\n"
                        f")\n"
                    )
                    actions.append(builders.python_action(model_name, behav_code))

            actions.append(builders.wire_connector(
                model=model_name,
                name=c_spec.name,
                section_name=c_spec.section_name,
                point1_name=p1_name,
                point2_name=p2_name,
                orientation=orient_ref,
                wire_feature_name=c_spec.wire_feature_name,
                wire_set_name=c_spec.wire_set_name,
            ))

    # 6e. Flexible Multibody Dynamics (FMBD) Rigid Bodies & Flexible Coupling Interfaces
    if fmbd:
        for rb in fmbd.rigid_bodies:
            if rb.point_coords is not None:
                actions.append(builders.reference_point(model=model_name, name=rb.ref_point_name, coordinates=rb.point_coords))
            actions.append(builders.rigid_body(
                model=model_name,
                name=rb.name,
                ref_point_expression=rb.ref_point_expression,
                body_expression=rb.body_region,
                tie_region=rb.tie_region,
                pin_region=rb.pin_region,
            ))

        for fi in fmbd.flexible_interfaces:
            cp_name = fi.effective_control_point
            if fi.effective_coords is not None:
                actions.append(builders.reference_point(model=model_name, name=cp_name, coordinates=fi.effective_coords))
            actions.append(builders.coupling_constraint(
                model=model_name,
                name=fi.name,
                control_point_name=cp_name,
                surface_expression=fi.effective_surface_region,
                coupling_type=fi.coupling_type,
                influence_radius=fi.influence_radius,
                u1=fi.u1, u2=fi.u2, u3=fi.u3,
                ur1=fi.ur1, ur2=fi.ur2, ur3=fi.ur3,
            ))

        if fmbd.gravity is not None:
            g_step = default_step_name
            actions.append(builders.gravity(
                model=model_name,
                name=f"Gravity_{fmbd.name}",
                comp1=fmbd.gravity[0],
                comp2=fmbd.gravity[1],
                comp3=fmbd.gravity[2],
                step=g_step,
            ))

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
                    f"region=region, {ld.direction.lower()}=cf_val)\n"
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
            f"import mesh\nfrom abaqusConstants import *\n"
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
                f"import mesh\nfrom abaqusConstants import *\n"
                f"p = mdb.models['{model_name}'].parts['{part_name}']\n"
                f"p.setMeshControls(regions=p.cells, elemShape=TET, technique=FREE)\n"
                f"elemType1 = mesh.ElemType(elemCode={mesh.element_type}, elemLibrary={mesh.element_library})\n"
                f"p.setElementType(regions=(p.cells,), elemTypes=(elemType1,))\n"
                f"p.generateMesh()\n"
            )
        else:
            mesh_elem_code = (
                f"import mesh\nfrom abaqusConstants import *\n"
                f"p = mdb.models['{model_name}'].parts['{part_name}']\n"
                f"elemType1 = mesh.ElemType(elemCode={mesh.element_type}, elemLibrary={mesh.element_library})\n"
                f"p.setElementType(regions=(p.cells,), elemTypes=(elemType1,))\n"
                f"p.generateMesh()\n"
            )
        actions.append(builders.python_action(model_name, mesh_elem_code))

    # 12. Output Requests & Job Creation
    if fatigue is not None:
        fatigue_out_req = (
            f"import step\n"
            f"for _for_name in list(mdb.models['{model_name}'].fieldOutputRequests.keys()):\n"
            f"    mdb.models['{model_name}'].fieldOutputRequests[_for_name].setValues(variables=('S', 'U', 'RF'))\n"
        )
        actions.append(builders.python_action(model_name, fatigue_out_req))

    if connectors or (fmbd and fmbd.connectors):
        conn_out_req = (
            f"import step\n"
            f"for _for_name in list(mdb.models['{model_name}'].fieldOutputRequests.keys()):\n"
            f"    mdb.models['{model_name}'].fieldOutputRequests[_for_name].setValues(variables=('CU', 'CTF', 'U', 'UR', 'RF', 'RM'))\n"
        )
        actions.append(builders.python_action(model_name, conn_out_req))

    if fmbd is not None:
        fmbd_field_out = (
            f"import step\n"
            f"for _for_name in list(mdb.models['{model_name}'].fieldOutputRequests.keys()):\n"
            f"    mdb.models['{model_name}'].fieldOutputRequests[_for_name].setValues(variables=('S', 'U', 'UR', 'V', 'VR', 'CU', 'CTF', 'RF', 'RM'))\n"
        )
        actions.append(builders.python_action(model_name, fmbd_field_out))
        fmbd_hist_out = (
            f"if 'H-Output-1' in mdb.models['{model_name}'].historyOutputRequests:\n"
            f"    mdb.models['{model_name}'].historyOutputRequests['H-Output-1'].setValues(variables=('ALLIE', 'ALLKE', 'ALLWK', 'ALLSE', 'ETOTAL'))\n"
        )
        actions.append(builders.python_action(model_name, fmbd_hist_out))

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
        "connectors_count": len(all_connectors) if all_connectors else 0,
        "fmbd_specs_count": (len(fmbd.rigid_bodies) + len(fmbd.flexible_interfaces)) if fmbd else 0,
        "fmbd": fmbd.to_dict() if fmbd else None,
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


def compile_engineering_intent(
    intent: EngineeringIntent,
    model_name: Optional[str] = None,
    part_name: Optional[str] = None,
    job_name: Optional[str] = None,
    geometry: Optional[IntentGeometrySpec] = None,
    material: Optional[MaterialDefinition] = None,
    mesh: Optional[IntentMeshSpec] = None,
    grounded_regions: Optional[Dict[str, GroundedRegion]] = None,
    submit_job: bool = False,
) -> CompiledAgentPlan:
    """Compile a high-level EngineeringIntent directly into a CompiledAgentPlan.

    Bridges declarative, multi-source EngineeringIntent models (from natural language,
    vision, or programmatic definitions) into canonical AbaqusActions, ensuring
    strict fail-closed validation for missing geometry, material, or boundary definitions.
    """
    if not isinstance(intent, EngineeringIntent):
        raise TypeError(f"Expected EngineeringIntent, got {type(intent).__name__}")

    # 1. Resolved Names
    safe_id = "".join(c if c.isalnum() or c == "_" else "_" for c in intent.id)
    eff_model = model_name or intent.metadata.get("model_name") or f"Model_{safe_id}"
    eff_part = part_name or intent.metadata.get("part_name") or "MainPart"
    eff_job = job_name or intent.metadata.get("job_name") or f"Job_{safe_id}"

    # 2. Geometry Resolution (Fail-closed on complete omission)
    eff_geom = geometry
    if eff_geom is None and "geometry" in intent.metadata:
        raw_geom = intent.metadata["geometry"]
        if isinstance(raw_geom, IntentGeometrySpec):
            eff_geom = raw_geom
        elif isinstance(raw_geom, dict):
            eff_geom = IntentGeometrySpec(**raw_geom)
    if eff_geom is None and "dimensions" in intent.metadata:
        dims = intent.metadata["dimensions"]
        if isinstance(dims, dict):
            eff_geom = IntentGeometrySpec(
                shape=dims.get("shape", "cantilever_box"),
                length=float(dims.get("length", 100.0)),
                width=float(dims.get("width", 10.0)),
                height=float(dims.get("height", 10.0)),
                radius=float(dims["radius"]) if "radius" in dims else None,
                thickness=float(dims["thickness"]) if "thickness" in dims else None,
                step_file_path=dims.get("step_file_path"),
            )
        elif isinstance(dims, (list, tuple)) and dims:
            vals = [float(d["value"]) if isinstance(d, dict) and "value" in d else float(d) for d in dims]
            l = vals[0] if len(vals) > 0 else 100.0
            w = vals[1] if len(vals) > 1 else 10.0
            h = vals[2] if len(vals) > 2 else 10.0
            eff_geom = IntentGeometrySpec(shape="cantilever_box", length=l, width=w, height=h)

    if eff_geom is None:
        raise ValueError(
            "Cannot compile engineering intent: missing geometry specification. "
            "Provide geometry via intent.metadata['geometry'] or explicit geometry parameter."
        )

    # 3. Material Resolution (Fail-closed on complete omission)
    eff_mat = material
    if eff_mat is None and intent.material is not None:
        if isinstance(intent.material, MaterialDefinition):
            eff_mat = intent.material
        elif isinstance(intent.material, dict):
            m = intent.material
            m_name = m.get("name", "DefaultMaterial")
            u_sys = m.get("unit_system") or intent.unit_system or "MM_N_MPA"
            youngs = m.get("elastic_modulus") or m.get("youngs_modulus") or m.get("E")
            nu = m.get("poisson_ratio") if m.get("poisson_ratio") is not None else (m.get("nu") if m.get("nu") is not None else 0.3)
            rho = m.get("density") or m.get("rho")
            yield_str = m.get("yield_stress") or m.get("yield_strength")

            elastic = None
            if youngs is not None:
                elastic = ElasticProperties(youngs_modulus=float(youngs), poisson_ratio=float(nu))
            plastic = None
            if yield_str is not None:
                plastic = PlasticProperties(yield_stress=float(yield_str))

            density_val = float(rho) if rho is not None else (7.85e-9 if "steel" in m_name.lower() or "q235" in m_name.lower() else (2.7e-9 if "al" in m_name.lower() else None))

            eff_mat = MaterialDefinition(
                name=m_name,
                unit_system=u_sys,
                elastic=elastic,
                density=density_val,
                plastic=plastic,
            )

    if eff_mat is None:
        raise ValueError(
            "Cannot compile engineering intent: missing material specification. "
            "Provide material via intent.material or explicit material parameter."
        )

    # 4. Step & Procedure Resolution
    eff_step = None
    eff_steps = intent.metadata.get("steps")
    eff_procedure = intent.metadata.get("procedure")

    if eff_procedure is None and eff_steps is None:
        raw_step = intent.metadata.get("step")
        if isinstance(raw_step, IntentStepSpec):
            eff_step = raw_step
        elif isinstance(raw_step, dict):
            eff_step = IntentStepSpec(**raw_step)
        else:
            analysis = str(intent.analysis_type or intent.kind or "linear_static").lower()
            if analysis in ("nonlinear_static", "plasticity"):
                eff_step = IntentStepSpec(name="Step-1", step_type="static_general", nlgeom=True)
            elif analysis in ("steady_thermal", "thermal", "heat_transfer"):
                eff_step = IntentStepSpec(name="Step-1", step_type="heat_transfer", nlgeom=False)
            elif analysis in ("modal_frequency", "frequency", "modal"):
                eff_step = IntentStepSpec(name="Step-1", step_type="frequency", nlgeom=False)
            elif analysis in ("transient_dynamic", "implicit_dynamic", "dynamic"):
                eff_step = IntentStepSpec(name="Step-1", step_type="implicit_dynamic", nlgeom=True)
            elif analysis in ("explicit_dynamic", "explicit"):
                eff_step = IntentStepSpec(name="Step-1", step_type="explicit_dynamic", nlgeom=True)
            else:
                eff_step = IntentStepSpec(name="Step-1", step_type="static_general", nlgeom=False)

    # 5. Boundary Conditions Mapping
    compiled_bcs: List[IntentBoundarySpec] = []
    for idx, bc in enumerate(intent.boundary_conditions):
        if isinstance(bc, IntentBoundarySpec):
            compiled_bcs.append(bc)
        elif isinstance(bc, dict):
            b_type = str(bc.get("type", "ENCASTRE")).upper()
            b_reg = str(bc.get("region", "RootFace"))
            b_name = str(bc.get("name") or f"BC_{idx+1}_{b_type}")
            b_vals = bc.get("values", {})
            b_step = bc.get("step", "Initial")
            b_plane = bc.get("plane")
            b_mods = bc.get("step_modifications")
            compiled_bcs.append(
                IntentBoundarySpec(
                    name=b_name,
                    bc_type=b_type,
                    region=b_reg,
                    values=b_vals,
                    step=b_step,
                    plane=b_plane,
                    step_modifications=b_mods,
                )
            )

    # 6. Loads Mapping
    compiled_loads: List[IntentLoadSpec] = []
    for idx, ld in enumerate(intent.loads):
        if isinstance(ld, IntentLoadSpec):
            compiled_loads.append(ld)
        elif isinstance(ld, dict):
            l_type = str(ld.get("type", "concentrated_force"))
            l_reg = str(ld.get("region", "TipFace"))
            mag = float(ld.get("magnitude", 0.0))
            raw_dir = str(ld.get("direction", "CF2")).upper()
            if raw_dir in ("-Y", "Y-", "-CF2"):
                dir_val = "CF2"
                if mag > 0:
                    mag = -mag
            elif raw_dir in ("+Y", "Y+", "CF2"):
                dir_val = "CF2"
            elif raw_dir in ("-X", "X-", "-CF1"):
                dir_val = "CF1"
                if mag > 0:
                    mag = -mag
            elif raw_dir in ("+X", "X+", "CF1"):
                dir_val = "CF1"
            elif raw_dir in ("-Z", "Z-", "-CF3"):
                dir_val = "CF3"
                if mag > 0:
                    mag = -mag
            elif raw_dir in ("+Z", "Z+", "CF3"):
                dir_val = "CF3"
            else:
                dir_val = raw_dir if raw_dir in ("CF1", "CF2", "CF3") else "CF2"

            l_name = str(ld.get("name") or f"Load_{idx+1}_{l_type}")
            l_step = ld.get("step")
            l_field = ld.get("field")
            l_dist = ld.get("distribution_type", "UNIFORM")
            l_axis = ld.get("axis")
            compiled_loads.append(
                IntentLoadSpec(
                    name=l_name,
                    load_type=l_type,
                    region=l_reg,
                    magnitude=mag,
                    direction=dir_val,
                    step=l_step,
                    field=l_field,
                    distribution_type=l_dist,
                    axis=l_axis,
                )
            )

    # 7. Mesh Mapping
    eff_mesh = mesh
    if eff_mesh is None and intent.mesh_requirements:
        if isinstance(intent.mesh_requirements, IntentMeshSpec):
            eff_mesh = intent.mesh_requirements
        elif isinstance(intent.mesh_requirements, dict):
            m_req = intent.mesh_requirements
            eff_mesh = IntentMeshSpec(
                element_type=m_req.get("element_type", "C3D8R"),
                global_size=float(m_req.get("global_size", 2.5)),
                deviation_factor=float(m_req.get("deviation_factor", 0.1)),
                element_library=m_req.get("element_library", "STANDARD"),
            )
    if eff_mesh is None:
        eff_mesh = IntentMeshSpec()

    # 8. Multi-domain special contracts
    eff_grounded = grounded_regions or intent.metadata.get("grounded_regions")
    eff_fields = intent.metadata.get("fields")
    eff_bolts = intent.metadata.get("bolt_pretensions")
    eff_moments = intent.metadata.get("moments")
    eff_interactions = intent.contacts or intent.metadata.get("interactions")
    eff_predefined = intent.metadata.get("predefined_fields")

    eff_fatigue = intent.fatigue
    eff_connectors = intent.connectors or None
    eff_fmbd = intent.fmbd

    return compile_intent_to_actions(
        model_name=eff_model,
        part_name=eff_part,
        job_name=eff_job,
        geometry=eff_geom,
        material=eff_mat,
        step=eff_step,
        bcs=compiled_bcs,
        loads=compiled_loads,
        mesh=eff_mesh,
        grounded_regions=eff_grounded,
        steps=eff_steps,
        procedure=eff_procedure,
        fields=eff_fields,
        bolt_pretensions=eff_bolts,
        moments=eff_moments,
        interactions=eff_interactions,
        predefined_fields=eff_predefined,
        fatigue=eff_fatigue,
        connectors=eff_connectors,
        fmbd=eff_fmbd,
        submit_job=submit_job,
    )
