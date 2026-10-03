#!/usr/bin/env python3
"""GA-2.6.1 Physical API Probes & Solver Calibration Harness.

Executes 4 focused, deterministic physical probes directly on Abaqus 2025:
- Probe 0 (P0): Multi-Step State Inheritance (Initial -> Step-1 -> Step-2, load propagation & reaction balance)
- Probe 1 (P1): Bolt Pretension Two-Stage Lifecycle (APPLY_FORCE -> FIX_LENGTH & internal load response)
- Probe 2 (P2): Analytical Spatial Load Field (ExpressionField + FIELD distribution integration)
- Probe 3 (P3): Moment / Torque Transfer Strategy (RP + Coupling on solid continuum without rotational DOFs)

Outputs verified machine evidence to machine_validation/ga261_probe_evidence.json.
Fail-Fast: Strict execution required. Emulated values only permitted with explicit --offline flag.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.execution.batch import resolve_default_launcher


def check_launcher(launcher: str) -> Tuple[str, bool]:
    """Resolve and verify if Abaqus launcher command actually exists on disk or PATH."""
    resolved = resolve_default_launcher(launcher)
    is_live = bool(shutil.which(resolved) or (os.path.isabs(resolved) and os.path.exists(resolved)))
    return resolved, is_live


# ==============================================================================
# Probe 0: Multi-Step State Inheritance
# ==============================================================================

def run_probe_0(workdir: Path, launcher: str, offline: bool) -> Dict[str, Any]:
    """Execute Probe 0: Multi-step DAG, state inheritance and load propagation."""
    probe_dir = workdir / "P0_MultiStep"
    probe_dir.mkdir(parents=True, exist_ok=True)

    solve_script = """from abaqus import *
from abaqusConstants import *
import part, material, section, assembly, step, interaction, load, mesh, job

# 1. Geometry & Model
m = mdb.Model(name='P0_Model')
s = m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
s.rectangle(point1=(0.0, 0.0), point2=(10.0, 10.0))
p = m.Part(name='Beam', dimensionality=THREE_D, type=DEFORMABLE_BODY)
p.BaseSolidExtrude(sketch=s, depth=100.0)

# 2. Material & Section
mat = m.Material(name='Steel')
mat.Elastic(table=((210000.0, 0.3),))
m.HomogeneousSolidSection(name='Sec', material='Steel')
p.SectionAssignment(region=(p.cells,), sectionName='Sec')

# 3. Assembly
a = m.rootAssembly
inst = a.Instance(name='Beam-1', part=p, dependent=ON)

# 4. Mesh (C3D8R Hex)
p.seedPart(size=5.0, deviationFactor=0.1)
p.generateMesh()

# 5. Multi-Step DAG: Initial -> Step-1 -> Step-2
m.StaticStep(name='Step-1', previous='Initial', timePeriod=1.0)
m.StaticStep(name='Step-2', previous='Step-1', timePeriod=1.0)

# 6. Boundary Condition: Fix root at Z=0 in Initial
root_face = inst.faces.findAt(((5.0, 5.0, 0.0),))
root_set = a.Set(faces=root_face, name='RootSet')
m.EncastreBC(name='FixRoot', createStepName='Initial', region=root_set)

# 7. Loads:
# Step-1: Load-1 on Z=100 end face, Fy = -1000.0 N (Surface Traction)
end_face = inst.faces.findAt(((5.0, 5.0, 100.0),))
end_surf = a.Surface(side1Faces=end_face, name='EndSurf')
m.SurfaceTraction(name='Load1', createStepName='Step-1', region=end_surf,
                  magnitude=10.0, directionVector=((0.0, 0.0, 0.0), (0.0, -1.0, 0.0)), traction=GENERAL)

# Step-2: Load-2 on Z=100 end face, Fy = -500.0 N
m.SurfaceTraction(name='Load2', createStepName='Step-2', region=end_surf,
                  magnitude=5.0, directionVector=((0.0, 0.0, 0.0), (0.0, -1.0, 0.0)), traction=GENERAL)

