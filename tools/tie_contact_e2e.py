#!/usr/bin/env python3
"""Run the Contact / Tie E2E Engineering Case through the real Abaqus runtime.

This tool executes a two-body tied cantilever beam analysis using the project's
existing Action, AnalysisRunner, ODB extraction, engineering-evidence,
contact diagnostics, and acceptance components.

The physical model consists of two solid blocks tied at their interface (x = 50 mm):
  - Block 1: [0, 50] x [0, 10] x [0, 10] mm, fixed at x = 0
  - Block 2: [50, 100] x [0, 10] x [0, 10] mm, loaded at x = 100 (Fy = -1000 N)
  - Tie constraint: connects Block 1 face (x = 50) and Block 2 face (x = 50)

Verification verifies:
1. Two distinct assembly instances are created and tied via the native `tie` action.
2. Solver executes and completes successfully (Standard solver).
3. ODB is generated and readable.
4. Global reaction force balance at fixed boundary (x = 0): RFy = +1000 N (+-1%).
5. Tip deflection at x = 100 matches monolithic cantilever beam (~2.07 mm).
6. Interface kinematic continuity across tied surface: relative displacement delta_U ~ 0.
7. Stress sanity at the fixed root: Mises stress <= 1200 MPa.
8. Acceptance gate verifies reaction balance, interface continuity, and criteria.
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

MODEL = "TieContactModel"
PART1 = "Block1"
PART2 = "Block2"
INSTANCE1 = "Block1-1"
INSTANCE2 = "Block2-1"
JOB = "TieContactJob"
STEP = "Step-1"

L1 = 50.0
L2 = 50.0
TOTAL_L = 100.0
B = 10.0
H = 10.0
E = 210000.0
NU = 0.3
FORCE = -1000.0


def build_tie_contact_script(src_dir=None):
    src_dir = str(src_dir or SRC)

    geometry_code = r"""
from abaqus import mdb
from abaqusConstants import THREE_D, DEFORMABLE_BODY, ON, CARTESIAN
import interaction

if %r in mdb.models:
    del mdb.models[%r]
model = mdb.Model(name=%r)

# Part 1: Block 1 [0, 50] x [0, 10] x [0, 10]
sk1 = model.ConstrainedSketch(name='Block1Profile', sheetSize=200.0)
sk1.rectangle(point1=(0.0, 0.0), point2=(%r, %r))
p1 = model.Part(name=%r, dimensionality=THREE_D, type=DEFORMABLE_BODY)
p1.BaseSolidExtrude(sketch=sk1, depth=%r)
del model.sketches['Block1Profile']

# Part 2: Block 2 [50, 100] x [0, 10] x [0, 10]
sk2 = model.ConstrainedSketch(name='Block2Profile', sheetSize=200.0)
sk2.rectangle(point1=(%r, 0.0), point2=(%r, %r))
p2 = model.Part(name=%r, dimensionality=THREE_D, type=DEFORMABLE_BODY)
p2.BaseSolidExtrude(sketch=sk2, depth=%r)
del model.sketches['Block2Profile']

p1.Set(name='AllCells', cells=p1.cells)
p2.Set(name='AllCells', cells=p2.cells)

# Assembly with two instances
assembly = model.rootAssembly
assembly.DatumCsysByDefault(CARTESIAN)
inst1 = assembly.Instance(name=%r, part=p1, dependent=ON)
inst2 = assembly.Instance(name=%r, part=p2, dependent=ON)

# Fixed face at x = 0 (Block 1)
fixed_face = inst1.faces.findAt(((0.0, %r, %r),))
assembly.Set(name='FixedFace', faces=fixed_face)

# Tip load vertices at x = 100 (Block 2)
tip_vertices = inst2.vertices.findAt(
    ((%r, 0.0, 0.0),),
    ((%r, %r, 0.0),),
    ((%r, 0.0, %r),),
    ((%r, %r, %r),),
)
assembly.Set(name='TipLoadVertices', vertices=tip_vertices)

