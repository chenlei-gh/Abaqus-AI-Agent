#!/usr/bin/env python3
"""Run the Thermal Steady-State Golden Case through the real Abaqus runtime.

The host side launches Abaqus. The CAE-side script uses the project's
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

MODEL = "ThermalGolden"
PART = "Bar"
INSTANCE = "Bar-1"
JOB = "ThermalGoldenJob"
STEP = "Step-1"

L = 100.0
B = 10.0
H = 10.0
K_VAL = 50.0  # mW/(mm*K) == W/(m*K)
T_HOT = 100.0  # deg C
T_COLD = 0.0   # deg C
THEORETICAL_Q_TOTAL = K_VAL * (B * H) * (T_HOT - T_COLD) / L  # 5000.0 mW


def build_thermal_golden_script(src_dir=None):
    src_dir = str(src_dir or SRC)
    geometry_code = r"""
from abaqus import mdb
from abaqusConstants import THREE_D, DEFORMABLE_BODY, ON, OFF, CARTESIAN

if %r in mdb.models:
    del mdb.models[%r]
model = mdb.Model(name=%r)

sketch = model.ConstrainedSketch(name='BarProfile', sheetSize=300.0)
sketch.rectangle(point1=(0.0, 0.0), point2=(%r, %r))
part = model.Part(name=%r, dimensionality=THREE_D, type=DEFORMABLE_BODY)
part.BaseSolidExtrude(sketch=sketch, depth=%r)
del model.sketches['BarProfile']

assembly = model.rootAssembly
assembly.DatumCsysByDefault(CARTESIAN)
assembly.Instance(name=%r, part=part, dependent=ON)
inst = assembly.instances[%r]

hot_face = inst.faces.findAt(((0.0, %r, %r),))
cold_face = inst.faces.findAt(((%r, %r, %r),))
assembly.Set(name='HotFace', faces=hot_face)
assembly.Set(name='ColdFace', faces=cold_face)

part.Set(name='AllCells', cells=part.cells)

print('AIAgent_THERMAL_GEOMETRY_CREATED')
""" % (
    MODEL, MODEL, MODEL, L, H, PART, B, INSTANCE, INSTANCE,
    H / 2.0, B / 2.0, L, H / 2.0, B / 2.0,
)

    evidence_sets_code = r"""
from abaqusConstants import *
model=mdb.models['ThermalGolden']
part=model.parts['Bar']
inst=model.rootAssembly.instances['Bar-1']
model.rootAssembly.regenerate()

# Evidence sets are mesh-based so ODB field extraction receives true node/element sets.
hot_nodes = inst.nodes.getByBoundingBox(xMin=-0.01, xMax=0.01)
if not hot_nodes:
    raise RuntimeError('HotNodes set is empty')
model.rootAssembly.Set(name='HotNodes', nodes=hot_nodes)

cold_nodes = inst.nodes.getByBoundingBox(xMin=99.99, xMax=100.01)
if not cold_nodes:
    raise RuntimeError('ColdNodes set is empty')
model.rootAssembly.Set(name='ColdNodes', nodes=cold_nodes)

mid_nodes = inst.nodes.getByBoundingBox(xMin=49.99, xMax=50.01)
if not mid_nodes:
    raise RuntimeError('MidNodes set is empty')
model.rootAssembly.Set(name='MidNodes', nodes=mid_nodes)

all_bc_nodes = inst.nodes.getByBoundingBox(xMin=-0.01, xMax=0.01) + inst.nodes.getByBoundingBox(xMin=99.99, xMax=100.01)
model.rootAssembly.Set(name='AllBCNodes', nodes=all_bc_nodes)