# 8. Submit Job
j = mdb.Job(name='P0_Job', model='P0_Model', type=ANALYSIS)
j.submit()
j.waitForCompletion()
print('P0_SOLVE_COMPLETED')
"""

    solve_file = probe_dir / "p0_solve.py"
    solve_file.write_text(solve_script, encoding="utf-8")
    script_sha = hashlib.sha256(solve_script.encode("utf-8")).hexdigest()

    res_json_path = (probe_dir / "p0_result.json").resolve().as_posix()
    post_script = f"""from odbAccess import openOdb
import json

odb = openOdb('P0_Job.odb', readOnly=True)
steps_present = list(odb.steps.keys())

# Step-1 verification
step1 = odb.steps['Step-1']
frame1 = step1.frames[-1]
rf_field1 = frame1.fieldOutputs['RF']
rf_y_step1 = sum(v.data[1] for v in rf_field1.values)

# Step-2 verification
step2 = odb.steps['Step-2']
frame2 = step2.frames[-1]
rf_field2 = frame2.fieldOutputs['RF']
rf_y_step2 = sum(v.data[1] for v in rf_field2.values)

inst = odb.rootAssembly.instances['BEAM-1']
elem_count = len(inst.elements)
node_count = len(inst.nodes)

res = {{
    'steps_present': steps_present,
    'step1_rf_y': float(rf_y_step1),
    'step2_rf_y': float(rf_y_step2),
    'elem_count': int(elem_count),
    'node_count': int(node_count),
}}
with open(r'{res_json_path}', 'w') as f:
    json.dump(res, f)
odb.close()
"""
    post_file = probe_dir / "p0_post.py"
    post_file.write_text(post_script, encoding="utf-8")

    if not offline:
        resolved, is_live = check_launcher(launcher)
        if not is_live:
            raise RuntimeError(f"[P0 FAIL-FAST] Abaqus launcher '{resolved}' not found.")
        run_res = subprocess.run([resolved, "cae", f"noGUI={solve_file.as_posix()}"], cwd=probe_dir, capture_output=True, text=True, timeout=120)
        if run_res.returncode != 0:
            raise RuntimeError(f"[P0 FAILED] Solver exit {run_res.returncode}:\n{run_res.stdout}\n{run_res.stderr}")
        post_res = subprocess.run([resolved, "python", post_file.as_posix()], cwd=probe_dir, capture_output=True, text=True, timeout=60)
        if post_res.returncode != 0:
            raise RuntimeError(f"[P0 FAILED] Post exit {post_res.returncode}:\n{post_res.stdout}\n{post_res.stderr}")
        with open(res_json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        tier = "REAL_ABAQUS"
    else:
        raw = {
            "steps_present": ["Step-1", "Step-2"],
            "step1_rf_y": 1000.0,
            "step2_rf_y": 1500.0,
            "elem_count": 80,
            "node_count": 189,
        }
        tier = "OFFLINE_EMULATED"

    s1_rf = raw["step1_rf_y"]
    s2_rf = raw["step2_rf_y"]
    s1_err = abs(s1_rf - 1000.0) / 1000.0
    s2_err = abs(s2_rf - 1500.0) / 1500.0
    passed = (
        raw["steps_present"] == ["Step-1", "Step-2"]
        and s1_err < 0.005
        and s2_err < 0.005
    )

    return {
        "probe": "P0_MULTI_STEP_INHERITANCE",
        "evidence_tier": tier,
        "passed": passed,
        "script_sha256": script_sha,
        "steps_verified": raw["steps_present"],
        "step1_rf_y": s1_rf,
        "step1_error": s1_err,
        "step2_rf_y": s2_rf,
        "step2_error": s2_err,
        "elem_count": raw["elem_count"],
        "node_count": raw["node_count"],
    }


# ==============================================================================
# Probe 1: Bolt Pretension Two-Stage Lifecycle
# ==============================================================================

def run_probe_1(workdir: Path, launcher: str, offline: bool) -> Dict[str, Any]:
    """Execute Probe 1: Bolt Pretension lifecycle (APPLY_FORCE -> FIX_LENGTH)."""
    probe_dir = workdir / "P1_BoltPretension"
    probe_dir.mkdir(parents=True, exist_ok=True)

    solve_script = """from abaqus import *
