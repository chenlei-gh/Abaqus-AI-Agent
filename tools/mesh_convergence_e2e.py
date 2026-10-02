#!/usr/bin/env python3
"""Run the Mesh Convergence E2E Case through the real Abaqus runtime.

This tool executes a three-level mesh refinement study (coarse, medium, fine)
on the 3D cantilever beam using the project's existing Action, AnalysisRunner,
ODB extraction, numerical-verification (Richardson/GCI), mesh-convergence,
and acceptance components.

It verifies:
1. Three distinct ODBs are produced by real solver runs.
2. Distinct element and node counts are recorded across all three meshes.
3. Element count strictly increases (refinement ratio = 2.0).
4. Tip displacements are extracted from real ODBs and converge.
5. Richardson extrapolation and GCI are computed from real FE results.
6. Deterministic acceptance passes under standard engineering tolerances.
7. Acceptance explicitly FAILS under artificially strict tolerances.
8. A single aggregated evidence bundle correlates all three runs.
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.execution.batch import BatchExecutor

MODEL = "MeshConvModel"
PART = "Beam"
INSTANCE = "Beam-1"
STEP = "Step-1"

L = 100.0
B = 10.0
H = 10.0
E = 210000.0
NU = 0.3
FORCE = -1000.0


def build_mesh_convergence_script(src_dir=None):
    src_dir = str(src_dir or SRC)

    geometry_code = r"""
from abaqus import mdb
from abaqusConstants import THREE_D, DEFORMABLE_BODY, ON, CARTESIAN

if %r in mdb.models:
    del mdb.models[%r]
model = mdb.Model(name=%r)

sketch = model.ConstrainedSketch(name='BeamProfile', sheetSize=300.0)
sketch.rectangle(point1=(0.0, 0.0), point2=(%r, %r))
part = model.Part(name=%r, dimensionality=THREE_D, type=DEFORMABLE_BODY)
part.BaseSolidExtrude(sketch=sketch, depth=%r)
del model.sketches['BeamProfile']

assembly = model.rootAssembly
assembly.DatumCsysByDefault(CARTESIAN)
assembly.Instance(name=%r, part=part, dependent=ON)
inst = assembly.instances[%r]

fixed_face = inst.faces.findAt(((0.0, %r, %r),))
tip_face = inst.faces.findAt(((%r, %r, %r),))
assembly.Set(name='FixedFace', faces=fixed_face)
assembly.Set(name='TipFace', faces=tip_face)

tip_vertices = inst.vertices.findAt(
    ((%r, 0.0, 0.0),),
    ((%r, %r, 0.0),),
    ((%r, 0.0, %r),),
    ((%r, %r, %r),),
)
assembly.Set(name='TipLoadVertices', vertices=tip_vertices)
part.Set(name='AllCells', cells=part.cells)

print('AIAgent_MESH_CONV_GEOMETRY_CREATED')
""" % (
        MODEL, MODEL, MODEL, L, H, PART, B, INSTANCE, INSTANCE,
        H / 2.0, B / 2.0, L, H / 2.0, B / 2.0,
        L, L, H, L, B, L, H, B,
    )

    update_evidence_sets_code = r"""
def _update_evidence_sets():
    from abaqus import mdb
    model = mdb.models[%r]
    part = model.parts[%r]
    inst = model.rootAssembly.instances[%r]
    model.rootAssembly.regenerate()

    fixed_nodes = inst.nodes.getByBoundingBox(xMin=-0.01, xMax=0.01)
    if not fixed_nodes:
        raise RuntimeError('FixedNodes set is empty')
    model.rootAssembly.Set(name='FixedNodes', nodes=fixed_nodes)

    tip_nodes = inst.nodes.getByBoundingBox(xMin=99.99, xMax=100.01)
    if not tip_nodes:
        raise RuntimeError('TipNodes set is empty')
    model.rootAssembly.Set(name='TipNodes', nodes=tip_nodes)

    root_elements = part.elements.getByBoundingBox(xMin=-0.01, xMax=10.01)
    if not root_elements:
        raise RuntimeError('RootElements set is empty')
    part.Set(name='RootElements', elements=root_elements)
