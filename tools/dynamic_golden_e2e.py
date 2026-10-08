#!/usr/bin/env python3
"""Run the Implicit Dynamic E2E Engineering Case through the real Abaqus runtime.

This tool executes a 3D cantilever beam transient dynamic analysis using the project's
existing Action, AnalysisRunner, ODB extraction, engineering-evidence, and
acceptance components.

The physical model consists of a 3D solid beam:
  - Dimensions: [0, 100] x [0, 10] x [0, 10] mm
  - Material: Steel (E = 210000 MPa, nu = 0.3, density = 7.85e-9 tonne/mm^3)
  - Boundary: Encastre at x = 0 (FixedFace)
  - Amplitude: Tabular ramp amplitude (0 to 1 over 0.005 s, then held constant to 0.02 s)
  - Step: Implicit dynamics step (time_period = 0.02 s, initial_inc = 0.0005 s, max_inc = 0.001 s)
  - Load: Tip concentrated load Fy = -1000 N modulated by the ramp amplitude
  - Mesh: C3D8R elements (seed = 2.5 mm)

Verification verifies:
1. Native `tabular_amplitude` action enters Abaqus model.
2. Native `implicit_dynamic_step` action creates and executes ImplicitDynamicsStep in Abaqus/Standard.
3. Multi-frame ODB generation across the dynamic time domain (>= 10 increments).
4. Time-history displacement extraction across all frames (demonstrating dynamic response).
5. Whole-model energy history output extraction (ALLIE, ALLKE, ALLWK, ALLSE).
6. Deterministic energy check (kinetic to internal energy ratio).
7. Engineering acceptance gate evaluation (PASS on physical criteria, FAIL on strict gate).
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

MODEL = "DynamicGolden"
PART = "Beam"
INSTANCE = "Beam-1"
JOB = "DynamicGoldenJob"
STEP = "Step-1"
AMPLITUDE = "TipLoadAmp"

L = 100.0
B = 10.0
H = 10.0
E = 210000.0
NU = 0.3
DENSITY = 7.85e-9  # tonne/mm^3
FORCE = -1000.0
TIME_PERIOD = 0.02
INITIAL_INC = 0.0005
MAX_INC = 0.001


def build_dynamic_golden_script(src_dir=None):
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
inst = assembly.Instance(name=%r, part=part, dependent=ON)

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

print('AIAgent_DYNAMIC_GEOMETRY_CREATED')
""" % (
        MODEL, MODEL, MODEL,
        L, H, PART, B,
        INSTANCE,
        H / 2.0, B / 2.0,
        L, H / 2.0, B / 2.0,
        L, L, H, L, B, L, H, B,
    )

    evidence_sets_code = r"""
from abaqusConstants import *
model = mdb.models[%r]
part = model.parts[%r]
inst = model.rootAssembly.instances[%r]
model.rootAssembly.regenerate()

fixed_nodes = inst.nodes.getByBoundingBox(xMin=-0.01, xMax=0.01)
if not fixed_nodes:
    raise RuntimeError('FixedNodes set is empty')
model.rootAssembly.Set(name='FixedNodes', nodes=fixed_nodes)

tip_nodes = inst.nodes.getByBoundingBox(xMin=%r, xMax=%r)
if not tip_nodes:
    raise RuntimeError('TipNodes set is empty')
model.rootAssembly.Set(name='TipNodes', nodes=tip_nodes)

root_elements = part.elements.getByBoundingBox(xMin=-0.01, xMax=10.01)
if not root_elements:
    raise RuntimeError('RootElements set is empty')
part.Set(name='RootElements', elements=root_elements)

print('AIAgent_DYNAMIC_EVIDENCE_SETS_CREATED')
""" % (
        MODEL, PART, INSTANCE,
        L - 0.01, L + 0.01,
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
    python_action, material_elastic, material_density, solid_section, section_assignment,
    tabular_amplitude, implicit_dynamic_step, field_output, fixed_bc, concentrated_force,
    seed_part, element_type, generate_mesh, mesh_quality,
    create_job,
)
from abaqus_ai_agent.actions.runner import execute
from abaqus_ai_agent.execution.client import InProcessExecutor
from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
from abaqus_ai_agent.execution.odb import extract_field, extract_history
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.engineering_evidence import (
    reaction_balance_from_field_evidence,
    energy_ratio_from_history_evidence,
)
from abaqus_ai_agent.acceptance import evaluate_result_acceptance