from abaqusConstants import *
import part, material, section, assembly, step, interaction, load, mesh, job

m = mdb.Model(name='P1_Model')
s = m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
s.rectangle(point1=(-5.0, -5.0), point2=(5.0, 5.0))
p = m.Part(name='Bolt', dimensionality=THREE_D, type=DEFORMABLE_BODY)
p.BaseSolidExtrude(sketch=s, depth=100.0)

# Partition at z=50 for bolt pre-tension section
d = p.DatumPlaneByPrincipalPlane(principalPlane=XYPLANE, offset=50.0)
p.PartitionCellByDatumPlane(datumPlane=p.datums[d.id], cells=p.cells)

mat = m.Material(name='Steel')
mat.Elastic(table=((210000.0, 0.3),))
m.HomogeneousSolidSection(name='Sec', material='Steel')
p.SectionAssignment(region=(p.cells,), sectionName='Sec')

a = m.rootAssembly
inst = a.Instance(name='Bolt-1', part=p, dependent=ON)

p.seedPart(size=5.0, deviationFactor=0.1)
p.generateMesh()

# Steps: Initial -> Step-Preload -> Step-Service
m.StaticStep(name='Step-Preload', previous='Initial', timePeriod=1.0)
m.StaticStep(name='Step-Service', previous='Step-Preload', timePeriod=1.0)

# Bottom fix at z=0 (ENCASTRE)
bot_face = inst.faces.findAt(((0.0, 0.0, 0.0),))
bot_set = a.Set(faces=bot_face, name='BotSet')
m.EncastreBC(name='FixBottom', createStepName='Initial', region=bot_set)

# Top constraint in Step-Preload at z=100
top_face = inst.faces.findAt(((0.0, 0.0, 100.0),))
top_set = a.Set(faces=top_face, name='TopSet')
m.DisplacementBC(name='FixTop', createStepName='Initial', region=top_set, u1=0.0, u2=0.0, u3=0.0)

# Datum Axis for Bolt direction (Z axis)
d_axis = a.DatumAxisByPrincipalAxis(principalAxis=ZAXIS)
axis = a.datums[d_axis.id]

# Bolt surface at z=50
cut_face = inst.faces.findAt(((0.0, 0.0, 50.0),))
cut_surf = a.Surface(side1Faces=cut_face, name='BoltSection')

# Step-Preload: Apply 5000.0 N pre-tension force
m.BoltLoad(name='BoltPreload', createStepName='Step-Preload', region=cut_surf,
           magnitude=5000.0, datumAxis=axis, boltMethod=APPLY_FORCE)

# Step-Service: Lock length (FIX_LENGTH) and apply external tension force at top
m.loads['BoltPreload'].setValuesInStep(stepName='Step-Service', boltMethod=FIX_LENGTH)

# Modify FixTop in Step-Service to release U3
m.boundaryConditions['FixTop'].setValuesInStep(stepName='Step-Service', u3=FREED)

# Apply external tension load at top face in Step-Service: 2000.0 N in +Z (20 MPa * 100 mm2)
top_surf = a.Surface(side1Faces=top_face, name='TopTractionSurf')
m.SurfaceTraction(name='ExternalTension', createStepName='Step-Service', region=top_surf,
                  magnitude=20.0, directionVector=((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)), traction=GENERAL)

j = mdb.Job(name='P1_Job', model='P1_Model', type=ANALYSIS)
j.submit()
j.waitForCompletion()
print('P1_SOLVE_COMPLETED')
"""

    solve_file = probe_dir / "p1_solve.py"
    solve_file.write_text(solve_script, encoding="utf-8")
    script_sha = hashlib.sha256(solve_script.encode("utf-8")).hexdigest()

    res_json_path = (probe_dir / "p1_result.json").resolve().as_posix()
    post_script = f"""from odbAccess import openOdb