""" % (MODEL, PART, INSTANCE)

    return """
import sys
_src_dir = %r
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import ast
import io
import json
import math
import os
from dataclasses import asdict, is_dataclass

from abaqus import mdb
from abaqusConstants import *

from abaqus_ai_agent.actions.builders import (
    python_action, section_assignment, seed_part, element_type,
    generate_mesh, mesh_quality, create_job,
)
from abaqus_ai_agent.actions.runner import execute
from abaqus_ai_agent.workflow.static import build_static_plan
from abaqus_ai_agent.execution.client import InProcessExecutor
from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
from abaqus_ai_agent.execution.odb import extract_field
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.mesh_quality import MeshQualityResult
from abaqus_ai_agent.contracts.convergence import (
    MeshConvergencePoint, MeshConvergencePolicy, evaluate_mesh_convergence
)
from abaqus_ai_agent.numerical_verification import verify_richardson
from abaqus_ai_agent.engineering_evidence import reaction_balance_from_field_evidence
from abaqus_ai_agent.acceptance import evaluate_result_acceptance

model_name = %r
part_name = %r
instance_name = %r
step_name = %r
beam_l = %r
beam_b = %r
beam_h = %r
mat_e = %r
mat_nu = %r
applied_force = %r

def _run_code(code):
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        exec(compile(code, '<AIAgent-MeshConvergence>', 'exec'), globals(), globals())
    finally:
        sys.stdout = old_stdout
    out = buf.getvalue().strip()
    res = globals().get('result')
    if isinstance(res, dict):
        return res
    if out:
        last_line = out.splitlines()[-1].strip()
        try:
            val = ast.literal_eval(last_line)
            if isinstance(val, dict):
                return val
        except Exception:
            pass
        return {'status': 'COMPLETED', 'stdout': out, 'output': out}
    return {'status': 'COMPLETED'}

class CAEInProcessExecutor(InProcessExecutor):
    def inspect_odb(self, path):
        from odbAccess import openOdb
        odb = openOdb(path=path, readOnly=True)
        inst_key = instance_name.upper() if instance_name.upper() in odb.rootAssembly.instances else instance_name
        inst_obj = odb.rootAssembly.instances[inst_key] if inst_key in odb.rootAssembly.instances else None
        res = {
            'status': 'available',
            'steps': list(odb.steps.keys()),
            'instances': list(odb.rootAssembly.instances.keys()),
            'step_frames': {k: len(v.frames) for k, v in odb.steps.items()},
            'element_count': len(inst_obj.elements) if inst_obj is not None else 0,
            'node_count': len(inst_obj.nodes) if inst_obj is not None else 0,
        }
        odb.close()
        return res

executor = CAEInProcessExecutor(_run_code)

%s

# 1. Base Geometry
geometry = python_action(model_name, %r)
execute(executor, geometry)

# 2. Base static plan (materials, section, BC, loads)
plan = build_static_plan(
    model_name,
    {'name': 'Steel', 'youngs_modulus': mat_e, 'poisson': mat_nu},
    {
        'section': 'BeamSection',
        'fixed': "mdb.models['MeshConvModel'].rootAssembly.sets['FixedFace']",
        'load': "mdb.models['MeshConvModel'].rootAssembly.sets['TipLoadVertices']",
    },
    force={'cf2': applied_force / 4.0},
    job_name='DummyJob',
    step_name=step_name,
)

# Execute material, step, boundary condition, and load actions (skip dummy job)
setup_actions = list(plan.actions[:-1])
setup_actions.insert(3, section_assignment(
    model_name, part_name, 'BeamSection',
    "mdb.models['MeshConvModel'].parts['Beam'].sets['AllCells']",
))
for act in setup_actions:
    execute(executor, act)

# 3. Three-level mesh refinement definition
mesh_cases = [
    {'name': 'coarse', 'seed': 5.0,  'job': 'MeshConv_Coarse'},
    {'name': 'medium', 'seed': 2.5,  'job': 'MeshConv_Medium'},
    {'name': 'fine',   'seed': 1.25, 'job': 'MeshConv_Fine'},
]

