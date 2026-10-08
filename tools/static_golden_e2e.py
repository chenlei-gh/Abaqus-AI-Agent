#!/usr/bin/env python3
"""Run the Static Engineering Golden Case through the real Abaqus runtime.

The host side only launches Abaqus. The CAE-side script uses the project's
existing Action, AnalysisRunner, ODB extraction, engineering-evidence, and
acceptance components so the test exercises the production path rather than a
parallel demo implementation.
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


MODEL = "StaticGolden"
PART = "Beam"
INSTANCE = "Beam-1"
JOB = "StaticGoldenJob"
STEP = "Step-1"

L = 100.0
B = 10.0
H = 10.0
E = 210000.0
NU = 0.3
FORCE = -1000.0


def build_static_golden_script(src_dir=None):
    src_dir = str(src_dir or SRC)
    # Keep the model construction inside an explicit python_action. All
    # subsequent mutations are normal AbaqusAction objects.
    geometry_code = r"""
from abaqus import mdb
from abaqusConstants import THREE_D, DEFORMABLE_BODY, ON, OFF, CARTESIAN

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

# A symmetric four-vertex CLOAD avoids an off-axis point load while retaining
# the native ConcentratedForce action and its explicit resultant.
tip_vertices = inst.vertices.findAt(
    ((%r, 0.0, 0.0),),
    ((%r, %r, 0.0),),
    ((%r, 0.0, %r),),
    ((%r, %r, %r),),
)
assembly.Set(name='TipLoadVertices', vertices=tip_vertices)

# Whole-cell set is used by the section-assignment action.
part.Set(name='AllCells', cells=part.cells)

print('AIAgent_STATIC_GEOMETRY_CREATED')
""" % (
    MODEL, MODEL, MODEL, L, H, PART, B, INSTANCE, INSTANCE,
    H / 2.0, B / 2.0, L, H / 2.0, B / 2.0,
    L, L, H, L, B, L, H, B,
)

    evidence_sets_code = r"""
from abaqusConstants import *
model=mdb.models['StaticGolden']
part=model.parts['Beam']
inst=model.rootAssembly.instances['Beam-1']
model.rootAssembly.regenerate()

# Evidence sets are mesh-based so ODB field extraction receives true node/element sets.
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