import json

odb = openOdb('P1_Job.odb', readOnly=True)

# 1. Step-Preload
step_pre = odb.steps['Step-Preload']
frame_pre = step_pre.frames[-1]

inst = odb.rootAssembly.instances['BOLT-1']
node_coords = {{n.label: n.coordinates for n in inst.nodes}}

rf_pre = frame_pre.fieldOutputs['RF']
rf_bot_pre = sum(v.data[2] for v in rf_pre.values if abs(node_coords[v.nodeLabel][2] - 0.0) < 1e-3)
rf_top_pre = sum(v.data[2] for v in rf_pre.values if abs(node_coords[v.nodeLabel][2] - 100.0) < 1e-3)

# 2. Step-Service
step_srv = odb.steps['Step-Service']
frame_srv = step_srv.frames[-1]

rf_srv = frame_srv.fieldOutputs['RF']
rf_bot_srv = sum(v.data[2] for v in rf_srv.values if abs(node_coords[v.nodeLabel][2] - 0.0) < 1e-3)
rf_top_srv = sum(v.data[2] for v in rf_srv.values if abs(node_coords[v.nodeLabel][2] - 100.0) < 1e-3)

# Top displacement in Step-Service
u_srv = frame_srv.fieldOutputs['U']
u3_top_srv = sum(v.data[2] for v in u_srv.values if abs(node_coords[v.nodeLabel][2] - 100.0) < 1e-3) / 9.0

res = {{
    'rf_bottom_preload': float(rf_bot_pre),
    'rf_top_preload': float(rf_top_pre),
    'rf_bottom_service': float(rf_bot_srv),
    'rf_top_service': float(rf_top_srv),
    'u3_top_service': float(u3_top_srv),
    'elem_count': len(inst.elements),
    'node_count': len(inst.nodes),
}}
with open(r'{res_json_path}', 'w') as f:
    json.dump(res, f)
odb.close()
"""
    post_file = probe_dir / "p1_post.py"
    post_file.write_text(post_script, encoding="utf-8")

    if not offline:
        resolved, is_live = check_launcher(launcher)
        if not is_live:
            raise RuntimeError(f"[P1 FAIL-FAST] Abaqus launcher '{resolved}' not found.")
        run_res = subprocess.run([resolved, "cae", f"noGUI={solve_file.as_posix()}"], cwd=probe_dir, capture_output=True, text=True, timeout=120)
        if run_res.returncode != 0:
            raise RuntimeError(f"[P1 FAILED] Solver exit {run_res.returncode}:\n{run_res.stdout}\n{run_res.stderr}")
        post_res = subprocess.run([resolved, "python", post_file.as_posix()], cwd=probe_dir, capture_output=True, text=True, timeout=60)
        if post_res.returncode != 0:
            raise RuntimeError(f"[P1 FAILED] Post exit {post_res.returncode}:\n{post_res.stdout}\n{post_res.stderr}")
        with open(res_json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        tier = "REAL_ABAQUS"
    else:
        raw = {
            "rf_bottom_preload": -5000.0,
            "rf_top_preload": 5000.0,
            "rf_bottom_service": -2000.0,
            "rf_top_service": 0.0,
            "u3_top_service": -0.014367,
            "elem_count": 80,
            "node_count": 189,
        }
        tier = "OFFLINE_EMULATED"

    # Preload verification: F_preload = 5000.0 N
    # Step-Preload bottom reaction = -5000.0 N, top reaction = +5000.0 N
    pre_err = abs(abs(raw["rf_bottom_preload"]) - 5000.0) / 5000.0
    # Service verification: external load = 2000.0 N -> bottom reaction = -2000.0 N
    srv_err = abs(abs(raw["rf_bottom_service"]) - 2000.0) / 2000.0
    passed = (pre_err < 0.001) and (srv_err < 0.001)

    return {
        "probe": "P1_BOLT_PRETENSION_LIFECYCLE",
        "evidence_tier": tier,
        "passed": passed,
        "script_sha256": script_sha,
        "rf_bottom_preload": raw["rf_bottom_preload"],
        "rf_top_preload": raw["rf_top_preload"],
        "preload_error": pre_err,
        "rf_bottom_service": raw["rf_bottom_service"],
        "rf_top_service": raw["rf_top_service"],
        "service_error": srv_err,
        "u3_top_service": raw["u3_top_service"],
        "elem_count": raw["elem_count"],
        "node_count": raw["node_count"],
    }


# ==============================================================================
# Probe 2: Analytical Spatial Load Field
# ==============================================================================

def run_probe_2(workdir: Path, launcher: str, offline: bool) -> Dict[str, Any]:
    """Execute Probe 2: ExpressionField + FIELD spatial load integration."""
    probe_dir = workdir / "P2_SpatialField"
    probe_dir.mkdir(parents=True, exist_ok=True)

    solve_script = """from abaqus import *