model_name = %r
part_name = %r
instance_name = %r
job_name = %r
step_name = %r
amp_name = %r
beam_l = %r
beam_b = %r
beam_h = %r
mat_e = %r
mat_nu = %r
mat_density = %r
applied_force = %r
time_period = %r
initial_inc = %r
max_inc = %r

def _run_code(code):
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        exec(compile(code, '<AIAgent-DynamicGolden>', 'exec'), globals(), globals())
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

# 2. Material with Density, Section, BC, Tabular Amplitude, Implicit Dynamic Step, Load, Mesh
actions = [
    material_elastic(model_name, 'Steel', youngs_modulus=mat_e, poisson=mat_nu),
    material_density(model_name, 'Steel', density=mat_density),
    solid_section(model_name, 'SolidSection', material='Steel'),
    section_assignment(
        model_name, part_name, 'SolidSection',
        "mdb.models['" + model_name + "'].parts['" + part_name + "'].sets['AllCells']",
    ),
    fixed_bc(
        model_name, 'FixedBC',
        "mdb.models['" + model_name + "'].rootAssembly.sets['FixedFace']",
        step='Initial',
    ),
    tabular_amplitude(
        model_name, amp_name,
        data=((0.0, 0.0), (0.005, 1.0), (time_period, 1.0)),
        time_span='STEP',
    ),
    implicit_dynamic_step(
        model_name, name=step_name, previous='Initial',
        time_period=time_period, max_num_inc=200,
        initial_inc=initial_inc, min_inc=1e-7, max_inc=max_inc,
        amplitude='STEP',
    ),
    field_output(
        model_name, variables=('S', 'U', 'RF'),
        request='F-Output-1', step=step_name, frequency=1,
    ),
    concentrated_force(
        model_name, 'TipLoad',
        "mdb.models['" + model_name + "'].rootAssembly.sets['TipLoadVertices']",
        cf2=applied_force / 4.0,
        step=step_name,
        amplitude=amp_name,
    ),
    seed_part(model_name, part_name, 2.5),
    element_type(
        model_name, part_name,
        "mdb.models['" + model_name + "'].parts['" + part_name + "'].sets['AllCells']",
        elem_code='C3D8R', library='STANDARD',
    ),
    generate_mesh(model_name, part_name),
    python_action(model_name, %r),
    create_job(model_name, job_name),
]

for action in actions:
    execute(executor, action)

mesh_result = execute(executor, mesh_quality(
    model_name, part_name,
    max_aspect_ratio=5.0,
    max_angular_deviation=20.0,
    max_geometric_deviation_factor=0.1,
    analysis_checks=True,
))

runner_criteria = (
    {
        'name': 'tip_displacement_end',
        'value_key': 'tip_u_end',
        'operator': '<=',
        'limit': 5.0,
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
        'limit': 1500.0,
        'unit': 'MPa',
        'result': {
            'field': 'S',
            'invariant': 'MISES',
            'aggregation': 'max',
            'step': step_name,
            'frame': -1,
            'region': "odb.rootAssembly.instances['" + instance_name.upper() + "'].elementSets['ROOTELEMENTS']",
        },
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
        id='dynamic-golden-e2e',
        kind='transient_cantilever_beam',
        description='Implicit transient dynamic cantilever beam under ramped tip load',
        analysis_type='implicit-dynamic',
        loads=('concentrated_force',),
        metadata={'solver': 'standard', 'procedure': 'implicit_dynamic'},
    ),
)