# Interface surfaces at x = 50 for Tie interaction
master_face = inst1.faces.findAt(((%r, %r, %r),))
slave_face = inst2.faces.findAt(((%r, %r, %r),))
assembly.Surface(name='MasterFace', side1Faces=master_face)
assembly.Surface(name='SlaveFace', side1Faces=slave_face)

print('AIAgent_TIE_GEOMETRY_CREATED')
""" % (
        MODEL, MODEL, MODEL,
        L1, H, PART1, B,
        L1, TOTAL_L, H, PART2, B,
        INSTANCE1, INSTANCE2,
        H / 2.0, B / 2.0,
        TOTAL_L, TOTAL_L, H, TOTAL_L, B, TOTAL_L, H, B,
        L1, H / 2.0, B / 2.0,
        L1, H / 2.0, B / 2.0,
    )

    evidence_sets_code = r"""
from abaqusConstants import *
model = mdb.models[%r]
p1 = model.parts[%r]
p2 = model.parts[%r]
inst1 = model.rootAssembly.instances[%r]
inst2 = model.rootAssembly.instances[%r]
model.rootAssembly.regenerate()

# Fixed boundary node set at x = 0
fixed_nodes = inst1.nodes.getByBoundingBox(xMin=-0.01, xMax=0.01)
if not fixed_nodes:
    raise RuntimeError('FixedNodes set is empty')
model.rootAssembly.Set(name='FixedNodes', nodes=fixed_nodes)

# Tip load node set at x = 100
tip_nodes = inst2.nodes.getByBoundingBox(xMin=%r, xMax=%r)
if not tip_nodes:
    raise RuntimeError('TipNodes set is empty')
model.rootAssembly.Set(name='TipNodes', nodes=tip_nodes)

# Interface master nodes on Block 1 at x = 50
master_nodes = inst1.nodes.getByBoundingBox(xMin=%r, xMax=%r)
if not master_nodes:
    raise RuntimeError('InterfaceMasterNodes set is empty')
model.rootAssembly.Set(name='InterfaceMasterNodes', nodes=master_nodes)

# Interface slave nodes on Block 2 at x = 50
slave_nodes = inst2.nodes.getByBoundingBox(xMin=%r, xMax=%r)
if not slave_nodes:
    raise RuntimeError('InterfaceSlaveNodes set is empty')
model.rootAssembly.Set(name='InterfaceSlaveNodes', nodes=slave_nodes)

# Root elements for stress sanity check
root_elems = p1.elements.getByBoundingBox(xMin=-0.01, xMax=10.01)
if not root_elems:
    raise RuntimeError('RootElements set is empty')
p1.Set(name='RootElements', elements=root_elems)

print('AIAgent_TIE_EVIDENCE_SETS_CREATED')
""" % (
        MODEL, PART1, PART2, INSTANCE1, INSTANCE2,
        TOTAL_L - 0.01, TOTAL_L + 0.01,
        L1 - 0.01, L1 + 0.01,
        L1 - 0.01, L1 + 0.01,
    )

    return """
import sys
_src_dir = %r
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import ast
import io
import json
import os
from dataclasses import asdict, is_dataclass

from abaqus_ai_agent.actions.builders import (
    python_action, material_elastic, solid_section, section_assignment,
    static_step, fixed_bc, concentrated_force,
    seed_part, element_type, generate_mesh, mesh_quality,
    tie, create_job,
)
from abaqus_ai_agent.actions.runner import execute
from abaqus_ai_agent.execution.client import InProcessExecutor
from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
from abaqus_ai_agent.execution.odb import extract_field
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.contact import ContactDiagnostic, ContactDiagnosticReport
from abaqus_ai_agent.engineering_evidence import reaction_balance_from_field_evidence
from abaqus_ai_agent.acceptance import evaluate_result_acceptance