from abaqusConstants import *
import part, material, section, assembly, step, interaction, load, mesh, job

m = mdb.Model(name='P2_Model')
s = m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
s.rectangle(point1=(0.0, 0.0), point2=(20.0, 50.0))
p = m.Part(name='Plate', dimensionality=THREE_D, type=DEFORMABLE_BODY)
p.BaseSolidExtrude(sketch=s, depth=10.0)

mat = m.Material(name='Steel')
mat.Elastic(table=((210000.0, 0.3),))
m.HomogeneousSolidSection(name='Sec', material='Steel')
p.SectionAssignment(region=(p.cells,), sectionName='Sec')

a = m.rootAssembly
inst = a.Instance(name='Plate-1', part=p, dependent=ON)

p.seedPart(size=5.0, deviationFactor=0.1)
p.generateMesh()

m.StaticStep(name='Step-1', previous='Initial', timePeriod=1.0)

root_face = inst.faces.findAt(((10.0, 25.0, 0.0),))
root_set = a.Set(faces=root_face, name='RootSet')
m.EncastreBC(name='FixRoot', createStepName='Initial', region=root_set)

# Spatial Field: p(Y) = 10.0 * (1.0 + 0.02 * Y)
# Analytical integral on [0, 20] x [0, 50] = 15000.0 N
m.ExpressionField(name='LinearYField', expression='1.0 + 0.02 * Y')
top_face = inst.faces.findAt(((10.0, 25.0, 10.0),))
top_surf = a.Surface(side1Faces=top_face, name='TopSurf')
m.Pressure(name='SpatialPressure', createStepName='Step-1', region=top_surf,
           magnitude=10.0, distributionType=FIELD, field='LinearYField')

j = mdb.Job(name='P2_Job', model='P2_Model', type=ANALYSIS)
j.submit()
j.waitForCompletion()
print('P2_SOLVE_COMPLETED')
"""

    solve_file = probe_dir / "p2_solve.py"
    solve_file.write_text(solve_script, encoding="utf-8")
    script_sha = hashlib.sha256(solve_script.encode("utf-8")).hexdigest()

    res_json_path = (probe_dir / "p2_result.json").resolve().as_posix()
    post_script = f"""from odbAccess import openOdb
import json

odb = openOdb('P2_Job.odb', readOnly=True)
step = odb.steps['Step-1']
frame = step.frames[-1]

rf_field = frame.fieldOutputs['RF']
total_rf3 = sum(v.data[2] for v in rf_field.values)

inst = odb.rootAssembly.instances['PLATE-1']
res = {{
    'total_rf3': float(total_rf3),
    'elem_count': len(inst.elements),
    'node_count': len(inst.nodes)
}}
with open(r'{res_json_path}', 'w') as f:
    json.dump(res, f)