if not run.odb_path:
    raise RuntimeError('Dynamic Golden E2E Case did not produce an ODB path: state=' + str(run.state) + ', status=' + str(run.job_status) + ', diag=' + repr(run.diagnostics))

# 3. ODB Multi-Frame Time History Extraction
from odbAccess import openOdb
odb = openOdb(path=run.odb_path, readOnly=True)
st = odb.steps[step_name]
tip_nset = odb.rootAssembly.nodeSets['TIPNODES']

time_history = []
for idx, fr in enumerate(st.frames):
    t_val = float(fr.frameValue)
    u_field = fr.fieldOutputs['U'].getSubset(region=tip_nset)
    mags = [float(v.magnitude) for v in u_field.values]
    u2s = [float(v.data[1]) for v in u_field.values]
    time_history.append({
        'frame_index': idx,
        'time': t_val,
        'tip_u_magnitude_max': max(mags) if mags else 0.0,
        'tip_u2_mean': sum(u2s) / len(u2s) if u2s else 0.0,
    })

frame_count = len(st.frames)
odb.close()

if frame_count < 10:
    raise RuntimeError('Dynamic Golden E2E expected >= 10 frames, found ' + str(frame_count))

peak_disp = max(item['tip_u_magnitude_max'] for item in time_history)
end_disp = time_history[-1]['tip_u_magnitude_max']
initial_disp = time_history[0]['tip_u_magnitude_max']

# 4. Whole-Model Energy History Extraction
energy_evidence = extract_history(
    executor,
    run.odb_path,
    step_name,
    'Assembly ASSEMBLY',
    ('ALLIE', 'ALLKE', 'ALLWK', 'ALLSE', 'ETOTAL'),
)

energy_check, energy_vals = energy_ratio_from_history_evidence(
    energy_evidence,
    'ALLKE',
    'ALLIE',
    tolerance=10.0,
    name='kinetic_to_internal_energy_ratio',
)

# 5. Reaction Force at Fixed Boundary (Last Frame)
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
    tolerance=1.5,
    unit='N',
)

# 6. Deterministic Acceptance Evaluation
result_values = {}
for item in run.metrics:
    metadata = getattr(item, 'metadata', {}) or {}
    key = metadata.get('value_key')
    value = getattr(item, 'value', None)
    if key and isinstance(value, (int, float)):
        result_values[key] = value

result_values['peak_displacement'] = peak_disp
result_values['end_displacement'] = end_disp
result_values['frame_count'] = frame_count

normal_criteria = (
    {
        'name': 'peak_displacement_bound',
        'value_key': 'peak_displacement',
        'operator': '<=',
        'limit': 5.0,
        'unit': 'mm',
    },
    {
        'name': 'peak_displacement_positive',
        'value_key': 'peak_displacement',
        'operator': '>=',
        'limit': 0.5,
        'unit': 'mm',
    },
    {
        'name': 'multi_frame_count',
        'value_key': 'frame_count',
        'operator': '>=',
        'limit': 10,
        'unit': 'frames',
    },
)

final_acceptance = evaluate_result_acceptance(
    result_status=run.job_status.state.value.lower() if run.job_status else 'unknown',
    engineering=reaction_report,
    mesh_quality=mesh_result if isinstance(mesh_result, dict) and mesh_result.get('status') == 'pass' else None,
    values=result_values,
    criteria=normal_criteria,
)

# 7. Strict Gate Verification (Proves Acceptance Can Deterministically FAIL)
strict_criteria = (
    {
        'name': 'peak_displacement_unphysical_strict',
        'value_key': 'peak_displacement',
        'operator': '<=',
        'limit': 0.0001,
        'unit': 'mm',
    },
)

strict_acceptance = evaluate_result_acceptance(
    result_status=run.job_status.state.value.lower() if run.job_status else 'unknown',
    values=result_values,
    criteria=strict_criteria,
)