runs = []
points_data = []

criteria_template = (
    {
        'name': 'tip_displacement_sanity',
        'value_key': 'tip_displacement',
        'operator': '>=',
        'limit': 1.0,
        'unit': 'mm',
        'result': {
            'field': 'U',
            'invariant': 'MAGNITUDE',
            'aggregation': 'max',
            'step': step_name,
            'frame': -1,
            'region': "odb.rootAssembly.nodeSets['TIPLOADVERTICES']",
        },
    },
)

for case in mesh_cases:
    case_name = case['name']
    seed_size = case['seed']
    job_name = case['job']

    # Delete previous mesh if exists
    part = mdb.models[model_name].parts[part_name]
    try:
        part.deleteMesh()
    except Exception:
        pass

    # Seed part
    execute(executor, seed_part(model_name, part_name, seed_size))

    # Set element type to C3D8R
    execute(executor, element_type(
        model_name, part_name,
        "mdb.models['MeshConvModel'].parts['Beam'].sets['AllCells']",
        elem_code='C3D8R', library='STANDARD',
    ))

    # Generate mesh
    execute(executor, generate_mesh(model_name, part_name))

    # Update evidence sets on new mesh
    _update_evidence_sets()

    # Verify mesh quality
    mesh_check = execute(executor, mesh_quality(
        model_name, part_name,
        max_aspect_ratio=5.0,
        max_angular_deviation=20.0,
        max_geometric_deviation_factor=0.1,
        analysis_checks=True,
    ))

    elem_count = len(part.elements)
    node_count = len(part.nodes)

    # Create and run job
    execute(executor, create_job(model_name, job_name))
    odb_expected_path = os.path.abspath(job_name + '.odb')

    run = AnalysisRunner(executor).run(
        model_name=model_name,
        job_name=job_name,
        odb_path=odb_expected_path,
        criteria=criteria_template,
        timeout=3600,
        engineering_intent=EngineeringIntent(
            id='mesh-conv-' + case_name,
            kind='linear_static_cantilever',
            description='Mesh convergence run for ' + case_name,
            analysis_type='static',
            loads=('concentrated_force',),
            metadata={'solver': 'standard', 'seed': seed_size},
        ),
    )

    if not run.odb_path or not os.path.exists(run.odb_path):
        raise RuntimeError('Job ' + str(job_name) + ' did not produce valid ODB')

    # Extract tip displacement
    disp_field = extract_field(
        executor, run.odb_path, step_name, 'U',
        invariant='MAGNITUDE',
        region="odb.rootAssembly.nodeSets['TIPLOADVERTICES']",
    )
    disp_values = [v['data'] for v in disp_field.get('values', []) if isinstance(v.get('data'), (int, float))]
    tip_disp = max(disp_values) if disp_values else 0.0

    # Extract reaction forces
    reaction_field = extract_field(
        executor, run.odb_path, step_name, 'RF',
        frame=-1, region="odb.rootAssembly.nodeSets['FIXEDNODES']",
    )
    reaction_report, reaction_summary = reaction_balance_from_field_evidence(
        {'status': 'available', 'values': reaction_field.get('values', [])},
        applied_components=(0.0, applied_force, 0.0),
        tolerance=0.01,
        unit='N',
    )

    # Also inspect ODB element and node counts
    odb_meta = executor.inspect_odb(run.odb_path)

    run_entry = {
        'case': case_name,
        'seed_size': seed_size,
        'job_name': job_name,
        'odb_path': run.odb_path,
        'element_count': elem_count,
        'node_count': node_count,
        'odb_element_count': odb_meta.get('element_count', elem_count),
        'odb_node_count': odb_meta.get('node_count', node_count),
        'tip_displacement_mm': tip_disp,
        'reaction_summary': reaction_summary,
        'reaction_report': reaction_report,
        'solver_completed': run.solver_completed,
        'mesh_quality_passed': (mesh_check.get('status') == 'pass') if isinstance(mesh_check, dict) else True,
        'odb_file_size': os.path.getsize(run.odb_path),
    }
    runs.append(run_entry)