odb.close()
"""
    post_file = probe_dir / "p2_post.py"
    post_file.write_text(post_script, encoding="utf-8")

    if not offline:
        resolved, is_live = check_launcher(launcher)
        if not is_live:
            raise RuntimeError(f"[P2 FAIL-FAST] Abaqus launcher '{resolved}' not found.")
        run_res = subprocess.run([resolved, "cae", f"noGUI={solve_file.as_posix()}"], cwd=probe_dir, capture_output=True, text=True, timeout=120)
        if run_res.returncode != 0:
            raise RuntimeError(f"[P2 FAILED] Solver exit {run_res.returncode}:\n{run_res.stdout}\n{run_res.stderr}")
        post_res = subprocess.run([resolved, "python", post_file.as_posix()], cwd=probe_dir, capture_output=True, text=True, timeout=60)
        if post_res.returncode != 0:
            raise RuntimeError(f"[P2 FAILED] Post exit {post_res.returncode}:\n{post_res.stdout}\n{post_res.stderr}")
        with open(res_json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        tier = "REAL_ABAQUS"
    else:
        raw = {
            "total_rf3": 15000.0,
            "elem_count": 80,
            "node_count": 165,
        }
        tier = "OFFLINE_EMULATED"

    # Analytical Reference:
    # Integral = 20 * 10 * [Y + 0.01 Y^2]_0^50 = 200 * (50 + 25) = 15000.0 N
    analytical_ref = 15000.0
    actual_rf3 = raw["total_rf3"]
    rf_err = abs(actual_rf3 - analytical_ref) / analytical_ref
    passed = rf_err < 0.001

    return {
        "probe": "P2_SPATIAL_LOAD_FIELD",
        "evidence_tier": tier,
        "passed": passed,
        "script_sha256": script_sha,
        "analytical_reference": analytical_ref,
        "actual_total_rf3": actual_rf3,
        "integral_relative_error": rf_err,
        "elem_count": raw["elem_count"],
        "node_count": raw["node_count"],
    }


# ==============================================================================
# Probe 3: Moment / Torque Transfer Strategy (RP + Coupling)
# ==============================================================================

def run_probe_3(workdir: Path, launcher: str, offline: bool) -> Dict[str, Any]:
    """Execute Probe 3: RP + Kinematic Coupling on 3D solid continuum."""
    probe_dir = workdir / "P3_MomentCoupling"
    probe_dir.mkdir(parents=True, exist_ok=True)

    solve_script = """from abaqus import *
from abaqusConstants import *
import part, material, section, assembly, step, interaction, load, mesh, job, regionToolset

m = mdb.Model(name='P3_Model')
s = m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
s.rectangle(point1=(-10.0, -10.0), point2=(10.0, 10.0))
p = m.Part(name='Shaft', dimensionality=THREE_D, type=DEFORMABLE_BODY)
p.BaseSolidExtrude(sketch=s, depth=100.0)

mat = m.Material(name='Steel')
mat.Elastic(table=((210000.0, 0.3),))
m.HomogeneousSolidSection(name='Sec', material='Steel')
p.SectionAssignment(region=(p.cells,), sectionName='Sec')

a = m.rootAssembly
inst = a.Instance(name='Shaft-1', part=p, dependent=ON)

p.seedPart(size=5.0, deviationFactor=0.1)
p.generateMesh()

m.StaticStep(name='Step-1', previous='Initial', timePeriod=1.0)

# Fix Root at z=0 (ENCASTRE)
root_face = inst.faces.findAt(((0.0, 0.0, 0.0),))
root_set = a.Set(faces=root_face, name='RootSet')
m.EncastreBC(name='FixRoot', createStepName='Initial', region=root_set)

# Reference Point at top center (0, 0, 100)
rp_feature = a.ReferencePoint(point=(0.0, 0.0, 100.0))
rp_ref = a.referencePoints[rp_feature.id]
rp_region = regionToolset.Region(referencePoints=(rp_ref,))

# Top Coupling Surface
top_face = inst.faces.findAt(((0.0, 0.0, 100.0),))
top_surf = a.Surface(side1Faces=top_face, name='TopSurf')

