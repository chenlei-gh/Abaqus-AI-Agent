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


def build_static_golden_script():
    # Keep the model construction inside an explicit python_action. All
    # subsequent mutations are normal AbaqusAction objects.
    geometry_code = r"""
from abaqus import mdb
from abaqusConstants import THREE_D, DEFORMABLE_BODY, ON, OFF
from sketch import ConstrainedSketch

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
        B / 2.0, H / 2.0, L, B / 2.0, H / 2.0,
        L, L, B, L, 0.0, H, L, B, H,
    )

    # This is intentionally assembled from the project's Action builders.
    # The CAE-side script imports them after Abaqus starts.
    return """
import json
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
from abaqus_ai_agent.engineering_evidence import reaction_balance_from_field_evidence
from abaqus_ai_agent.acceptance import evaluate_result_acceptance

MODEL=%r
PART=%r
INSTANCE=%r
JOB=%r
STEP=%r
L=%r
B=%r
H=%r
E=%r
NU=%r
FORCE=%r

def _run_code(code):
    exec(compile(code, '<AIAgent-StaticGolden>', 'exec'), globals(), globals())
    return {'status': 'COMPLETED'}

executor = InProcessExecutor(_run_code)

geometry = python_action(MODEL, %r)
execute(executor, geometry)

plan = build_static_plan(
    MODEL,
    {'name': 'Steel', 'youngs_modulus': E, 'poisson': NU},
    {
        'section': 'BeamSection',
        'fixed': "mdb.models['StaticGolden'].rootAssembly.sets['FixedFace']",
        'load': "mdb.models['StaticGolden'].rootAssembly.sets['TipLoadVertices']",
    },
    force={'cf2': FORCE / 4.0},
    job_name=JOB,
    step_name=STEP,
)

actions = list(plan.actions)
actions.insert(3, section_assignment(
    MODEL, PART, 'BeamSection',
    "mdb.models['StaticGolden'].parts['Beam'].sets['AllCells']",
))
actions.extend([
    seed_part(MODEL, PART, 2.5),
    element_type(
        MODEL, PART,
        "mdb.models['StaticGolden'].parts['Beam'].cells",
        elem_code='C3D8R', library='STANDARD',
    ),
    generate_mesh(MODEL, PART),
    python_action(MODEL, r"""
from abaqusConstants import *
model=mdb.models['StaticGolden']
part=model.parts['Beam']
inst=model.rootAssembly.instances['Beam-1']

# Evidence sets are mesh-based so ODB field extraction receives true node/element sets.
fixed_nodes=tuple(n for n in inst.nodes if abs(n.coordinates[0]) < 1.0e-9)
if not fixed_nodes:
    raise RuntimeError('FixedNodes set is empty')
model.rootAssembly.Set(name='FixedNodes', nodes=fixed_nodes)

root_elements=[]
for elem in part.elements:
    pts=[part.nodes[label-1].coordinates for label in elem.connectivity]
    cx=sum(p[0] for p in pts)/float(len(pts))
    if cx <= 10.0 + 1.0e-9:
        root_elements.append(elem)
if not root_elements:
    raise RuntimeError('RootElements set is empty')
part.Set(name='RootElements', elements=tuple(root_elements))

tip_rp = model.rootAssembly.referencePoints
# The four-vertex CLOAD is applied symmetrically; no separate RP is needed.
print('AIAgent_STATIC_EVIDENCE_SETS_CREATED')
"""),
])

for action in actions:
    execute(executor, action)

# Native mesh verifier is executed through the existing action path. Its result
# is recorded, but this Golden Case does not invent a new mesh-quality gate.
mesh_result = execute(executor, mesh_quality(
    MODEL, PART,
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
            'step': STEP,
            'frame': -1,
            'region': "odb.rootAssembly.nodeSets['TipLoadVertices']",
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
            'step': STEP,
            'frame': -1,
            'region': "odb.rootAssembly.nodeSets['TipLoadVertices']",
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
            'step': STEP,
            'frame': -1,
            'region': "odb.rootAssembly.instances['Beam-1'].elementSets['RootElements']",
        },
    },
)

run = AnalysisRunner(executor).run(
    model_name=MODEL,
    job_name=JOB,
    criteria=criteria,
    timeout=3600,
    action_plan=tuple(actions),
    engineering_intent={
        'analysis_type': 'static',
        'nonlinear': False,
        'loads': ('concentrated_force',),
    },
)

if not run.odb_path:
    raise RuntimeError('Golden Case did not produce an ODB path')

reaction_field = extract_field(
    executor,
    run.odb_path,
    STEP,
    'RF',
    component='RF2',
    frame=-1,
    region="odb.rootAssembly.nodeSets['FixedNodes']",
)

reaction_report, reaction_summary = reaction_balance_from_field_evidence(
    {
        'status': 'available',
        'values': reaction_field.get('values', []),
    },
    applied_components=(0.0, FORCE, 0.0),
    tolerance=0.01,
    unit='N',
)

# Final acceptance is intentionally evaluated again after the real RF evidence
# exists. AnalysisRunner already performed deterministic ODB-backed criteria
# acceptance; this second call closes the engineering-check gate without adding
# a new orchestration service.
result_values = {}
for item in run.metrics:
    key = getattr(getattr(item, 'requirement', None), 'value_key', None)
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
    'model': {'length_mm': L, 'width_mm': B, 'height_mm': H},
    'material': {'E_MPa': E, 'nu': NU},
    'load': {'Fy_N': FORCE},
    'theory': {
        'tip_displacement_mm': abs(FORCE) * L ** 3 / (3.0 * E * (B * H ** 3 / 12.0)),
        'root_bending_stress_MPa': abs(FORCE) * L * (H / 2.0) / (B * H ** 3 / 12.0),
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
    raise TypeError('not JSON serializable: %r' % (type(value),))

print('AIAgent_STATIC_GOLDEN_RESULT_BEGIN')
print(json.dumps(report, default=_default, sort_keys=True))
print('AIAgent_STATIC_GOLDEN_RESULT_END')
""" % (
        MODEL, PART, INSTANCE, JOB, STEP, L, B, H, E, NU, FORCE, geometry_code
    )


def _extract_report(stdout):
    begin = 'AIAgent_STATIC_GOLDEN_RESULT_BEGIN'
    end = 'AIAgent_STATIC_GOLDEN_RESULT_END'
    if begin not in stdout or end not in stdout:
        return None
    payload = stdout.split(begin, 1)[1].split(end, 1)[0].strip()
    return json.loads(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the Static Engineering Golden Case')
    parser.add_argument('--launcher', default=os.environ.get('ABAQUS_COMMAND', 'abaqus'))
    parser.add_argument('--workdir', default=os.getcwd())
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--output', default=os.path.join('machine_validation', 'static_golden_e2e.json'))
    args = parser.parse_args(argv)

    workdir = os.path.abspath(args.workdir)
    validation_dir = os.path.join(workdir, 'machine_validation')
    os.makedirs(validation_dir, exist_ok=True)
    script_path = os.path.join(validation_dir, 'static_golden_e2e_script.py')
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
        report = _extract_report((process.stdout or '') + '\n' + (process.stderr or ''))
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
