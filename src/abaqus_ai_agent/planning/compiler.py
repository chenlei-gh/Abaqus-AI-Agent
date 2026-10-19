"""R1: Agent-Native Engineering Intent Compiler.

Compiles high-level EngineeringIntent specifications into an executable,
ordered sequence of AbaqusActions, and renders them into native Abaqus/CAE Python scripts.
Eliminates hardcoded CAE scripts in favor of dynamic intent compilation.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..contracts.mesh import LocalSeed, MeshSpecification
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
    assembly_scope: Optional[Any] = None


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
    stabilization_method: Optional[str] = None
    stabilization_magnitude: Optional[float] = None
    max_num_inc: Optional[int] = None
    initial_inc: Optional[float] = None
    min_inc: Optional[float] = None
    max_inc: Optional[float] = None


@dataclass(frozen=True)
class IntentMeshSpec:
    element_type: str = "C3D8R"
    global_size: float = 2.5
    deviation_factor: float = 0.1
    element_library: str = "STANDARD"  # "STANDARD", "EXPLICIT"
    local_seeds: Tuple[LocalSeed, ...] = ()

    def __post_init__(self):
        if self.global_size is None or float(self.global_size) <= 0:
            raise ValueError(f"global_size must be positive, got {self.global_size!r}")
        if self.deviation_factor is None or not (0.0 <= float(self.deviation_factor) <= 1.0):
            raise ValueError(f"deviation_factor must be in [0, 1], got {self.deviation_factor!r}")
        lib_str = str(self.element_library).upper()
        if lib_str not in ("STANDARD", "EXPLICIT"):
            raise ValueError(f"element_library must be STANDARD or EXPLICIT, got {self.element_library!r}")
        if self.element_library != lib_str:
            object.__setattr__(self, "element_library", lib_str)
        if not isinstance(self.local_seeds, tuple):
            norm_seeds = []
            for s in self.local_seeds:
                if isinstance(s, LocalSeed):
                    norm_seeds.append(s)
                elif isinstance(s, dict):
                    norm_seeds.append(LocalSeed(
                        region_expression=s["region_expression"],
                        size=s.get("size"),
                        number=s.get("number"),
                        constraint=s.get("constraint"),
                    ))
                else:
                    raise TypeError(f"Invalid local seed item: {s!r}")
            object.__setattr__(self, "local_seeds", tuple(norm_seeds))


@dataclass(frozen=True)
class IntentInteractionSpec:
    name: str
    interaction_type: str = "surface_to_surface_contact"
    master_region: str = ""
    slave_region: str = ""
    friction_coefficient: float = 0.0
    normal_behavior: str = "HARD"
    step: str = "Initial"
    stabilization: Optional[Dict[str, Any]] = None


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
    material: Optional[MaterialDefinition] = None


def compile_intent_to_actions(
    model_name: str,
    part_name: str,
    job_name: str,
    geometry: IntentGeometrySpec,
    material: Union[MaterialDefinition, Dict[str, Any], str],
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
    assembly_scope: Optional[Any] = None,
    predefined_fields: Optional[Sequence[IntentPredefinedFieldSpec]] = None,
    connectors: Optional[Sequence[IntentConnectorSpec]] = None,
    fmbd: Optional[IntentFMBDSpec] = None,
    fatigue: Optional[IntentFatigueSpec] = None,
    contact_stabilization: Optional[Any] = None,
    submit_job: bool = False,
) -> CompiledAgentPlan:
    """Compile declarative engineering specifications into canonical AbaqusActions and CAE script."""
    from ..reasoning.material_catalog import resolve_material_to_definition
    eff_material = resolve_material_to_definition(material, fail_closed=True)
    material = eff_material

    actions: List[AbaqusAction] = []
    active_scope = assembly_scope if assembly_scope is not None else getattr(geometry, "assembly_scope", None)
    if active_scope is not None and geometry.shape != "step_assembly":
        raise ValueError(
            "assembly_scope is only valid for shape='step_assembly'; refusing to attach "
            "multi-part contact and fixture data to a single-part template"
        )

    # 1. Geometry Construction (Native Python CAE Action)
    model_init = (
        f"if '{model_name}' not in mdb.models:\n"
        f"    mdb.Model(name='{model_name}')\n"
    )
    if geometry.shape == "l_bracket":
        l_len = geometry.length if geometry.length > 0 else 100.0
        l_h = geometry.height if geometry.height > 0 else 100.0
        l_t = geometry.thickness if (geometry.thickness is not None and geometry.thickness > 0) else 10.0
        l_w = geometry.width if geometry.width > 0 else 20.0
        geo_code = (
            model_init +
            f"s = mdb.models['{model_name}'].ConstrainedSketch(name='__profile__', sheetSize=300.0)\n"
            f"s.Line(point1=(0.0, 0.0), point2=({l_len}, 0.0))\n"
            f"s.Line(point1=({l_len}, 0.0), point2=({l_len}, {l_t}))\n"
            f"s.Line(point1=({l_len}, {l_t}), point2=({l_t}, {l_t}))\n"
            f"s.Line(point1=({l_t}, {l_t}), point2=({l_t}, {l_h}))\n"
            f"s.Line(point1=({l_t}, {l_h}), point2=(0.0, {l_h}))\n"
            f"s.Line(point1=(0.0, {l_h}), point2=(0.0, 0.0))\n"
            f"p = mdb.models['{model_name}'].Part(name='{part_name}', dimensionality=THREE_D, type=DEFORMABLE_BODY)\n"
            f"p.BaseSolidExtrude(sketch=s, depth={l_w})\n"
            f"del mdb.models['{model_name}'].sketches['__profile__']\n"
        )
    elif geometry.shape == "plate_with_hole":
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
    elif geometry.shape == "step_assembly":
        scope = active_scope
        if scope is None or not getattr(scope, "is_complete", False):
            raise ValueError(
                "step_assembly requires a complete assembly scope covering every solid, "
                "at least one mating contact, and one installation fixture"
            )
        step_path = (geometry.step_file_path or "").replace("\\", "/")
        if not step_path:
            raise ValueError("step_assembly requires a non-empty step_file_path")
        # Abaqus 2025 noGUI does not bind mdb.openStep until auxImportGeom is
        # imported. Open once and reuse the returned ACIS object: each
        # importGeomFromStep call reconverts the whole file.
        # Non-ASCII paths make the converter report a valid file as corrupt.
        part_blocks = [
            "import os\n"
            "import shutil\n"
            "import tempfile\n"
            "import auxImportGeom\n"
            f"_step_source = r'{step_path}'\n"
            "_step_open_path = _step_source\n"
            "_step_staged = None\n"
            "if not _step_source.isascii():\n"
            "    _step_staged = os.path.join(tempfile.gettempdir(), 'abaqus_step_' + format(abs(hash(_step_source)), 'x') + '.stp')\n"
            "    shutil.copy2(_step_source, _step_staged)\n"
            "    _step_open_path = _step_staged\n"
            "_step_file = mdb.openStep(_step_open_path, scaleFromFile=OFF)\n"
            "if _step_staged and os.path.exists(_step_staged):\n"
            "    os.remove(_step_staged)\n"
            "if int(getattr(_step_file, 'numberOfParts', 0) or 0) < 1:\n"
            "    raise RuntimeError('STEP conversion produced no ACIS bodies')\n"
        ]
        for index, part in enumerate(scope.parts):
            body_num = getattr(part, "step_body_index", None)
            if not isinstance(body_num, int) or body_num < 1:
                raise ValueError(
                    f"step_assembly part {getattr(part, 'solid_id', part)} has no STEP body index; "
                    "refusing to guess bodyNum from part name or list position"
                )
            part_blocks.append(
                f"p_{index} = mdb.models['{model_name}'].PartFromGeometryFile(\n"
                f"    name='{part.name}', geometryFile=_step_file, bodyNum={body_num},\n"
                f"    combine=False, dimensionality=THREE_D, type=DEFORMABLE_BODY)\n"
            )
        geo_code = model_init + "".join(part_blocks)
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
            b_name = getattr(b_spec, "name", None) or (b_spec.get("name") if isinstance(b_spec, dict) else None) or (b_spec.get("bolt_name") if isinstance(b_spec, dict) else "B1")
            reg_expr = getattr(b_spec, "region_expression", None) or (b_spec.get("region_expression") if isinstance(b_spec, dict) else None)
            gr = grounded_regions.get(reg_expr) if (grounded_regions and reg_expr) else None
            cut_z = (
                _extract_gr_pts_and_anchor(gr)[1][2]
                if (gr and _extract_gr_pts_and_anchor(gr)[1])
                else (geometry.length / 2.0)
            )
            part_partition_code += (
                f"d_plane_{b_name} = p.DatumPlaneByPrincipalPlane(principalPlane=XYPLANE, offset={cut_z})\n"
                f"p.PartitionCellByDatumPlane(datumPlane=p.datums[d_plane_{b_name}.id], cells=p.cells)\n"
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
    if material.plastic:
        plastic_table: Tuple[Tuple[float, float], ...] = ()
        if material.plastic.hardening_table:
            raw_table = tuple(tuple(float(x) for x in pt) for pt in material.plastic.hardening_table)
            if raw_table and raw_table[0][1] != 0.0 and material.plastic.yield_stress is not None:
                plastic_table = ((float(material.plastic.yield_stress), 0.0),) + raw_table
            else:
                plastic_table = raw_table
        elif material.plastic.yield_stress is not None and material.plastic.yield_stress > 0:
            plastic_table = ((float(material.plastic.yield_stress), 0.0),)

        if plastic_table:
            actions.append(builders.material_plastic(
                model=model_name,
                name=material.name,
                table=plastic_table,
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
    if geometry.shape == "step_assembly":
        assign_lines = []
        for index, part in enumerate(active_scope.parts):
            assign_lines.append(
                f"p_{index} = mdb.models['{model_name}'].parts['{part.name}']\n"
                f"reg_{index} = p_{index}.Set(cells=p_{index}.cells, name='AllCells')\n"
                f"p_{index}.SectionAssignment(region=reg_{index}, sectionName='{sec_name}')\n"
            )
        sec_assign_code = "".join(assign_lines)
    elif geometry.shape != "two_blocks_contact":
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
    if geometry.shape == "step_assembly":
        inst_lines = [
            f"a = mdb.models['{model_name}'].rootAssembly\n",
            "a.DatumCsysByDefault(CARTESIAN)\n",
        ]
        for index, part in enumerate(active_scope.parts):
            inst_lines.append(
                f"p_{index} = mdb.models['{model_name}'].parts['{part.name}']\n"
                f"a.Instance(name='{part.instance_name}', part=p_{index}, dependent=ON)\n"
            )
        for contact in active_scope.contacts:
            mx, my, mz = contact.master_point
            sx, sy, sz = contact.slave_point
            inst_lines.append(
                f"main_faces = a.instances['{contact.master_instance}'].faces.findAt((({mx}, {my}, {mz}),))\n"
                f"a.Surface(side1Faces=main_faces, name='{contact.master_surface}')\n"
                f"secondary_faces = a.instances['{contact.slave_instance}'].faces.findAt((({sx}, {sy}, {sz}),))\n"
                f"a.Surface(side1Faces=secondary_faces, name='{contact.slave_surface}')\n"
            )
        fixture = active_scope.fixture
        fx, fy, fz = fixture.point
        inst_lines.append(
            f"fixed_faces = a.instances['{fixture.instance_name}'].faces.findAt((({fx}, {fy}, {fz}),))\n"
            f"a.Set(faces=fixed_faces, name='{fixture.set_name}')\n"
            f"mdb.models['{model_name}'].EncastreBC(name='{fixture.name}', createStepName='Initial', "
            f"region=a.sets['{fixture.set_name}'])\n"
        )
        inst_name = active_scope.parts[0].instance_name
        inst_code = "".join(inst_lines)
    elif geometry.shape != "two_blocks_contact":
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
            proc_controls = dict(getattr(s, "metadata", {}) or {}).get("step_controls") or {}
            if proc_type in ("static", "static_general"):
                actions.append(builders.static_step(
                    model=model_name,
                    name=s.name,
                    previous=s.previous,
                    nlgeom=nlgeom_val,
                    time_period=s.time_period,
                    stabilization_method=proc_controls.get("stabilization_method", "NONE"),
                    stabilization_magnitude=proc_controls.get("stabilization_magnitude"),
                    initial_inc=proc_controls.get("initial_inc", s.initial_inc),
                    min_inc=proc_controls.get("min_inc", s.min_inc),
                    max_inc=proc_controls.get("max_inc", s.max_inc),
                    max_num_inc=proc_controls.get("max_num_inc", s.max_num_inc),
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
                    stabilization_method=s.stabilization_method or "NONE",
                    stabilization_magnitude=s.stabilization_magnitude,
                    max_num_inc=s.max_num_inc or 100,
                    initial_inc=s.initial_inc,
                    min_inc=s.min_inc,
                    max_inc=s.max_inc,
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
                stabilization_method=active_step.stabilization_method or "NONE",
                stabilization_magnitude=active_step.stabilization_magnitude,
                max_num_inc=active_step.max_num_inc or 100,
                initial_inc=active_step.initial_inc,
                min_inc=active_step.min_inc,
                max_inc=active_step.max_inc,
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
    stabilized_target_steps: List[str] = []
    if geometry.shape == "step_assembly" and active_scope is not None:
        derived = [
            IntentInteractionSpec(
                name=contact.name,
                master_region=contact.master_surface,
                slave_region=contact.slave_surface,
                friction_coefficient=contact.friction_coefficient,
            )
            for contact in active_scope.contacts
        ]
        interactions = tuple(derived) + tuple(interactions or ())

    if contact_stabilization is not None:
        from ..contracts.contact_stabilization import (
            ContactStabilizationError,
            SUPPORTED_TARGET_PROCEDURES,
            coerce_contact_stabilization,
            resolve_contact_stabilization,
        )

        _spec = coerce_contact_stabilization(contact_stabilization)
        if _spec is not None:
            _step_order: List[str] = []
            _supported: List[str] = []
            if procedure is not None:
                for s in procedure.steps:
                    _step_order.append(s.name)
                    if (s.procedure or "static").lower() in SUPPORTED_TARGET_PROCEDURES:
                        _supported.append(s.name)
            elif steps:
                for s in steps:
                    _step_order.append(s.name)
                    if s.step_type in SUPPORTED_TARGET_PROCEDURES:
                        _supported.append(s.name)
            elif step is not None and step.name in defined_steps:
                _step_order.append(step.name)
                if step.step_type in SUPPORTED_TARGET_PROCEDURES:
                    _supported.append(step.name)
            _spec, _bindings = resolve_contact_stabilization(
                interactions or (),
                _spec,
                step_order=tuple(_step_order),
                enablement_steps=tuple(_supported),
            )
            _binding = _bindings[0] if _bindings else None
            if _binding is None:
                raise ContactStabilizationError(
                    "contact stabilization was requested but no binding target was resolved"
                )
            for inter in interactions or ():
                if inter.name != _binding.interaction_name:
                    continue
                interactions = tuple(
                    replace(b, stabilization=_spec.to_dict()) if b.name == _binding.interaction_name else b
                    for b in interactions
                )

    if interactions:
        from ..contracts.contact_stabilization import (
            ContactStabilizationBinding,
            coerce_contact_stabilization,
            contact_control_script,
        )
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
            binding = None
            spec = coerce_contact_stabilization(inter.stabilization)
            if spec is not None:
                target = spec.target_step or (inter.step if inter.step != "Initial" else None)
                if target is None:
                    raise ValueError(
                        f"Contact '{inter.name}' is created in the Initial step, so contact "
                        "stabilization needs an explicit target_step"
                    )
                binding = ContactStabilizationBinding(
                    interaction_name=inter.name,
                    interaction_step=inter.step,
                    target_step=target,
                    control_name=spec.control_name,
                    spec=spec,
                    requires_step_override=(inter.step != target),
                )
            if binding is not None and binding.target_step not in stabilized_target_steps:
                stabilized_target_steps.append(binding.target_step)
            extra = ""
            if binding is not None and not binding.requires_step_override:
                extra = f", contactControls='{binding.control_name}'"
            inter_code += (
                f"a = mdb.models['{model_name}'].rootAssembly\n"
                f"m_surf = a.surfaces['{inter.master_region}']\n"
                f"s_surf = a.surfaces['{inter.slave_region}']\n"
                f"try:\n"
                f"    mdb.models['{model_name}'].SurfaceToSurfaceContactStd(name='{inter.name}', "
                f"createStepName='{inter.step}', main=m_surf, secondary=s_surf, sliding=FINITE, "
                f"interactionProperty='{prop_name}'{extra})\n"
                f"except (TypeError, NameError):\n"
                f"    mdb.models['{model_name}'].SurfaceToSurfaceContactStd(name='{inter.name}', "
                f"createStepName='{inter.step}', master=m_surf, slave=s_surf, sliding=FINITE, "
                f"interactionProperty='{prop_name}'{extra})\n"
            )
            if binding is not None:
                from ..contracts.contact_stabilization import (
                    contact_control_binding_script,
                    contact_control_creation_script,
                )
                # The control object must exist before the interaction uses it.
                inter_code = (
                    contact_control_creation_script(binding, model_name) + "\n" + inter_code
                )
                inter_code += contact_control_binding_script(binding, model_name)
                if inter_code and not inter_code.endswith("\n"):
                    inter_code += "\n"
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
                    pts, anch = _extract_gr_pts_and_anchor(gr)
                    find_at_str = ", ".join(f"(({p[0]}, {p[1]}, {p[2]}),)" for p in pts) if pts else ""
                    rp_pt = m_spec.rp_coordinates if m_spec.rp_coordinates else (anch if anch else (geometry.width / 2.0, geometry.height / 2.0, geometry.length))
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
        target_semantic = _extract_gr_target_semantic(gr)
        plane = bc.plane or (target_semantic.split("_")[-1] if "SYMMETRY_PLANE" in target_semantic else "X")

        if gr is not None:
            named_set, named_surf = _extract_gr_named_selector(gr)
            pts, _ = _extract_gr_pts_and_anchor(gr)
            find_at_str = ", ".join(f"(({p[0]}, {p[1]}, {p[2]}),)" for p in pts) if pts else ""
            if bc.bc_type in ("SYMMETRY", "XSYMM", "YSYMM", "ZSYMM"):
                method_name = {"X": "XsymmBC", "Y": "YsymmBC", "Z": "ZsymmBC"}.get(plane, "XsymmBC")
                if named_set:
                    bc_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"region = a.sets['{named_set}']\n"
                        f"mdb.models['{model_name}'].{method_name}(name='{bc.name}', createStepName='{bc_step}', region=region)\n"
                    )
                    actions.append(builders.python_action(model_name, bc_code))
                    actions.append(builders.symmetry_bc(
                        model=model_name,
                        name=bc.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{named_set}']",
                        step=bc_step,
                        plane=plane,
                    ))
                else:
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
                if named_set:
                    bc_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"region = a.sets['{named_set}']\n"
                        f"mdb.models['{model_name}'].EncastreBC(name='{bc.name}', createStepName='{bc_step}', region=region)\n"
                    )
                    actions.append(builders.python_action(model_name, bc_code))
                    actions.append(builders.fixed_bc(
                        model=model_name,
                        name=bc.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{named_set}']",
                        step=bc_step,
                    ))
                elif named_surf:
                    bc_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"region = a.surfaces['{named_surf}']\n"
                        f"mdb.models['{model_name}'].EncastreBC(name='{bc.name}', createStepName='{bc_step}', region=region)\n"
                    )
                    actions.append(builders.python_action(model_name, bc_code))
                    actions.append(builders.fixed_bc(
                        model=model_name,
                        name=bc.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.surfaces['{named_surf}']",
                        step=bc_step,
                    ))
                else:
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
                if named_set:
                    bc_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"region = a.sets['{named_set}']\n"
                        f"mdb.models['{model_name}'].TemperatureBC(name='{bc.name}', createStepName='{bc_step}', "
                        f"region=region, distributionType=UNIFORM, magnitude={mag})\n"
                    )
                    actions.append(builders.python_action(model_name, bc_code))
                elif named_surf:
                    bc_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"region = a.surfaces['{named_surf}']\n"
                        f"mdb.models['{model_name}'].TemperatureBC(name='{bc.name}', createStepName='{bc_step}', "
                        f"region=region, distributionType=UNIFORM, magnitude={mag})\n"
                    )
                    actions.append(builders.python_action(model_name, bc_code))
                else:
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
                elif named_set:
                    bc_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"region = a.sets['{named_set}']\n"
                        f"mdb.models['{model_name}'].DisplacementBC(name='{bc.name}', createStepName='{bc_step}', "
                        f"region=region, {dof_str})\n"
                    )
                    actions.append(builders.python_action(model_name, bc_code))
                    actions.append(builders.displacement_bc(
                        model=model_name,
                        name=bc.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{named_set}']",
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
            named_set, named_surf = _extract_gr_named_selector(gr)
            pts, anch = _extract_gr_pts_and_anchor(gr)
            find_at_str = ", ".join(f"(({p[0]}, {p[1]}, {p[2]}),)" for p in pts) if pts else ""
            if ld.load_type == "pressure":
                if named_surf:
                    load_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"surf = a.surfaces['{named_surf}']\n"
                        f"mdb.models['{model_name}'].Pressure(name='{ld.name}', createStepName='{target_step}', "
                        f"region=surf, magnitude={ld.magnitude}{field_arg})\n"
                    )
                    actions.append(builders.python_action(model_name, load_code))
                    actions.append(builders.pressure_load(
                        model=model_name,
                        name=ld.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.surfaces['{named_surf}']",
                        magnitude=ld.magnitude,
                        step=target_step,
                        field=ld.field,
                    ))
                elif named_set:
                    load_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"surf = a.Surface(side1Faces=a.sets['{named_set}'].faces, name='{ld.region}_Surf')\n"
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
                else:
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
                if named_set:
                    load_code = (
                        f"a = mdb.models['{model_name}'].rootAssembly\n"
                        f"region = a.sets['{named_set}']\n"
                        f"mdb.models['{model_name}'].ConcentratedForce(name='{ld.name}', createStepName='{target_step}', "
                        f"region=region, cf3={ld.magnitude}{field_arg})\n"
                    )
                    actions.append(builders.python_action(model_name, load_code))
                    actions.append(builders.concentrated_force(
                        model=model_name,
                        name=ld.name,
                        region_expression=f"mdb.models['{model_name}'].rootAssembly.sets['{named_set}']",
                        cf3=ld.magnitude,
                        step=target_step,
                    ))
                else:
                    entity_type = _extract_gr_entity_type(gr)
                    if entity_type.lower() == "face":
                        if geometry.shape == "l_bracket":
                            thick = geometry.thickness if geometry.thickness and geometry.thickness > 0 else 10.0
                            wid = geometry.width if geometry.width and geometry.width > 0 else 20.0
                            anch_pt = anch if anch else (0.0, 0.0, 0.0)
                            if abs(anch_pt[1] - (geometry.height or 100.0)) < 1.0 or abs(anch_pt[0] - (geometry.length or 100.0)) < 1.0:
                                face_area = thick * wid
                            else:
                                face_area = (geometry.length or 100.0) * wid
                        elif geometry.shape == "plate_with_hole":
                            p_width = geometry.width if geometry.width > 0 else 100.0
                            p_height = geometry.height if geometry.height > 20.0 else (geometry.length if geometry.length > 20.0 else 100.0)
                            p_depth = geometry.thickness if geometry.thickness is not None else 20.0
                            p_radius = geometry.radius if geometry.radius is not None else 10.0
                            face_area = (p_width * p_height) - (math.pi * p_radius**2)
                        elif geometry.shape == "cantilever_box":
                            face_area = (geometry.width if geometry.width > 0 else 10.0) * (geometry.height if geometry.height > 0 else 10.0)
                        else:
                            face_area = (geometry.width if geometry.width > 0 else 10.0) * (geometry.height if geometry.height > 0 else 10.0)
                        if face_area <= 0:
                            face_area = 1.0
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
                pts, _ = _extract_gr_pts_and_anchor(gr)
                find_at_str = ", ".join(f"(({p[0]}, {p[1]}, {p[2]}),)" for p in pts) if pts else ""
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
    if geometry.shape == "step_assembly":
        if getattr(mesh, "local_seeds", None):
            raise ValueError(
                "step_assembly does not accept part-local seeds until each seed names its solid; "
                "refusing to apply them to one part only"
            )
        mesh_lines = ["import mesh\nfrom abaqusConstants import *\n"]
        for index, part in enumerate(active_scope.parts):
            mesh_lines.append(
                f"p_{index} = mdb.models['{model_name}'].parts['{part.name}']\n"
                f"p_{index}.seedPart(size={mesh.global_size}, deviationFactor={mesh.deviation_factor})\n"
                f"elemType1 = mesh.ElemType(elemCode={mesh.element_type}, elemLibrary={mesh.element_library})\n"
                f"p_{index}.setElementType(regions=(p_{index}.cells,), elemTypes=(elemType1,))\n"
                f"p_{index}.generateMesh()\n"
            )
        actions.append(builders.python_action(model_name, "".join(mesh_lines)))
    elif geometry.shape == "two_blocks_contact":
        if getattr(mesh, "local_seeds", None):
            raise ValueError(
                f"Geometry shape 'two_blocks_contact' does not currently support local_seeds; "
                f"received {len(mesh.local_seeds)} local seed specification(s). Fail-closed to avoid silent omission."
            )
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
        if mesh.local_seeds:
            for ls in mesh.local_seeds:
                reg_expr = getattr(ls, "region_expression", None)
                ls_size = getattr(ls, "size", None)
                ls_num = getattr(ls, "number", None)
                ls_c_raw = getattr(ls, "constraint", None) or "FREE"
                ls_c_str = str(ls_c_raw).upper()
                c_map = {"SMOOTH": "FREE", "NONE": "FREE", "CONTROLLED": "FIXED"}
                ls_c = c_map.get(ls_c_str, ls_c_str)
                if ls_size is not None:
                    actions.append(builders.local_seed_size(
                        model=model_name,
                        part=part_name,
                        region_expression=reg_expr,
                        size=ls_size,
                        constraint=ls_c,
                    ))
                elif ls_num is not None:
                    actions.append(builders.local_seed_number(
                        model=model_name,
                        part=part_name,
                        region_expression=reg_expr,
                        number=ls_num,
                        constraint=ls_c,
                    ))
                else:
                    raise ValueError(f"Local seed requires either size or number: {ls}")
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
    # Contact stabilization is only auditable if the dissipation it introduces is
    # written to the ODB. Abaqus does not include ALLSD in the default PRESELECT
    # history output, so a dedicated request is added on the stabilized step.
    # Without it the acceptance gate would be permanently BLOCKED for lack of
    # evidence, which is indistinguishable from a failed repair.
    for _stab_step in stabilized_target_steps:
        stab_energy_out = (
            f"import step\n"
            f"if 'H-Energy-Stabilization' not in mdb.models['{model_name}'].historyOutputRequests:\n"
            f"    mdb.models['{model_name}'].HistoryOutputRequest(\n"
            f"        name='H-Energy-Stabilization', createStepName='{_stab_step}',\n"
            f"        variables=('ALLSD', 'ALLSE', 'ALLIE', 'ETOTAL'))\n"
        )
        actions.append(builders.python_action(model_name, stab_energy_out))

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
            "assembly_scope": None if active_scope is None else active_scope.to_dict(),
        },
        "material": material.to_dict(),
        "material_name": material.name,
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
        material=material,
    )


def _extract_gr_pts_and_anchor(gr: Any) -> Tuple[Tuple[Tuple[float, float, float], ...], Optional[Tuple[float, float, float]]]:
    """Helper to extract anchor points and primary anchor point from GroundedRegion or dict."""
    if gr is None:
        return (), None
    pts: Tuple[Tuple[float, float, float], ...] = ()
    anch: Optional[Tuple[float, float, float]] = None
    if isinstance(gr, dict):
        raw_pts = gr.get("anchor_points")
        if raw_pts and isinstance(raw_pts, (list, tuple)):
            converted_pts = []
            for p in raw_pts:
                if _is_valid_3d_point(p):
                    converted_pts.append((float(p[0]), float(p[1]), float(p[2])))
            pts = tuple(converted_pts)
        raw_anch = gr.get("anchor_point")
        if raw_anch and _is_valid_3d_point(raw_anch):
            anch = (float(raw_anch[0]), float(raw_anch[1]), float(raw_anch[2]))
        if not pts and anch:
            pts = (anch,)
        if not anch and pts:
            anch = pts[0]
    else:
        raw_pts = getattr(gr, "anchor_points", None)
        if raw_pts and isinstance(raw_pts, (list, tuple)):
            converted_pts = []
            for p in raw_pts:
                if _is_valid_3d_point(p):
                    converted_pts.append((float(p[0]), float(p[1]), float(p[2])))
            pts = tuple(converted_pts)
        raw_anch = getattr(gr, "anchor_point", None)
        if raw_anch and _is_valid_3d_point(raw_anch):
            anch = (float(raw_anch[0]), float(raw_anch[1]), float(raw_anch[2]))
        if not pts and anch:
            pts = (anch,)
        if not anch and pts:
            anch = pts[0]
    return pts, anch


def _extract_gr_target_semantic(gr: Any) -> str:
    """Helper to extract target_semantic from GroundedRegion or dict."""
    if gr is None:
        return ""
    if isinstance(gr, dict):
        return str(gr.get("target_semantic", ""))
    return str(getattr(gr, "target_semantic", ""))


def _extract_gr_entity_type(gr: Any) -> str:
    """Helper to extract entity_type from GroundedRegion or dict."""
    if gr is None:
        return "face"
    if isinstance(gr, dict):
        return str(gr.get("entity_type", "face"))
    return str(getattr(gr, "entity_type", "face"))


def _is_valid_3d_point(pt: Any) -> bool:
    """Validate that a point is a 3-element coordinate of finite non-boolean floats."""
    if not isinstance(pt, (list, tuple)) or len(pt) < 3:
        return False
    for c in pt[:3]:
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            return False
        try:
            fc = float(c)
            if not math.isfinite(fc):
                return False
        except (ValueError, TypeError):
            return False
    return True


def _extract_gr_named_selector(gr: Any) -> Tuple[Optional[str], Optional[str]]:
    """Extract (named_set, named_surface) from GroundedRegion or dict if present."""
    if gr is None:
        return None, None
    named_set: Optional[str] = None
    named_surf: Optional[str] = None
    if isinstance(gr, dict):
        s = gr.get("set")
        if isinstance(s, str) and s.strip():
            named_set = s.strip()
        sf = gr.get("surface")
        if isinstance(sf, str) and sf.strip():
            named_surf = sf.strip()
    else:
        s = getattr(gr, "set", None)
        if isinstance(s, str) and s.strip():
            named_set = s.strip()
        sf = getattr(gr, "surface", None)
        if isinstance(sf, str) and sf.strip():
            named_surf = sf.strip()
    return named_set, named_surf


def _is_valid_grounded_region(gr: Any) -> bool:
    """Validate whether a grounded region representation has genuine geometry mapping anchors or consumable named selectors."""
    if gr is None:
        return False

    # 1. Unresolved flag check (both object and dict)
    if getattr(gr, "resolved", None) is False:
        return False
    if isinstance(gr, dict) and gr.get("resolved") is False:
        return False

    # 2. Status check (both object and dict)
    status = getattr(gr, "status", None) if not isinstance(gr, dict) else gr.get("status")
    if status is not None:
        st_str = str(status).strip().upper()
        if st_str in ("NOT_FOUND", "AMBIGUOUS", "UNSUPPORTED", "UNRESOLVED") or not st_str:
            return False
        if any(unres in st_str for unres in ("NOT_", "UNRESOLVED", "FAIL", "INVALID")):
            return False

    # 3. Confidence check (both object and dict)
    conf = getattr(gr, "confidence", None) if not isinstance(gr, dict) else gr.get("confidence")
    if conf is not None:
        try:
            if isinstance(conf, bool) or float(conf) <= 0.0 or not math.isfinite(float(conf)):
                return False
        except (ValueError, TypeError):
            return False

    # 4. Anchor points validation
    pts = getattr(gr, "anchor_points", None) if not isinstance(gr, dict) else gr.get("anchor_points")
    if pts and isinstance(pts, (list, tuple)) and len(pts) > 0:
        if all(_is_valid_3d_point(p) for p in pts):
            return True
        return False

    pt = getattr(gr, "anchor_point", None) if not isinstance(gr, dict) else gr.get("anchor_point")
    if pt is not None:
        if _is_valid_3d_point(pt):
            return True
        return False

    # 5. Consumable named topological selectors (named set or surface with non-empty string name)
    named_set, named_surf = _extract_gr_named_selector(gr)
    if named_set is not None or named_surf is not None:
        return True

    return False


def _geometry_model_from_value(value: Any):
    """Return a GeometryModel when the caller passed one, including a wrapped dict."""
    from ..geometry.model import GeometryModel

    if isinstance(value, GeometryModel):
        return value
    if isinstance(value, dict):
        nested = value.get("geometry_model") or value.get("model")
        if isinstance(nested, GeometryModel):
            return nested
    return None


def _screen_inputs_from_intent(intent: Optional[object]) -> dict:
    """Read an already-resolved screen. Do not invent part membership here."""
    if intent is None:
        return {}
    metadata = getattr(intent, "metadata", None) or {}
    if not isinstance(metadata, dict):
        return {}
    screen = metadata.get("assembly_screen")
    if screen is None:
        return {}
    return {"screen": screen}


def _bind_step_assembly_scope(
    geometry: IntentGeometrySpec,
    *,
    allow_missing_step_file: bool = False,
    requirement: Optional[object] = None,
    screen: Optional[object] = None,
    judgments: Optional[object] = None,
) -> IntentGeometrySpec:
    """Attach the requirement-screened scope, or refuse an unresolved inventory.

    Contact and fixture geometry are never invented here. A multi-solid STEP
    model is not analyzed in full unless the requirement explicitly says so.
    """
    from ..geometry.assembly_scope import build_assembly_scope
    from ..geometry.cad_ingestion import ingest_cad_file
    from ..geometry.model import GeometryModel

    raw_scope = getattr(geometry, "assembly_scope", None)
    model = _geometry_model_from_value(raw_scope) or _geometry_model_from_value(geometry)
    step_path = getattr(geometry, "step_file_path", None)
    # A primitive template may cite a STEP fixture for provenance. Only an
    # explicit STEP/assembly request, or a supplied CAD model, changes scope.
    should_ingest = (
        model is None
        and bool(step_path)
        and geometry.shape in ("step_file", "step_assembly")
    )
    if should_ingest and not allow_missing_step_file:
        if not os.path.isfile(step_path):
            raise ValueError(
                f"STEP geometry file does not exist: {step_path}. "
                "Refusing to compile a single-part template for an unread multi-solid model."
            )
        model = ingest_cad_file(step_path)
    if not isinstance(model, GeometryModel) or model.solid_count <= 1:
        return geometry

    scope = build_assembly_scope(
        model,
        requirement=requirement,
        screen=screen,
        judgments=judgments,
    )
    if not scope.is_complete:
        raise ValueError(
            "Multi-solid STEP inventory cannot be solved until the analysis requirement "
            f"screens it. Assembly scope is incomplete: {list(scope.gaps)}. "
            "Retained parts, mating contact, and the installation fixture must be grounded; "
            "do not fall back to every solid or to one solid."
        )
    return IntentGeometrySpec(
        shape="step_assembly",
        length=geometry.length,
        width=geometry.width,
        height=geometry.height,
        radius=geometry.radius,
        thickness=geometry.thickness,
        step_file_path=step_path or model.provenance.file_path,
        assembly_scope=scope,
    )


def compile_engineering_intent(
    intent: EngineeringIntent,
    model_name: Optional[str] = None,
    part_name: Optional[str] = None,
    job_name: Optional[str] = None,
    geometry: Optional[Union[IntentGeometrySpec, Dict[str, Any]]] = None,
    material: Optional[Union[MaterialDefinition, Dict[str, Any], str]] = None,
    mesh: Optional[IntentMeshSpec] = None,
    grounded_regions: Optional[Dict[str, GroundedRegion]] = None,
    submit_job: bool = False,
    allow_missing_step_file: bool = False,
) -> CompiledAgentPlan:
    """Compile a high-level EngineeringIntent directly into a CompiledAgentPlan.

    Bridges declarative, multi-source EngineeringIntent models (from natural language,
    vision, or programmatic definitions) into canonical AbaqusActions, ensuring
    strict fail-closed validation for missing geometry, material, or boundary definitions.
    """
    if not isinstance(intent, EngineeringIntent):
        raise TypeError(f"Expected EngineeringIntent, got {type(intent).__name__}")
    if not getattr(intent, "is_executable", True):
        raise ValueError("Draft or non-executable EngineeringIntent cannot be compiled into an execution plan.")

    from ..validation.condition_fidelity import audit_condition_fidelity
    fidelity = audit_condition_fidelity(intent, description=intent.description or "")
    if fidelity["blockers"]:
        raise ValueError(
            "Cannot compile engineering intent: condition fidelity is unresolved ("
            + "; ".join(fidelity["blockers"])
            + "). No default coating thickness, modulus, cracking strain, indenter size, "
            "friction, or regulation mapping is assumed."
        )

    # 1. Resolved Names
    safe_id = "".join(c if c.isalnum() or c == "_" else "_" for c in intent.id)
    eff_model = model_name or intent.metadata.get("model_name") or f"Model_{safe_id}"
    eff_part = part_name or intent.metadata.get("part_name") or "MainPart"
    eff_job = job_name or intent.metadata.get("job_name") or f"Job_{safe_id}"

    # 2. Geometry Resolution (Fail-closed on complete omission)
    eff_geom = geometry
    if isinstance(eff_geom, dict):
        if "box" in eff_geom and isinstance(eff_geom["box"], (list, tuple)) and len(eff_geom["box"]) >= 3:
            b = eff_geom["box"]
            eff_geom = IntentGeometrySpec(
                shape=str(eff_geom.get("shape", "cantilever_box")),
                length=float(b[0]),
                width=float(b[1]),
                height=float(b[2]),
            )
        elif "shape" in eff_geom:
            eff_geom = IntentGeometrySpec(**eff_geom)
        else:
            eff_geom = IntentGeometrySpec(
                shape=str(eff_geom.get("shape", "cantilever_box")),
                length=float(eff_geom.get("length", 100.0)),
                width=float(eff_geom.get("width", 10.0)),
                height=float(eff_geom.get("height", 10.0)),
                radius=float(eff_geom["radius"]) if "radius" in eff_geom else None,
                thickness=float(eff_geom["thickness"]) if "thickness" in eff_geom else None,
                step_file_path=eff_geom.get("step_file_path"),
            )
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
    screen_inputs = _screen_inputs_from_intent(intent)
    eff_geom = _bind_step_assembly_scope(
        eff_geom,
        allow_missing_step_file=allow_missing_step_file,
        requirement=getattr(intent, "description", None),
        **screen_inputs,
    )

    # 3. Material Resolution (Fail-closed on complete omission)
    raw_mat = material if material is not None else intent.material
    if raw_mat is None:
        raise ValueError(
            "Cannot compile engineering intent: missing material specification. "
            "Provide material via intent.material or explicit material parameter."
        )

    from ..reasoning.material_catalog import resolve_material_to_definition
    u_sys = intent.unit_system or "MM_N_MPA"
    eff_mat = resolve_material_to_definition(raw_mat, unit_system=u_sys, fail_closed=True)

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
            if analysis in ("bolt_pretension", "bolt_service") or intent.metadata.get("bolt_pretensions"):
                eff_steps = [
                    IntentStepSpec(name="Step-Preload", step_type="static_general", nlgeom=False),
                    IntentStepSpec(name="Step-Service", step_type="static_general", nlgeom=False, previous="Step-Preload"),
                ]
            elif analysis in ("nonlinear_static", "plasticity"):
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

        if eff_step is not None and intent.metadata.get("step_controls"):
            sc = intent.metadata["step_controls"]
            eff_step = IntentStepSpec(
                name=eff_step.name,
                step_type=eff_step.step_type,
                nlgeom=eff_step.nlgeom,
                time_period=eff_step.time_period,
                previous=eff_step.previous,
                stabilization_method=sc.get("stabilization_method", eff_step.stabilization_method),
                stabilization_magnitude=sc.get("stabilization_magnitude", eff_step.stabilization_magnitude),
                max_num_inc=sc.get("max_num_inc", eff_step.max_num_inc),
                initial_inc=sc.get("initial_inc", eff_step.initial_inc),
                min_inc=sc.get("min_inc", eff_step.min_inc),
                max_inc=sc.get("max_inc", eff_step.max_inc),
            )

    # 4b. Step controls must reach every step path, not just the single-step
    # branch. Self-healing writes initial_inc/min_inc/max_inc and stabilization
    # into metadata["step_controls"]; a procedure or a steps list used to drop
    # them silently.
    _raw_step_controls = intent.metadata.get("step_controls") or {}
    if _raw_step_controls:
        _sc = dict(_raw_step_controls)
        if eff_step is not None:
            eff_step = IntentStepSpec(
                name=eff_step.name,
                step_type=eff_step.step_type,
                nlgeom=eff_step.nlgeom,
                time_period=eff_step.time_period,
                previous=eff_step.previous,
                stabilization_method=_sc.get("stabilization_method", eff_step.stabilization_method),
                stabilization_magnitude=_sc.get("stabilization_magnitude", eff_step.stabilization_magnitude),
                max_num_inc=_sc.get("max_num_inc", eff_step.max_num_inc),
                initial_inc=_sc.get("initial_inc", eff_step.initial_inc),
                min_inc=_sc.get("min_inc", eff_step.min_inc),
                max_inc=_sc.get("max_inc", eff_step.max_inc),
            )
        if eff_steps is not None:
            eff_steps = tuple(
                IntentStepSpec(
                    name=s.name,
                    step_type=s.step_type,
                    nlgeom=s.nlgeom,
                    time_period=s.time_period,
                    previous=s.previous,
                    stabilization_method=_sc.get("stabilization_method", s.stabilization_method),
                    stabilization_magnitude=_sc.get("stabilization_magnitude", s.stabilization_magnitude),
                    max_num_inc=_sc.get("max_num_inc", s.max_num_inc),
                    initial_inc=_sc.get("initial_inc", s.initial_inc),
                    min_inc=_sc.get("min_inc", s.min_inc),
                    max_inc=_sc.get("max_inc", s.max_inc),
                )
                for s in eff_steps
            )
        if eff_procedure is not None:
            eff_procedure = MultiStepProcedureSpec(
                steps=tuple(
                    replace(s, metadata=dict(s.metadata, step_controls=dict(_sc)))
                    for s in eff_procedure.steps
                )
            )

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
        elif isinstance(intent.mesh_requirements, MeshSpecification):
            ms = intent.mesh_requirements
            eff_elem_type = "C3D8R"
            eff_lib = "STANDARD"
            if ms.element_types:
                et0 = ms.element_types[0]
                eff_elem_type = et0.get("elem_code", et0.get("elemCode", "C3D8R"))
                eff_lib = et0.get("elem_library", et0.get("elemLibrary", "STANDARD"))
            eff_mesh = IntentMeshSpec(
                element_type=eff_elem_type,
                global_size=float(ms.global_size),
                deviation_factor=float(ms.deviation_factor),
                element_library=eff_lib,
                local_seeds=ms.local_seeds,
            )
        elif isinstance(intent.mesh_requirements, dict):
            m_req = intent.mesh_requirements
            raw_local_seeds = m_req.get("local_seeds", ())
            parsed_local_seeds = []
            for item in raw_local_seeds:
                if isinstance(item, LocalSeed):
                    parsed_local_seeds.append(item)
                elif isinstance(item, dict):
                    parsed_local_seeds.append(LocalSeed(
                        region_expression=item["region_expression"],
                        size=item.get("size"),
                        number=item.get("number"),
                        constraint=item.get("constraint"),
                    ))
                else:
                    raise TypeError(f"Invalid local seed item in dict: {item!r}")
            raw_g_size = m_req.get("global_size", 2.5)
            if raw_g_size is None or float(raw_g_size) <= 0:
                raise ValueError(f"Explicit mesh requirement global_size must be positive, got {raw_g_size!r}")
            eff_mesh = IntentMeshSpec(
                element_type=m_req.get("element_type", "C3D8R"),
                global_size=float(raw_g_size),
                deviation_factor=float(m_req.get("deviation_factor", 0.1)),
                element_library=m_req.get("element_library", "STANDARD"),
                local_seeds=tuple(parsed_local_seeds),
            )
        else:
            raise TypeError(f"Unsupported mesh_requirements type: {type(intent.mesh_requirements)}")
    if eff_mesh is None:
        eff_mesh = IntentMeshSpec()

    # Check unresolvable partition requirements in mesh metadata
    geom_plan = intent.metadata.get("geometry_mesh_plan")
    if geom_plan is not None:
        unresolved_partitions = [
            ref for ref in getattr(geom_plan, "refinements", ())
            if getattr(ref, "requires_partition", False) or getattr(ref, "method", "") == "partition_then_seed"
        ]
        if unresolved_partitions:
            targets = [r.target for r in unresolved_partitions]
            raise ValueError(
                f"Mesh refinement requires unexecuted geometric partitioning for targets: {targets}. "
                "Fail-closed: cannot silently omit partition-dependent local mesh refinement."
            )

    # 7.5. Topological Grounding Gate for non-primitive geometry
    is_step_or_external = (
        getattr(eff_geom, "shape", "") == "step_file"
        or getattr(eff_geom, "step_file_path", None) is not None
    )
    eff_grounded = grounded_regions or intent.metadata.get("grounded_regions") or {}
    if not isinstance(eff_grounded, dict):
        eff_grounded = {}

    active_scope = getattr(eff_geom, "assembly_scope", None) or intent.metadata.get("assembly_scope")
    if active_scope is not None and getattr(eff_geom, "shape", "") != "step_assembly":
        raise ValueError(
            "Multi-part assembly_scope cannot be compiled through a single-part geometry shape. "
            "Use shape='step_assembly' so every solid, contact, and fixture is emitted."
        )
    if getattr(eff_geom, "shape", "") == "step_assembly" and not getattr(active_scope, "is_complete", False):
        raise ValueError(
            "step_assembly refused: assembly scope is missing or incomplete. "
            "A handle plus its related parts cannot be solved as one solid."
        )

    if is_step_or_external and getattr(eff_geom, "shape", "") != "step_assembly":
        referenced_regions = set()
        for bc in compiled_bcs:
            if getattr(bc, "region", None):
                referenced_regions.add(str(bc.region))
        for ld in compiled_loads:
            if getattr(ld, "region", None):
                referenced_regions.add(str(ld.region))

        missing_or_invalid = [
            reg for reg in sorted(referenced_regions)
            if not _is_valid_grounded_region(eff_grounded.get(reg))
        ]
        if missing_or_invalid:
            step_path = getattr(eff_geom, "step_file_path", None)
            raise ValueError(
                f"Cannot compile engineering intent: geometry relies on external STEP file ({step_path}), "
                f"but referenced boundary/load regions {missing_or_invalid} lack valid GroundedRegion mappings. "
                "Provide complete and valid GroundedRegion mappings before compiling execution plan."
            )

    # 8. Multi-domain special contracts
    eff_fields = intent.metadata.get("fields")
    eff_bolts = intent.metadata.get("bolt_pretensions")
    eff_moments = intent.metadata.get("moments")
    eff_interactions = intent.contacts or intent.metadata.get("interactions")
    eff_predefined = intent.metadata.get("predefined_fields")

    eff_fatigue = intent.fatigue
    eff_connectors = intent.connectors or None
    eff_fmbd = intent.fmbd
    eff_contact_stabilization = intent.metadata.get("contact_stabilization")

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
        assembly_scope=active_scope,
        predefined_fields=eff_predefined,
        fatigue=eff_fatigue,
        connectors=eff_connectors,
        fmbd=eff_fmbd,
        contact_stabilization=eff_contact_stabilization,
        submit_job=submit_job,
    )
