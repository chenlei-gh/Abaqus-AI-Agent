"""R1: Agent-Native Engineering Intent Compiler.

Compiles high-level EngineeringIntent specifications into an executable,
ordered sequence of AbaqusActions, and renders them into native Abaqus/CAE Python scripts.
Eliminates hardcoded CAE scripts in favor of dynamic intent compilation.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts.action import AbaqusAction
from ..contracts.material import MaterialDefinition
from ..actions import builders
from ..actions.script import action_to_script


@dataclass(frozen=True)
class IntentGeometrySpec:
    shape: str = "cantilever_box"             # "cantilever_box", "cylinder", "plate"
    length: float = 100.0                     # mm
    width: float = 10.0                       # mm
    height: float = 10.0                      # mm
    radius: Optional[float] = None
    thickness: Optional[float] = None


@dataclass(frozen=True)
class IntentBoundarySpec:
    name: str
    bc_type: str                              # "ENCASTRE", "PINNED", "DISPLACEMENT"
    region: str                               # e.g. "FixedFace", "Root"
    values: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class IntentLoadSpec:
    name: str
    load_type: str                            # "concentrated_force", "pressure", "gravity"
    region: str                               # e.g. "TipFace", "TopSurface"
    magnitude: float
    direction: str = "CF2"                    # "CF1", "CF2", "CF3"


@dataclass(frozen=True)
class IntentStepSpec:
    name: str = "Step-1"
    step_type: str = "static_general"         # "static_general", "frequency", "implicit_dynamic"
    nlgeom: bool = False
    time_period: float = 1.0


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
    step: IntentStepSpec,
    bcs: Sequence[IntentBoundarySpec],
    loads: Sequence[IntentLoadSpec],
    mesh: IntentMeshSpec,
) -> CompiledAgentPlan:
    """Compile structured engineering intent into an ordered sequence of AbaqusActions."""
    actions: List[AbaqusAction] = []

    # 1. Geometry Construction (Native Python CAE Action)
    if geometry.shape == "cantilever_box":
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
    # Assign section to entire cell of part
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

    # 5. Analysis Step Action
    if step.step_type == "static_general":
        actions.append(builders.static_step(
            model=model_name,
            name=step.name,
            previous="Initial",
            nlgeom=step.nlgeom,
            time_period=step.time_period,
        ))
    elif step.step_type == "frequency":
        actions.append(builders.frequency_step(
            model=model_name,
            name=step.name,
            previous="Initial",
            num_eigen=10,
        ))
    else:
        actions.append(builders.static_step(model=model_name, name=step.name))

    # 6. Boundary Conditions Actions
    for bc in bcs:
        if bc.bc_type == "ENCASTRE":
            # Select root face at z=0
            bc_code = (
                f"a = mdb.models['{model_name}'].rootAssembly\n"
                f"f = a.instances['{inst_name}'].faces\n"
                f"fixed_faces = f.findAt((({geometry.width/2.0}, {geometry.height/2.0}, 0.0),))\n"
                f"region = a.Set(faces=fixed_faces, name='{bc.region}')\n"
                f"mdb.models['{model_name}'].EncastreBC(name='{bc.name}', createStepName='Initial', region=region)\n"
            )
            actions.append(builders.python_action(model_name, bc_code))

    # 7. Load Actions
    for ld in loads:
        if ld.load_type == "concentrated_force":
            # Apply tip force at z=L
            load_code = (
                f"a = mdb.models['{model_name}'].rootAssembly\n"
                f"v = a.instances['{inst_name}'].vertices\n"
                f"tip_verts = v.findAt((({geometry.width}, {geometry.height}, {geometry.length}),))\n"
                f"region = a.Set(vertices=tip_verts, name='{ld.region}')\n"
                f"cf_val = {ld.magnitude}\n"
                f"mdb.models['{model_name}'].ConcentratedForce(name='{ld.name}', createStepName='{step.name}', "
                f"region=region, {ld.direction}=cf_val)\n"
            )
            actions.append(builders.python_action(model_name, load_code))

    # 8. Mesh Generation Actions
    actions.append(builders.seed_part(
        model=model_name,
        part=part_name,
        size=mesh.global_size,
        deviation_factor=mesh.deviation_factor,
    ))
    mesh_elem_code = (
        f"p = mdb.models['{model_name}'].parts['{part_name}']\n"
        f"elemType1 = mesh.ElemType(elemCode={mesh.element_type}, elemLibrary=STANDARD)\n"
        f"p.setElementType(regions=(p.cells,), elemTypes=(elemType1,))\n"
        f"p.generateMesh()\n"
    )
    actions.append(builders.python_action(model_name, mesh_elem_code))

    # 9. Output Requests & Job Creation
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
        },
        "material": material.name,
        "actions_count": len(actions),
    }

    return CompiledAgentPlan(
        model_name=model_name,
        part_name=part_name,
        job_name=job_name,
        actions=tuple(actions),
        cae_script=full_script,
        intent_summary=intent_summary,
    )