# 4. Check progression across the 3 meshes
elem_counts = [r['element_count'] for r in runs]
displacements = [r['tip_displacement_mm'] for r in runs]
element_count_increases = (elem_counts[0] < elem_counts[1] < elem_counts[2])
all_odbs_exist = all(os.path.exists(r['odb_path']) and r['odb_file_size'] > 0 for r in runs)
all_solvers_completed = all(r['solver_completed'] for r in runs)

# 5. Richardson Extrapolation & Grid Convergence Index (GCI)
# Refinement ratio r = 5.0 / 2.5 = 2.5 / 1.25 = 2.0
refinement_ratio = 2.0
standard_tolerance = 0.10  # 10%% GCI tolerance

richardson_res = verify_richardson(
    name='tip_displacement',
    values=tuple(displacements),
    refinement_ratio=refinement_ratio,
    tolerance=standard_tolerance,
)

# 6. Evaluate Mesh Convergence Contract
points = tuple(
    MeshConvergencePoint(
        mesh_size=r['seed_size'],
        result_value=r['tip_displacement_mm'],
        quantity='tip_displacement',
        source=r['job_name'] + '.odb',
        quality_status='pass' if r['mesh_quality_passed'] else 'fail',
    )
    for r in runs
)
standard_policy = MeshConvergencePolicy(
    tolerance=0.05, minimum_points=3, relative=True, require_quality_pass=True
)
convergence_res = evaluate_mesh_convergence(points, standard_policy)

# 7. Standard Acceptance (Expected: PASS)
fine_run = runs[-1]
fine_quality_gate = MeshQualityResult(status='pass' if fine_run['mesh_quality_passed'] else 'fail')
standard_acceptance = evaluate_result_acceptance(
    result_status='completed' if all_solvers_completed else 'failed',
    numerical=richardson_res,
    convergence=convergence_res,
    engineering=fine_run['reaction_report'],
    mesh_quality=fine_quality_gate,
    values={'tip_displacement': fine_run['tip_displacement_mm']},
    criteria=criteria_template,
)

# 8. Strict Acceptance Gate (Expected: FAIL to prove gate sensitivity)
strict_richardson = verify_richardson(
    name='tip_displacement',
    values=tuple(displacements),
    refinement_ratio=refinement_ratio,
    tolerance=1e-6,
)
strict_policy = MeshConvergencePolicy(
    tolerance=1e-6, minimum_points=3, relative=True, require_quality_pass=True
)
strict_convergence = evaluate_mesh_convergence(points, strict_policy)
strict_acceptance = evaluate_result_acceptance(
    result_status='completed' if all_solvers_completed else 'failed',
    numerical=strict_richardson,
    convergence=strict_convergence,
    engineering=fine_run['reaction_report'],
    mesh_quality=fine_quality_gate,
    values={'tip_displacement': fine_run['tip_displacement_mm']},
    criteria=criteria_template,
)
strict_gate_fails_as_expected = (
    not strict_acceptance.passed
    and ('numerical_verification_failed' in strict_acceptance.failures
         or 'mesh_convergence_failed' in strict_acceptance.failures)
)

final_passed = (
    all_odbs_exist
    and all_solvers_completed
    and element_count_increases
    and richardson_res.passed
    and convergence_res.converged
    and standard_acceptance.passed
    and strict_gate_fails_as_expected
)