# Coupling
m.Coupling(name='RP_Coupling', controlPoint=rp_region, surface=top_surf,
           influenceRadius=WHOLE_SURFACE, couplingType=KINEMATIC,
           u1=ON, u2=ON, u3=ON, ur1=ON, ur2=ON, ur3=ON)

# Apply Moment CM3 = 100000.0 N*mm via native Moment API
m.Moment(name='TorqueLoad', createStepName='Step-1', region=rp_region, cm3=100000.0)

j = mdb.Job(name='P3_Job', model='P3_Model', type=ANALYSIS)
j.submit()
j.waitForCompletion()
print('P3_SOLVE_COMPLETED')
"""

    solve_file = probe_dir / "p3_solve.py"
    solve_file.write_text(solve_script, encoding="utf-8")
    script_sha = hashlib.sha256(solve_script.encode("utf-8")).hexdigest()

    res_json_path = (probe_dir / "p3_result.json").resolve().as_posix()
    post_script = f"""from odbAccess import openOdb
import json

odb = openOdb('P3_Job.odb', readOnly=True)
step = odb.steps['Step-1']
frame = step.frames[-1]

inst = odb.rootAssembly.instances['SHAFT-1']
node_coords = {{n.label: n.coordinates for n in inst.nodes}}

rf_field = frame.fieldOutputs['RF']

total_torque = 0.0
total_fx = 0.0
total_fy = 0.0
root_node_count = 0

for v in rf_field.values:
    coord = node_coords.get(v.nodeLabel)
    if coord is not None and abs(coord[2] - 0.0) < 1e-3:
        x, y, z = coord
        fx, fy, fz = v.data
        total_fx += fx
        total_fy += fy
        total_torque += (x * fy - y * fx)
        root_node_count += 1

u_field = frame.fieldOutputs['UR']
max_ur3 = max(abs(v.data[2]) for v in u_field.values if len(v.data) > 2)

res = {{
    'total_torque_reaction': float(total_torque),
    'total_fx': float(total_fx),
    'total_fy': float(total_fy),
    'root_node_count': int(root_node_count),
    'max_ur3': float(max_ur3),
    'elem_count': len(inst.elements),
    'node_count': len(inst.nodes)
}}
with open(r'{res_json_path}', 'w') as f:
    json.dump(res, f)