print('AIAgent_THERMAL_EVIDENCE_SETS_CREATED')
"""

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
from abaqus_ai_agent.workflow.thermal import build_thermal_plan
from abaqus_ai_agent.execution.client import InProcessExecutor
from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
from abaqus_ai_agent.execution.odb import extract_field
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.engineering_evidence import thermal_flux_balance_from_field_evidence
from abaqus_ai_agent.acceptance import evaluate_result_acceptance

model_name=%r
part_name=%r
instance_name=%r
job_name=%r
step_name=%r
bar_l=%r
bar_b=%r
bar_h=%r
mat_k=%r
t_hot=%r
t_cold=%r
q_theory=%r

def _run_code(code):
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        exec(compile(code, '<AIAgent-ThermalGolden>', 'exec'), globals(), globals())
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

plan = build_thermal_plan(
    model_name,
    {'name': 'SteelThermal', 'conductivity': mat_k},
    {
        'section': 'ThermalSection',
    },
    temperature_bcs=(
        {'name': 'HotEndBC', 'region': "mdb.models['ThermalGolden'].rootAssembly.sets['HotFace']", 'magnitude': t_hot},
        {'name': 'ColdEndBC', 'region': "mdb.models['ThermalGolden'].rootAssembly.sets['ColdFace']", 'magnitude': t_cold},
    ),
    response='STEADY_STATE',
    job_name=job_name,
    step_name=step_name,
    field_variables=('NT', 'HFL', 'RFL'),
)

actions = list(plan.actions[:-1])
actions.insert(3, section_assignment(
    model_name, part_name, 'ThermalSection',
    "mdb.models['ThermalGolden'].parts['Bar'].sets['AllCells']",
))
actions.extend([
    seed_part(model_name, part_name, 2.5),
    element_type(
        model_name, part_name,
        "mdb.models['ThermalGolden'].parts['Bar'].sets['AllCells']",
        elem_code='DC3D8', library='STANDARD',
    ),
    generate_mesh(model_name, part_name),
    python_action(model_name, %r),
    plan.actions[-1],
])

for action in actions:
    execute(executor, action)

mesh_result = execute(executor, mesh_quality(
    model_name, part_name,
    max_aspect_ratio=5.0,
    max_angular_deviation=20.0,
    max_geometric_deviation_factor=0.1,
    analysis_checks=True,
))

criteria = (
    {
        'name': 'mid_temperature_lower',
        'value_key': 'mid_temp_lower',
        'operator': '>=',
        'limit': 49.5,
        'unit': 'C',
        'result': {
            'field': 'NT',
            'aggregation': 'average',
            'step': step_name,
            'frame': -1,
            'region': "odb.rootAssembly.nodeSets['MIDNODES']",
        },
    },
    {
        'name': 'mid_temperature_upper',
        'value_key': 'mid_temp_upper',
        'operator': '<=',
        'limit': 50.5,
        'unit': 'C',
        'result': {
            'field': 'NT',
            'aggregation': 'average',
            'step': step_name,
            'frame': -1,
            'region': "odb.rootAssembly.nodeSets['MIDNODES']",
        },
    },
    {
        'name': 'hot_boundary_temp',
        'value_key': 'hot_temp',
        'operator': '>=',
        'limit': 99.5,
        'unit': 'C',
        'result': {
            'field': 'NT',
            'aggregation': 'average',
            'step': step_name,
            'frame': -1,
            'region': "odb.rootAssembly.nodeSets['HOTNODES']",
        },
    },
    {
        'name': 'cold_boundary_temp',
        'value_key': 'cold_temp',
        'operator': '<=',
        'limit': 0.5,
        'unit': 'C',
        'result': {
            'field': 'NT',
            'aggregation': 'average',
            'step': step_name,
            'frame': -1,
            'region': "odb.rootAssembly.nodeSets['COLDNODES']",
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
        id='thermal-golden',
        kind='steady_state_heat_transfer_bar',
        description='1D steady-state heat conduction bar between two fixed temperatures',
        analysis_type='thermal',
        loads=(),
        boundary_conditions=('temperature_bc',),
        metadata={'solver': 'standard', 'procedure': 'heat_transfer'},
    ),
)

if not run.odb_path:
    raise RuntimeError('Thermal Golden Case did not produce an ODB path: diagnostics=' + str(run.diagnostics) + ' state=' + str(run.state) + ' status=' + str(run.job_status))

# Extract full nodal temperature field for 1D analytical profile comparison
nt_field = extract_field(
    executor,
    run.odb_path,
    step_name,
    'NT',
    frame=-1,
)

nt_values = nt_field.get('values', [])
analytical_errors = []
profile_samples = []
for item in nt_values:
    coords = item.get('coordinates')
    t_val = item.get('data')
    if coords is not None and isinstance(t_val, (int, float)):
        x_coord = float(coords[0])
        t_exact = t_hot + (t_cold - t_hot) * (x_coord / bar_l)
        err = abs(float(t_val) - t_exact)
        analytical_errors.append(err)
        if len(profile_samples) < 10 and abs(x_coord - round(x_coord / 10.0) * 10.0) < 1e-3:
            profile_samples.append({
                'x': x_coord, 'T_actual': float(t_val), 'T_exact': t_exact, 'error': err
            })

max_temp_error = max(analytical_errors) if analytical_errors else 0.0
mean_temp_error = sum(analytical_errors) / len(analytical_errors) if analytical_errors else 0.0

# Extract Reaction Flux (RFL) at boundary nodes for thermal energy conservation check
rfl_field = extract_field(
    executor,
    run.odb_path,
    step_name,
    'RFL',
    frame=-1,
    region="odb.rootAssembly.nodeSets['ALLBCNODES']",
)

rfl_hot_field = extract_field(
    executor,
    run.odb_path,
    step_name,
    'RFL',
    frame=-1,
    region="odb.rootAssembly.nodeSets['HOTNODES']",
)

rfl_cold_field = extract_field(
    executor,
    run.odb_path,
    step_name,
    'RFL',
    frame=-1,
    region="odb.rootAssembly.nodeSets['COLDNODES']",
)

thermal_balance_report, reaction_summary = thermal_flux_balance_from_field_evidence(
    {
        'status': 'available',
        'values': rfl_field.get('values', []),
    },
    reference_flux=q_theory,
    tolerance=0.01,
    unit='mW',
)

hot_flux_sum = sum([float(x.get('data', 0.0)) for x in rfl_hot_field.get('values', [])])
cold_flux_sum = sum([float(x.get('data', 0.0)) for x in rfl_cold_field.get('values', [])])

result_values = {}
for item in run.metrics:
    metadata = getattr(item, 'metadata', {}) or {}
    key = metadata.get('value_key')
    value = getattr(item, 'value', None)
    if key and isinstance(value, (int, float)):
        result_values[key] = value

result_values['max_temperature_error'] = max_temp_error

thermal_criteria = list(criteria)
thermal_criteria.append({
    'name': 'max_temperature_profile_error',
    'value_key': 'max_temperature_error',
    'operator': '<=',
    'limit': 0.5,
    'unit': 'C',
})

final_acceptance = evaluate_result_acceptance(
    result_status=run.job_status.state.value.lower() if run.job_status else 'unknown',
    engineering=thermal_balance_report,
    mesh_quality=mesh_result,
    values=result_values,
    criteria=tuple(thermal_criteria),
)

# Also test a strict gate to confirm failure detection
strict_criteria = list(thermal_criteria)
strict_criteria.append({
    'name': 'strict_temperature_gate_artificial',
    'value_key': 'mid_temp_lower',
    'operator': '>=',
    'limit': 60.0,
    'unit': 'C',
})
strict_acceptance = evaluate_result_acceptance(
    result_status=run.job_status.state.value.lower() if run.job_status else 'unknown',
    engineering=thermal_balance_report,
    mesh_quality=mesh_result,
    values=result_values,
    criteria=tuple(strict_criteria),
)

report = {
    'status': 'pass' if (
        run.solver_completed
        and run.odb_path
        and thermal_balance_report.passed
        and final_acceptance.passed
        and not strict_acceptance.passed
    ) else 'fail',
    'model': {'length_mm': bar_l, 'width_mm': bar_b, 'height_mm': bar_h},
    'material': {'conductivity_mW_mm_K': mat_k},
    'temperatures': {'T_hot_C': t_hot, 'T_cold_C': t_cold},
    'theory': {
        'Q_rate_total_mW': q_theory,
        'temperature_gradient_C_per_mm': (t_cold - t_hot) / bar_l,
        'T_mid_exact_C': (t_hot + t_cold) / 2.0,
    },
    'workflow': {
        'thermal_plan_actions': len(plan.actions),
        'action_count': len(actions),
        'solver_completed': run.solver_completed,
        'state': run.state.value,
        'engineering_status': run.engineering_status,
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
        'max_temp_error_C': max_temp_error,
        'mean_temp_error_C': mean_temp_error,
        'profile_samples': profile_samples,
    },
    'thermal_balance': {
        'hot_nodes_RFL_sum_mW': hot_flux_sum,
        'cold_nodes_RFL_sum_mW': cold_flux_sum,
        'net_reaction_flux_mW': hot_flux_sum + cold_flux_sum,
        'theoretical_flux_mW': q_theory,
        'flux_balance_passed': thermal_balance_report.passed,
    },
    'engineering_checks': {
        'thermal_balance_report': thermal_balance_report,
        'mesh_result': mesh_result,
    },
    'acceptance': final_acceptance,
    'strict_acceptance': {
        'passed': strict_acceptance.passed,
        'failures': list(strict_acceptance.failures),
    },
    'provenance': run.provenance,
}

def _default(value):
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, 'value'):
        return value.value
    return str(value)

print('AIAgent_THERMAL_GOLDEN_REPORT_JSON_BEGIN')
print(json.dumps(report, indent=2, default=_default))
print('AIAgent_THERMAL_GOLDEN_REPORT_JSON_END')
print('AIAgent_THERMAL_E2E_EVIDENCE_STATUS: ' + report['status'])
""" % (
    src_dir,
    MODEL, PART, INSTANCE, JOB, STEP,
    L, B, H, K_VAL, T_HOT, T_COLD, THEORETICAL_Q_TOTAL,
    geometry_code,
    evidence_sets_code,
)