tip_rp = model.rootAssembly.referencePoints
# The four-vertex CLOAD is applied symmetrically; no separate RP is needed.
print('AIAgent_STATIC_EVIDENCE_SETS_CREATED')
"""

    # This is intentionally assembled from the project's Action builders.
    # The CAE-side script imports them after Abaqus starts.
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
    python_action, section_assignment, seed_part, element_type,
    generate_mesh, mesh_quality,
)
from abaqus_ai_agent.actions.runner import execute
from abaqus_ai_agent.workflow.static import build_static_plan
from abaqus_ai_agent.execution.client import InProcessExecutor
from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
from abaqus_ai_agent.execution.odb import extract_field
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.engineering_evidence import reaction_balance_from_field_evidence
from abaqus_ai_agent.acceptance import evaluate_result_acceptance

model_name=%r
part_name=%r
instance_name=%r
job_name=%r
step_name=%r
beam_l=%r
beam_b=%r
beam_h=%r
mat_e=%r
mat_nu=%r
applied_force=%r

def _run_code(code):
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        exec(compile(code, '<AIAgent-StaticGolden>', 'exec'), globals(), globals())
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

geometry = python_action(model_name, %r)
execute(executor, geometry)

plan = build_static_plan(
    model_name,
    {'name': 'Steel', 'youngs_modulus': mat_e, 'poisson': mat_nu},
    {
        'section': 'BeamSection',
        'fixed': "mdb.models['StaticGolden'].rootAssembly.sets['FixedFace']",
        'load': "mdb.models['StaticGolden'].rootAssembly.sets['TipLoadVertices']",
    },
    force={'cf2': applied_force / 4.0},
    job_name=job_name,
    step_name=step_name,
)

actions = list(plan.actions[:-1])
actions.insert(3, section_assignment(
    model_name, part_name, 'BeamSection',
    "mdb.models['StaticGolden'].parts['Beam'].sets['AllCells']",
))
actions.extend([
    seed_part(model_name, part_name, 2.5),
    element_type(
        model_name, part_name,
        "mdb.models['StaticGolden'].parts['Beam'].sets['AllCells']",
        elem_code='C3D8R', library='STANDARD',
    ),
    generate_mesh(model_name, part_name),
    python_action(model_name, %r),
    plan.actions[-1],
])

for action in actions:
    execute(executor, action)

# Native mesh verifier is executed through the existing action path. Its result
# is recorded, but this Golden Case does not invent a new mesh-quality gate.
mesh_result = execute(executor, mesh_quality(
    model_name, part_name,
    max_aspect_ratio=5.0,
    max_angular_deviation=20.0,
    max_geometric_deviation_factor=0.1,
    analysis_checks=True,
))

criteria = (
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
            'region': "odb.rootAssembly.instances['BEAM-1'].elementSets['ROOTELEMENTS']",
        },
    },
)

odb_expected_path = os.path.abspath(job_name + '.odb')

run = AnalysisRunner(executor).run(
    model_name=model_name,
    job_name=job_name,
    odb_path=odb_expected_path,
    criteria=criteria,
    timeout=3600,
    action_plan=tuple(actions),
    engineering_intent=EngineeringIntent(
        id='static-golden',
        kind='linear_static_cantilever',
        description='3D cantilever beam under a symmetric tip transverse load',
        analysis_type='static',
        loads=('concentrated_force',),
        metadata={'solver': 'standard'},
    ),
)

if not run.odb_path:
    raise RuntimeError('Golden Case did not produce an ODB path')

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

# Final acceptance is intentionally evaluated again after the real RF evidence
# exists. AnalysisRunner already performed deterministic ODB-backed criteria
# acceptance; this second call closes the engineering-check gate without adding
# a new orchestration service.
result_values = {}
for item in run.metrics:
    metadata = getattr(item, 'metadata', {}) or {}
    key = metadata.get('value_key')
    value = getattr(item, 'value', None)
    if key and isinstance(value, (int, float)):
        result_values[key] = value

final_acceptance = evaluate_result_acceptance(
    result_status=run.job_status.state.value.lower() if run.job_status else 'unknown',
    engineering=reaction_report,
    values=result_values,
    criteria=criteria,
)

report = {
    'status': 'pass' if (
        run.solver_completed
        and run.odb_path
        and reaction_report.passed
        and final_acceptance.passed
    ) else 'fail',
    'model': {'length_mm': beam_l, 'width_mm': beam_b, 'height_mm': beam_h},
    'material': {'E_MPa': mat_e, 'nu': mat_nu},
    'load': {'Fy_N': applied_force},
    'theory': {
        'tip_displacement_mm': abs(applied_force) * beam_l ** 3 / (3.0 * mat_e * (beam_b * beam_h ** 3 / 12.0)),
        'root_bending_stress_MPa': abs(applied_force) * beam_l * (beam_h / 2.0) / (beam_b * beam_h ** 3 / 12.0),
    },
    'workflow': {
        'static_plan_actions': len(plan.actions),
        'action_count': len(actions),
        'solver_completed': run.solver_completed,
        'state': run.state.value,
        'engineering_status_before_rf_gate': run.engineering_status,
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
    },
    'engineering_checks': {
        'reaction_summary': reaction_summary,
        'reaction_report': reaction_report,
        'mesh_result': mesh_result,
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

print('AIAgent_STATIC_GOLDEN_RESULT_BEGIN')
print(json.dumps(report, default=_default, sort_keys=True))
print('AIAgent_STATIC_GOLDEN_RESULT_END')
""" % (
        src_dir, MODEL, PART, INSTANCE, JOB, STEP, L, B, H, E, NU, FORCE, geometry_code, evidence_sets_code
    )


def _extract_report(stdout):
    begin = 'AIAgent_STATIC_GOLDEN_RESULT_BEGIN'
    end = 'AIAgent_STATIC_GOLDEN_RESULT_END'
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
    parser = argparse.ArgumentParser(description='Run the Static Engineering Golden Case')
    parser.add_argument('--launcher', default=os.environ.get('ABAQUS_COMMAND', 'abaqus'))
    parser.add_argument(
        '--workdir',
        default=os.path.join(str(ROOT), 'runs', 'static_golden_run'),
    )
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument(
        '--output',
        default=os.path.join(str(ROOT), 'machine_validation', 'static_golden_e2e.json'),
    )
    args = parser.parse_args(argv)

    workdir = os.path.abspath(args.workdir)
    os.makedirs(workdir, exist_ok=True)
    script_path = os.path.join(workdir, 'static_golden_e2e_script.py')
    with open(script_path, 'w', encoding='utf-8') as handle:
        handle.write(build_static_golden_script())

    evidence = {
        'status': 'fail',
        'launcher': args.launcher,
        'workdir': workdir,
        'script': os.path.abspath(script_path),
        'case': '3d_cantilever_static',
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