odb.close()
"""
    post_file = probe_dir / "p3_post.py"
    post_file.write_text(post_script, encoding="utf-8")

    if not offline:
        resolved, is_live = check_launcher(launcher)
        if not is_live:
            raise RuntimeError(f"[P3 FAIL-FAST] Abaqus launcher '{resolved}' not found.")
        run_res = subprocess.run([resolved, "cae", f"noGUI={solve_file.as_posix()}"], cwd=probe_dir, capture_output=True, text=True, timeout=120)
        if run_res.returncode != 0:
            raise RuntimeError(f"[P3 FAILED] Solver exit {run_res.returncode}:\n{run_res.stdout}\n{run_res.stderr}")
        post_res = subprocess.run([resolved, "python", post_file.as_posix()], cwd=probe_dir, capture_output=True, text=True, timeout=60)
        if post_res.returncode != 0:
            raise RuntimeError(f"[P3 FAILED] Post exit {post_res.returncode}:\n{post_res.stdout}\n{post_res.stderr}")
        with open(res_json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        tier = "REAL_ABAQUS"
    else:
        raw = {
            "total_torque_reaction": -100000.0,
            "total_fx": 0.0,
            "total_fy": 0.0,
            "root_node_count": 25,
            "max_ur3": 0.005676,
            "elem_count": 320,
            "node_count": 525,
        }
        tier = "OFFLINE_EMULATED"

    # Physics Verification:
    # Applied Mz = 100000.0 N*mm -> root shear couple torque reaction = -100000.0 N*mm
    applied_mz = 100000.0
    actual_torque = raw["total_torque_reaction"]
    torque_err = abs(abs(actual_torque) - applied_mz) / applied_mz
    net_force = math.sqrt(raw["total_fx"] ** 2 + raw["total_fy"] ** 2)
    passed = (torque_err < 0.001) and (net_force < 1e-6)

    return {
        "probe": "P3_MOMENT_COUPLING_STRATEGY",
        "evidence_tier": tier,
        "passed": passed,
        "script_sha256": script_sha,
        "applied_torque": applied_mz,
        "reaction_torque": actual_torque,
        "torque_equilibrium_error": torque_err,
        "net_shear_force": net_force,
        "max_ur3": raw["max_ur3"],
        "root_node_count": raw["root_node_count"],
        "elem_count": raw["elem_count"],
        "node_count": raw["node_count"],
    }


# ==============================================================================
# Suite Orchestrator & Evidence Persistence
# ==============================================================================

def execute_all_probes(
    workdir: Path,
    launcher: str = "abaqus",
    offline: bool = False,
    selected_probe: str = "ALL",
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute all selected probes and generate certified evidence manifest."""
    workdir.mkdir(parents=True, exist_ok=True)

    print("================================================================================")
    print(" [GA-2.6.1] Abaqus 2025 Physical API Probes & Solver Calibration Harness")
    print("================================================================================")
    print(f" Mode: {'OFFLINE (Emulated)' if offline else 'REAL_ABAQUS (Live Solver)'}")
    print(f" Target Probes: {selected_probe}")

    probe_funcs = {
        "P0": ("Probe 0 (Multi-Step State Inheritance)", run_probe_0),
        "P1": ("Probe 1 (Bolt Pretension Two-Stage Lifecycle)", run_probe_1),
        "P2": ("Probe 2 (Analytical Spatial Load Field)", run_probe_2),
        "P3": ("Probe 3 (Moment / Coupling Strategy)", run_probe_3),
    }

    results = []
    all_passed = True

    targets = list(probe_funcs.keys()) if selected_probe == "ALL" else [selected_probe]
    for key in targets:
        title, func = probe_funcs[key]
        print(f"\n---> Running {title}...")
        res = func(workdir, launcher, offline)
        status_str = "PASS" if res["passed"] else "FAIL"
        print(f"     Status: [{status_str}] | Tier: {res['evidence_tier']}")
        results.append(res)
        if not res["passed"]:
            all_passed = False

    manifest = {
        "phase": "GA-2.6.1",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "solver_version": "Abaqus 2025" if not offline else "OFFLINE",
        "all_probes_passed": all_passed,
        "probe_count": len(results),
        "evidence_tier": "REAL_ABAQUS" if not offline else "OFFLINE_EMULATED",
        "probes": results,
    }

    if output_path is not None:
        evidence_file = output_path
    elif not offline:
        evidence_file = ROOT / "machine_validation" / "ga261_probe_evidence.json"
    else:
        evidence_file = workdir / "ga261_probe_evidence.json"

    evidence_file.parent.mkdir(parents=True, exist_ok=True)
    evidence_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n[EVIDENCE WRITTEN] -> {evidence_file}")
    print(f"Summary: {len(results)}/{len(results)} Probes Completed. Overall: {'PASS' if all_passed else 'FAIL'}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="GA-2.6.1 Abaqus 2025 Physical API Probes")
    parser.add_argument("--workdir", type=Path, default=ROOT / ".tmp" / "ga261_probes", help="Working directory for CAE runs")
    parser.add_argument("--launcher", type=str, default="abaqus", help="Abaqus launcher name or path")
    parser.add_argument("--offline", action="store_true", help="Run in offline emulated verification mode")
    parser.add_argument("--probe", type=str, default="ALL", choices=["ALL", "P0", "P1", "P2", "P3"], help="Run specific probe")
    args = parser.parse_args()

    manifest = execute_all_probes(
        workdir=args.workdir,
        launcher=args.launcher,
        offline=args.offline,
        selected_probe=args.probe,
    )
    if not manifest["all_probes_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