model_name = %r
part1_name = %r
part2_name = %r
instance1_name = %r
instance2_name = %r
job_name = %r
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
        exec(compile(code, '<AIAgent-TieContact>', 'exec'), globals(), globals())
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
        res = {
            'status': 'available',
            'steps': list(odb.steps.keys()),
            'instances': list(odb.rootAssembly.instances.keys()),
            'step_frames': {k: len(v.frames) for k, v in odb.steps.items()},
        }
        odb.close()
        return res

executor = CAEInProcessExecutor(_run_code)

# 1. Geometry & Assembly
geometry = python_action(model_name, %r)
execute(executor, geometry)

# 2. Materials, Sections, Interactions, Steps, BCs, Loads, Meshing
actions = [
    material_elastic(model_name, 'Steel', youngs_modulus=mat_e, poisson=mat_nu),
    solid_section(model_name, 'SolidSection', material='Steel'),
    section_assignment(
        model_name, part1_name, 'SolidSection',
        "mdb.models['" + model_name + "'].parts['" + part1_name + "'].sets['AllCells']",
    ),
    section_assignment(
        model_name, part2_name, 'SolidSection',
        "mdb.models['" + model_name + "'].parts['" + part2_name + "'].sets['AllCells']",
    ),
    # Native Tie action
    tie(
        model_name, 'Tie-1',
        "mdb.models['" + model_name + "'].rootAssembly.surfaces['MasterFace']",
        "mdb.models['" + model_name + "'].rootAssembly.surfaces['SlaveFace']",
    ),
    fixed_bc(
        model_name, 'FixedBC',
        "mdb.models['" + model_name + "'].rootAssembly.sets['FixedFace']",
        step='Initial',
    ),
    static_step(model_name, step_name),
    concentrated_force(
        model_name, 'TipLoad',
        "mdb.models['" + model_name + "'].rootAssembly.sets['TipLoadVertices']",
        cf2=applied_force / 4.0,
        step=step_name,
    ),
    seed_part(model_name, part1_name, 2.5),
    seed_part(model_name, part2_name, 2.5),
    element_type(
        model_name, part1_name,
        "mdb.models['" + model_name + "'].parts['" + part1_name + "'].sets['AllCells']",
        elem_code='C3D8R', library='STANDARD',
    ),
    element_type(
        model_name, part2_name,
        "mdb.models['" + model_name + "'].parts['" + part2_name + "'].sets['AllCells']",
        elem_code='C3D8R', library='STANDARD',
    ),
    generate_mesh(model_name, part1_name),
    generate_mesh(model_name, part2_name),
    python_action(model_name, %r),
    create_job(model_name, job_name),
]

for action in actions:
    execute(executor, action)

mesh_result1 = execute(executor, mesh_quality(
    model_name, part1_name,
    max_aspect_ratio=5.0,
    max_angular_deviation=20.0,
    max_geometric_deviation_factor=0.1,
    analysis_checks=True,
))
mesh_result2 = execute(executor, mesh_quality(
    model_name, part2_name,
    max_aspect_ratio=5.0,
    max_angular_deviation=20.0,
    max_geometric_deviation_factor=0.1,
    analysis_checks=True,
))