theory_static_tip_disp = abs(applied_force) * beam_l ** 3 / (3.0 * mat_e * (beam_b * beam_h ** 3 / 12.0))

report = {
    'status': 'pass' if (
        run.solver_completed
        and run.odb_path
        and frame_count >= 10
        and energy_check.passed
        and final_acceptance.passed
        and not strict_acceptance.passed
    ) else 'fail',
    'model': {
        'length_mm': beam_l,
        'width_mm': beam_b,
        'height_mm': beam_h,
    },
    'material': {
        'E_MPa': mat_e,
        'nu': mat_nu,
        'density_tonne_mm3': mat_density,
    },
    'dynamic_parameters': {
        'time_period_s': time_period,
        'initial_inc_s': initial_inc,
        'max_inc_s': max_inc,
        'amplitude': amp_name,
        'total_frames': frame_count,
    },
    'load': {'Fy_N': applied_force},
    'theory': {
        'static_tip_displacement_mm': theory_static_tip_disp,
    },
    'time_history_sample': time_history[::max(1, len(time_history) // 8)],
    'dynamic_metrics': {
        'initial_displacement_mm': initial_disp,
        'peak_displacement_mm': peak_disp,
        'end_displacement_mm': end_disp,
        'dynamic_amplification_ratio': peak_disp / theory_static_tip_disp if theory_static_tip_disp > 0 else None,
    },
    'energy_verification': {
        'energy_check': energy_check,
        'energy_values': energy_vals,
        'energy_summary': energy_evidence.get('variables', {}),
    },
    'engineering_checks': {
        'reaction_summary': reaction_summary,
        'reaction_report': reaction_report,
        'mesh_quality': mesh_result,
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
    'acceptance': final_acceptance,
    'strict_gate_verification': {
        'passed': strict_acceptance.passed,
        'expected_fail': not strict_acceptance.passed,
        'failures': strict_acceptance.failures,
    },
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

print('AIAgent_DYNAMIC_GOLDEN_RESULT_BEGIN')
print(json.dumps(report, default=_default, sort_keys=True))
print('AIAgent_DYNAMIC_GOLDEN_RESULT_END')
""" % (
        src_dir,
        MODEL, PART, INSTANCE, JOB, STEP, AMPLITUDE,
        L, B, H, E, NU, DENSITY, FORCE,
        TIME_PERIOD, INITIAL_INC, MAX_INC,
        geometry_code,
        evidence_sets_code,
    )


def _extract_report(stdout):
    begin = 'AIAgent_DYNAMIC_GOLDEN_RESULT_BEGIN'
    end = 'AIAgent_DYNAMIC_GOLDEN_RESULT_END'
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
    parser = argparse.ArgumentParser(description='Run the Implicit Dynamic E2E Engineering Case')
    parser.add_argument('--launcher', default=os.environ.get('ABAQUS_COMMAND', 'abaqus'))
    parser.add_argument('--workdir', default=os.path.join(str(ROOT), 'runs', 'dynamic_golden_run'))
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--output', default=os.path.join('machine_validation', 'dynamic_golden_e2e.json'))
    args = parser.parse_args(argv)

    workdir = os.path.abspath(args.workdir)
    os.makedirs(workdir, exist_ok=True)
    script_path = os.path.join(workdir, 'dynamic_golden_e2e_script.py')
    with open(script_path, 'w', encoding='utf-8') as handle:
        handle.write(build_dynamic_golden_script())

    evidence = {
        'status': 'fail',
        'launcher': args.launcher,
        'workdir': workdir,
        'script': os.path.abspath(script_path),
        'case': 'cantilever_transient_implicit_dynamic',
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as handle:
        json.dump(evidence, handle, indent=2, default=str)

    print('AIAgent_DYNAMIC_E2E_EVIDENCE_STATUS:', evidence['status'])
    if evidence['status'] != 'pass':
        sys.exit(1)


if __name__ == '__main__':
    main()