def parse_thermal_report_from_output(output):
    begin = "AIAgent_THERMAL_GOLDEN_REPORT_JSON_BEGIN"
    end = "AIAgent_THERMAL_GOLDEN_REPORT_JSON_END"
    if begin not in output or end not in output:
        return None
    raw = output.split(begin, 1)[1].split(end, 1)[0].strip()
    clean_lines = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("#:"):
            line = line[2:].strip()
        if line:
            clean_lines.append(line)
    try:
        return json.loads("\n".join(clean_lines))
    except Exception:
        return None


def parse_evidence_status_from_output(output):
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("#:"):
            line = line[2:].strip()
        if "AIAgent_THERMAL_E2E_EVIDENCE_STATUS:" in line:
            return line.split("AIAgent_THERMAL_E2E_EVIDENCE_STATUS:", 1)[1].strip()
    return None


def main():
    parser = argparse.ArgumentParser(description="Run Thermal Steady-State Golden Case on live Abaqus")
    parser.add_argument("--launcher", default=os.environ.get("ABAQUS_BAT", "abaqus"),
                        help="Path to abaqus.bat or command name")
    parser.add_argument("--workdir", default=None, help="Working directory for validation files")
    parser.add_argument("--timeout", type=int, default=300, help="Abaqus process timeout in seconds")
    args = parser.parse_args()

    workdir = Path(args.workdir or (ROOT / "machine_validation")).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    script_path = workdir / "thermal_golden_e2e_script.py"
    script_path.write_text(build_thermal_golden_script(src_dir=SRC), encoding="utf-8")

    executor = BatchExecutor(launcher=args.launcher, workdir=workdir, timeout=args.timeout)
    proc = executor.run_nogui(script_path, timeout=args.timeout)

    combined_output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()

    status = parse_evidence_status_from_output(combined_output)
    report = parse_thermal_report_from_output(combined_output)

    if not status or not report:
        # Fallback to checking rpy files if stdout was captured by Abaqus
        for rpy in sorted(workdir.glob("abaqus.rpy*"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                content = rpy.read_text(encoding="utf-8", errors="replace")
                if not status:
                    status = parse_evidence_status_from_output(content)
                if not report:
                    report = parse_thermal_report_from_output(content)
                if status and report:
                    break
            except Exception:
                pass

    overall_status = "pass" if (status == "pass" and report is not None and report.get("status") == "pass") else "fail"
    result = {
        "status": overall_status,
        "launcher": args.launcher,
        "workdir": str(workdir),
        "script": str(script_path),
        "case": "1d_steady_state_heat_conduction",
        "command": proc.command,
        "return_code": proc.return_code,
        "process_succeeded": proc.return_code == 0,
        "report": report,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }

    out_file = workdir / "thermal_golden_e2e.json"
    out_file.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    print("AIAgent_THERMAL_E2E_EVIDENCE_STATUS: %s" % result["status"])
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