runner_criteria = (
    {
        'name': 'tip_displacement_lower',
        'value_key': 'max_displacement',
        'operator': '>=',
        'limit': 1.60,
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
    {
        'name': 'tip_displacement_upper',
        'value_key': 'max_displacement_upper',
        'operator': '<=',
        'limit': 2.20,
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
    {
        'name': 'root_mises_sanity',
        'value_key': 'root_mises',
        'operator': '<=',
        'limit': 1200.0,
        'unit': 'MPa',
        'result': {
            'field': 'S',
            'invariant': 'MISES',
            'aggregation': 'max',
            'step': step_name,
            'frame': -1,
            'region': "odb.rootAssembly.instances['" + instance1_name.upper() + "'].elementSets['ROOTELEMENTS']",
        },
    },
)

final_criteria = runner_criteria + (
    {
        'name': 'interface_displacement_continuity',
        'value_key': 'interface_max_diff',
        'operator': '<=',
        'limit': 0.01,
        'unit': 'mm',
    },
)

odb_expected_path = os.path.abspath(job_name + '.odb')

run = AnalysisRunner(executor).run(
    model_name=model_name,
    job_name=job_name,
    odb_path=odb_expected_path,
    criteria=runner_criteria,
    timeout=3600,
    action_plan=tuple(actions),
    engineering_intent=EngineeringIntent(
        id='tie-contact-e2e',
        kind='tied_cantilever_static',
        description='Two solid blocks tied at interface under tip transverse load',
        analysis_type='static',
        loads=('concentrated_force',),
        metadata={'solver': 'standard', 'interaction': 'tie'},
    ),
)

if not run.odb_path:
    raise RuntimeError('Tie Contact E2E Case did not produce an ODB path: state=' + str(run.state) + ', status=' + str(run.job_status) + ', diag=' + repr(run.diagnostics))

# 1. Reaction force balance on fixed nodes (x = 0)
reaction_field = extract_field(
    executor,
    run.odb_path,
    step_name,
    'RF',
    frame=-1,
    region="odb.rootAssembly.nodeSets['FIXEDNODES']",
)

reaction_report, reaction_summary = reaction_balance_from_field_evidence(
    {
        'status': 'available',
        'values': reaction_field.get('values', []),
    },
    applied_components=(0.0, applied_force, 0.0),
    tolerance=0.01,
    unit='N',
)

# 2. Interface kinematic continuity across tied surface (x = 50)
u_master_field = extract_field(
    executor,
    run.odb_path,
    step_name,
    'U',
    frame=-1,
    region="odb.rootAssembly.nodeSets['INTERFACEMASTERNODES']",
)
u_slave_field = extract_field(
    executor,
    run.odb_path,
    step_name,
    'U',
    frame=-1,
    region="odb.rootAssembly.nodeSets['INTERFACESLAVENODES']",
)

master_nodes_disp = {}
for item in u_master_field.get('values', []):
    coords = item.get('coordinates')
    if coords is not None and len(coords) == 3:
        key = (round(coords[1], 2), round(coords[2], 2))
        master_nodes_disp[key] = item.get('data')

slave_nodes_disp = {}
for item in u_slave_field.get('values', []):
    coords = item.get('coordinates')
    if coords is not None and len(coords) == 3:
        key = (round(coords[1], 2), round(coords[2], 2))
        slave_nodes_disp[key] = item.get('data')

matched_coords = [k for k in master_nodes_disp if k in slave_nodes_disp]
interface_diffs = []
for k in matched_coords:
    m_disp = master_nodes_disp[k]
    s_disp = slave_nodes_disp[k]
    if m_disp and s_disp and len(m_disp) == 3 and len(s_disp) == 3:
        diff = sum([(m_disp[i] - s_disp[i]) ** 2 for i in range(3)]) ** 0.5
        interface_diffs.append(diff)

max_interface_diff = max(interface_diffs) if interface_diffs else None
mean_interface_diff = sum(interface_diffs) / len(interface_diffs) if interface_diffs else None

contact_diag = ContactDiagnostic(
    name='interface_kinematic_continuity',
    status='pass' if (max_interface_diff is not None and max_interface_diff <= 0.01) else 'fail',
    value=max_interface_diff,
    limit=0.01,
    unit='mm',
    message='Tie constraint kinematic relative displacement <= 0.01 mm',
)
contact_report = ContactDiagnosticReport(diagnostics=(contact_diag,))

# 3. Final Acceptance Gate
result_values = {}
for item in run.metrics:
    metadata = getattr(item, 'metadata', {}) or {}
    key = metadata.get('value_key')
    value = getattr(item, 'value', None)
    if key and isinstance(value, (int, float)):
        result_values[key] = value

if max_interface_diff is not None:
    result_values['interface_max_diff'] = max_interface_diff

final_acceptance = evaluate_result_acceptance(
    result_status=run.job_status.state.value.lower() if run.job_status else 'unknown',
    engineering=reaction_report,
    contact_diagnostics=contact_report,
    values=result_values,
    criteria=final_criteria,
)

theory_tip_disp = abs(applied_force) * beam_l ** 3 / (3.0 * mat_e * (beam_b * beam_h ** 3 / 12.0))
theory_bending_stress = abs(applied_force) * beam_l * (beam_h / 2.0) / (beam_b * beam_h ** 3 / 12.0)

report = {
    'status': 'pass' if (
        run.solver_completed
        and run.odb_path
        and reaction_report.passed
        and contact_report.passed
        and final_acceptance.passed
    ) else 'fail',
    'model': {
        'block1_length_mm': beam_l / 2.0,
        'block2_length_mm': beam_l / 2.0,
        'total_length_mm': beam_l,
        'width_mm': beam_b,
        'height_mm': beam_h,
    },
    'material': {'E_MPa': mat_e, 'nu': mat_nu},
    'load': {'Fy_N': applied_force},
    'theory': {
        'tip_displacement_mm': theory_tip_disp,
        'root_bending_stress_MPa': theory_bending_stress,
    },
    'workflow': {
        'action_count': len(actions),
        'solver_completed': run.solver_completed,
        'state': run.state.value,
    },
    'solver': {
        'job_status': run.job_status,
        'odb_path': run.odb_path,
        'artifacts': run.artifacts,
        'diagnostics': run.diagnostics,
    },
    'results': {
        'metrics': run.metrics,
        'evidence': run.evidence,
        'tip_displacement_max': result_values.get('max_displacement'),
        'root_mises': result_values.get('root_mises'),
    },
    'tie_verification': {
        'matched_interface_nodes': len(matched_coords),
        'max_interface_relative_displacement_mm': max_interface_diff,
        'mean_interface_relative_displacement_mm': mean_interface_diff,
        'contact_diagnostic': contact_diag,
        'contact_report': contact_report,
    },
    'engineering_checks': {
        'reaction_summary': reaction_summary,
        'reaction_report': reaction_report,
        'mesh_result_block1': mesh_result1,
        'mesh_result_block2': mesh_result2,
    },
    'acceptance': final_acceptance,
    'provenance': run.provenance,
}

def _default(value):
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, 'value'):
        return value.value
    if isinstance(value, tuple):
        return list(value)
    raise TypeError('not JSON serializable: ' + repr(type(value)))

print('AIAgent_TIE_CONTACT_RESULT_BEGIN')
print(json.dumps(report, default=_default, sort_keys=True))
print('AIAgent_TIE_CONTACT_RESULT_END')
""" % (
        src_dir,
        MODEL, PART1, PART2, INSTANCE1, INSTANCE2, JOB, STEP,
        TOTAL_L, B, H, E, NU, FORCE,
        geometry_code,
        evidence_sets_code,
    )


def _extract_report(stdout):
    begin = 'AIAgent_TIE_CONTACT_RESULT_BEGIN'
    end = 'AIAgent_TIE_CONTACT_RESULT_END'
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
    parser = argparse.ArgumentParser(description='Run the Contact / Tie E2E Engineering Case')
    parser.add_argument('--launcher', default=os.environ.get('ABAQUS_COMMAND', 'abaqus'))
    parser.add_argument(
        '--workdir',
        default=os.path.join(str(ROOT), 'runs', 'tie_contact_run'),
    )
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument(
        '--output',
        default=os.path.join(str(ROOT), 'machine_validation', 'tie_contact_e2e.json'),
    )
    args = parser.parse_args(argv)

    workdir = os.path.abspath(args.workdir)
    os.makedirs(workdir, exist_ok=True)
    script_path = os.path.join(workdir, 'tie_contact_e2e_script.py')
    with open(script_path, 'w', encoding='utf-8') as handle:
        handle.write(build_tie_contact_script())

    evidence = {
        'status': 'fail',
        'launcher': args.launcher,
        'workdir': workdir,
        'script': os.path.abspath(script_path),
        'case': 'two_block_tied_cantilever_static',
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
        output_path = ROOT / output_path
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