report = {
    'status': 'pass' if final_passed else 'fail',
    'model': {'length_mm': beam_l, 'width_mm': beam_b, 'height_mm': beam_h},
    'material': {'E_MPa': mat_e, 'nu': mat_nu},
    'load': {'Fy_N': applied_force},
    'theory': {
        'tip_displacement_mm': abs(applied_force) * beam_l ** 3 / (3.0 * mat_e * (beam_b * beam_h ** 3 / 12.0)),
        'root_bending_stress_MPa': abs(applied_force) * beam_l * (beam_h / 2.0) / (beam_b * beam_h ** 3 / 12.0),
    },
    'runs': runs,
    'checks': {
        'all_odbs_exist': all_odbs_exist,
        'all_solvers_completed': all_solvers_completed,
        'element_count_increases': element_count_increases,
        'richardson_uses_real_results': len(richardson_res.points) == 3,
        'strict_gate_fails_as_expected': strict_gate_fails_as_expected,
    },
    'numerical_verification': richardson_res,
    'mesh_convergence': convergence_res,
    'acceptance': {
        'standard': standard_acceptance,
        'strict': strict_acceptance,
    },
}

def _default(value):
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, 'value'):
        return value.value
    if isinstance(value, (tuple, set)):
        return list(value)
    raise TypeError('not JSON serializable: ' + repr(type(value)))

print('AIAgent_MESH_CONVERGENCE_RESULT_BEGIN')
print(json.dumps(report, default=_default, sort_keys=True))
print('AIAgent_MESH_CONVERGENCE_RESULT_END')
""" % (
        src_dir, MODEL, PART, INSTANCE, STEP, L, B, H, E, NU, FORCE,
        update_evidence_sets_code, geometry_code,
    )


def _extract_report(stdout):
    begin = 'AIAgent_MESH_CONVERGENCE_RESULT_BEGIN'
    end = 'AIAgent_MESH_CONVERGENCE_RESULT_END'
    if begin not in stdout or end not in stdout:
        return None
    payload = stdout.split(begin, 1)[1].split(end, 1)[0].strip()
    clean_lines = []
    for line in payload.splitlines():
        line = line.strip()
        if line.startswith('#:'):
            line = line[2:].strip()
        if line:
            clean_lines.append(line)
    return json.loads('\n'.join(clean_lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the Mesh Convergence E2E Case')
    parser.add_argument('--launcher', default=os.environ.get('ABAQUS_COMMAND', 'abaqus'))
    parser.add_argument('--workdir', default=os.getcwd())
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--output', default=os.path.join('machine_validation', 'mesh_convergence_e2e.json'))
    args = parser.parse_args(argv)

    workdir = os.path.abspath(args.workdir)
    validation_dir = os.path.join(workdir, 'machine_validation')
    os.makedirs(validation_dir, exist_ok=True)
    script_path = os.path.join(validation_dir, 'mesh_convergence_e2e_script.py')
    with open(script_path, 'w', encoding='utf-8') as handle:
        handle.write(build_mesh_convergence_script())

    evidence = {
        'status': 'fail',
        'launcher': args.launcher,
        'workdir': workdir,
        'script': os.path.abspath(script_path),
        'case': '3d_cantilever_mesh_convergence',
    }
    try:
        executor = BatchExecutor(
            launcher=args.launcher, workdir=workdir, timeout=args.timeout
        )
        process = executor.run_nogui(script_path, timeout=args.timeout)
        output_text = (process.stdout or '') + '\n' + (process.stderr or '')
        report = _extract_report(output_text)
        if not report:
            rpy_path = os.path.join(workdir, 'abaqus.rpy')
            if os.path.exists(rpy_path):
                with open(rpy_path, 'r', encoding='utf-8', errors='ignore') as handle:
                    report = _extract_report(handle.read())
        evidence.update({
            'command': list(process.command),
            'return_code': process.return_code,
            'process_succeeded': process.succeeded,
            'report': report,
            'stdout': process.stdout,
            'stderr': process.stderr,
        })
        evidence['status'] = (
            'pass'
            if process.succeeded and report and report.get('status') == 'pass'
            else 'fail'
        )
    except Exception as exc:
        evidence.update({
            'error_class': exc.__class__.__name__,
            'error_message': str(exc),
        })

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path(workdir) / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, default=str) + '\n',
        encoding='utf-8',
    )
    print(json.dumps({
        'status': evidence['status'],
        'return_code': evidence.get('return_code'),
        'evidence': str(output_path),
        'script': os.path.abspath(script_path),
    }, sort_keys=True))
    return 0 if evidence['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
