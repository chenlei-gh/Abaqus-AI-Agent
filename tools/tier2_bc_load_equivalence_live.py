#!/usr/bin/env python3
"""Tier 2 Live Real-Machine Validation: BC / Load Engineering Equivalence.

Verifies:
1. Case A: Cantilever + Concentrated Force -> sum(RF) + CF = 0 static equilibrium.
2. Case B: Cantilever + Surface Pressure -> sum(RF) + integral(P*dA) = 0 balance.
3. Case C: 1D Steady Heat Transfer -> linear T distribution and heat balance.
4. Case D: Structural conflict preflight detection (fail-closed before solver).
5. Case E: Rigid-body under-constrained model -> solver numerical singularity detection.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.execution.batch import BatchExecutor
from abaqus_ai_agent.actions.builders import fixed_bc, displacement_bc
from abaqus_ai_agent.validation.preflight import preflight_plan


def build_tier2_abaqus_script(workdir_escaped: str, result_json_escaped: str) -> str:
    """Abaqus CAE noGUI script for Cases A, B, C, and E."""
    return '''# -*- coding: mbcs -*-
import sys
import json
import os
from abaqus import *
from abaqusConstants import *
import part
import material
import section
import assembly
import step
import interaction
import load
import mesh
import job
import odbAccess

report = {
    "tier": "Tier 2: BC / Load Engineering Equivalence",
    "case_a_cf_equilibrium": {},
    "case_b_pressure_equilibrium": {},
    "case_c_thermal_gradient": {},
    "case_e_singularity_detection": {},
    "passed": False,
    "diagnostics": []
}

try:
    # =========================================================================
    # CASE A: Concentrated Force Equilibrium
    # =========================================================================
    Mdb()
    m_a = mdb.models['Model-1']
    s_a = m_a.ConstrainedSketch(name='sketch_a', sheetSize=100.0)
    s_a.rectangle(point1=(0.0, 0.0), point2=(10.0, 10.0))
    p_a = m_a.Part(name='BeamA', dimensionality=THREE_D, type=DEFORMABLE_BODY)
    p_a.BaseSolidExtrude(sketch=s_a, depth=100.0)

    mat_a = m_a.Material(name='Steel')
    mat_a.Elastic(table=((210000.0, 0.3), ))
    m_a.HomogeneousSolidSection(name='SolidA', material='Steel', thickness=None)
    p_a.SectionAssignment(region=(p_a.cells, ), sectionName='SolidA')

    a_a = m_a.rootAssembly
    inst_a = a_a.Instance(name='BeamA-1', part=p_a, dependent=ON)
    p_a.seedPart(size=10.0, deviationFactor=0.1, minSizeFactor=0.1)
    p_a.generateMesh()
    a_a.regenerate()

    fix_face_a = inst_a.faces.findAt(((5.0, 5.0, 0.0), ))
    a_a.Set(name='FixFace', faces=fix_face_a)
    tip_nodes_a = inst_a.nodes.getByBoundingBox(xMin=-1.0, xMax=11.0, yMin=-1.0, yMax=11.0, zMin=99.0, zMax=101.0)
    a_a.Set(name='TipNodes', nodes=tip_nodes_a)

    m_a.StaticStep(name='Step-1', previous='Initial')
    m_a.DisplacementBC(name='FixBC', createStepName='Initial', region=a_a.sets['FixFace'],
                       u1=0.0, u2=0.0, u3=0.0)

    # Applied CF in -Y: total 1000 N distributed across tip nodes
    node_count_a = len(tip_nodes_a)
    cf_per_node = -1000.0 / float(node_count_a)
    m_a.ConcentratedForce(name='TipCF', createStepName='Step-1',
                          region=a_a.sets['TipNodes'], cf2=cf_per_node)

    job_a = mdb.Job(name='Tier2_CaseA_Job', model='Model-1', description='Case A CF Balance')
    job_a.writeInput()
    job_a.submit(consistencyChecking=OFF)
    job_a.waitForCompletion()

    odb_a = odbAccess.openOdb('Tier2_CaseA_Job.odb')
    step_a = odb_a.steps['Step-1']
    frame_a = step_a.frames[-1]
    rf_field_a = frame_a.fieldOutputs['RF']
    
    # Get fix face node labels (at Z = 0.0)
    fix_labels_a = set()
    for inst_obj in odb_a.rootAssembly.instances.values():
        for n in inst_obj.nodes:
            if abs(n.coordinates[2]) < 1e-3:
                fix_labels_a.add(n.label)
    
    sum_rf2_a = 0.0
    for val in rf_field_a.values:
        if val.nodeLabel in fix_labels_a:
            sum_rf2_a += float(val.data[1])
    odb_a.close()

    total_applied_cf = -1000.0
    cf_residual = sum_rf2_a + total_applied_cf
    rel_error_a = abs(cf_residual) / abs(total_applied_cf)
    report["case_a_cf_equilibrium"] = {
        "applied_cf2": total_applied_cf,
        "sum_reaction_rf2": sum_rf2_a,
        "residual": cf_residual,
        "relative_error": rel_error_a,
        "balanced": (rel_error_a < 1e-4)
    }

    # =========================================================================
    # CASE B: Surface Pressure Equilibrium
    # =========================================================================
    Mdb()
    m_b = mdb.models['Model-1']
    s_b = m_b.ConstrainedSketch(name='sketch_b', sheetSize=100.0)
    s_b.rectangle(point1=(0.0, 0.0), point2=(10.0, 10.0))
    p_b = m_b.Part(name='BeamB', dimensionality=THREE_D, type=DEFORMABLE_BODY)
    p_b.BaseSolidExtrude(sketch=s_b, depth=100.0)

    mat_b = m_b.Material(name='Steel')
    mat_b.Elastic(table=((210000.0, 0.3), ))
    m_b.HomogeneousSolidSection(name='SolidB', material='Steel', thickness=None)
    p_b.SectionAssignment(region=(p_b.cells, ), sectionName='SolidB')

    a_b = m_b.rootAssembly
    inst_b = a_b.Instance(name='BeamB-1', part=p_b, dependent=ON)
    p_b.seedPart(size=10.0, deviationFactor=0.1, minSizeFactor=0.1)
    p_b.generateMesh()
    a_b.regenerate()

    # Fixed face at Z=0
    fix_face_b = inst_b.faces.findAt(((5.0, 5.0, 0.0), ))
    a_b.Set(name='FixFace', faces=fix_face_b)
    # Top face at Y=10 (Area = 10 x 100 = 1000 mm^2)
    top_face_b = inst_b.faces.findAt(((5.0, 10.0, 50.0), ))
    a_b.Surface(name='TopSurf', side1Faces=top_face_b)

    m_b.StaticStep(name='Step-1', previous='Initial')
    m_b.DisplacementBC(name='FixBC', createStepName='Initial', region=a_b.sets['FixFace'],
                       u1=0.0, u2=0.0, u3=0.0)
    # Apply pressure P = 2.0 MPa downwards on TopSurf -> Total load in Y = -2000 N
    m_b.Pressure(name='TopPressure', createStepName='Step-1',
                   region=a_b.surfaces['TopSurf'], magnitude=2.0)

    job_b = mdb.Job(name='Tier2_CaseB_Job', model='Model-1', description='Case B Pressure Balance')
    job_b.writeInput()
    job_b.submit(consistencyChecking=OFF)
    job_b.waitForCompletion()

    odb_b = odbAccess.openOdb('Tier2_CaseB_Job.odb')
    step_b = odb_b.steps['Step-1']
    frame_b = step_b.frames[-1]
    rf_field_b = frame_b.fieldOutputs['RF']
    
    # Get fix face node labels (at Z = 0.0)
    fix_labels_b = set()
    for inst_obj in odb_b.rootAssembly.instances.values():
        for n in inst_obj.nodes:
            if abs(n.coordinates[2]) < 1e-3:
                fix_labels_b.add(n.label)

    sum_rf2_b = 0.0
    for val in rf_field_b.values:
        if val.nodeLabel in fix_labels_b:
            sum_rf2_b += float(val.data[1])
    odb_b.close()

    total_pressure_force = 2.0 * (10.0 * 100.0)  # 2000 N in Y
    # Reaction force opposes applied load: sum_rf2_b should be +2000 N
    pressure_residual = sum_rf2_b - total_pressure_force
    rel_error_b = abs(pressure_residual) / total_pressure_force
    report["case_b_pressure_equilibrium"] = {
        "pressure_magnitude": 2.0,
        "area_mm2": 1000.0,
        "expected_total_load": total_pressure_force,
        "sum_reaction_rf2": sum_rf2_b,
        "residual": pressure_residual,
        "relative_error": rel_error_b,
        "balanced": (rel_error_b < 1e-3)
    }

    # =========================================================================
    # CASE C: Steady-State Thermal Conduction
    # =========================================================================
    Mdb()
    m_c = mdb.models['Model-1']
    s_c = m_c.ConstrainedSketch(name='sketch_c', sheetSize=100.0)
    s_c.rectangle(point1=(0.0, 0.0), point2=(10.0, 10.0))
    p_c = m_c.Part(name='BarC', dimensionality=THREE_D, type=DEFORMABLE_BODY)
    p_c.BaseSolidExtrude(sketch=s_c, depth=100.0)

    mat_c = m_c.Material(name='ConductiveMat')
    mat_c.Conductivity(table=((45.0, ), ))
    m_c.HomogeneousSolidSection(name='SolidC', material='ConductiveMat', thickness=None)
    p_c.SectionAssignment(region=(p_c.cells, ), sectionName='SolidC')

    a_c = m_c.rootAssembly
    inst_c = a_c.Instance(name='BarC-1', part=p_c, dependent=ON)
    p_c.seedPart(size=10.0, deviationFactor=0.1, minSizeFactor=0.1)
    # Assign heat transfer element type DC3D8
    import mesh
    elemType = mesh.ElemType(elemCode=DC3D8, elemLibrary=STANDARD)
    p_c.setElementType(regions=(p_c.cells, ), elemTypes=(elemType, ))
    p_c.generateMesh()
    a_c.regenerate()

    face_cold = inst_c.faces.findAt(((5.0, 5.0, 0.0), ))
    face_hot = inst_c.faces.findAt(((5.0, 5.0, 100.0), ))
    a_c.Set(name='ColdEnd', faces=face_cold)
    a_c.Set(name='HotEnd', faces=face_hot)

    m_c.HeatTransferStep(name='ThermalStep', previous='Initial', response=STEADY_STATE)
    m_c.TemperatureBC(name='ColdBC', createStepName='ThermalStep',
                      region=a_c.sets['ColdEnd'], magnitude=20.0)
    m_c.TemperatureBC(name='HotBC', createStepName='ThermalStep',
                      region=a_c.sets['HotEnd'], magnitude=100.0)

    job_c = mdb.Job(name='Tier2_CaseC_Job', model='Model-1', description='Case C Steady Thermal')
    job_c.writeInput()
    job_c.submit(consistencyChecking=OFF)
    job_c.waitForCompletion()

    odb_c = odbAccess.openOdb('Tier2_CaseC_Job.odb')
    step_c = odb_c.steps['ThermalStep']
    frame_c = step_c.frames[-1]
    nt11_field = frame_c.fieldOutputs['NT11']
    
    # Query nodes near Z=50 (midpoint)
    mid_labels = set()
    for inst_obj in odb_c.rootAssembly.instances.values():
        for n in inst_obj.nodes:
            if abs(n.coordinates[2] - 50.0) < 1e-3:
                mid_labels.add(n.label)
    
    mid_temps = [float(val.data) for val in nt11_field.values if val.nodeLabel in mid_labels]
    avg_mid_temp = sum(mid_temps) / len(mid_temps) if mid_temps else 0.0
    odb_c.close()

    # Analytical midpoint temp = (100 + 20) / 2 = 60.0 C
    t_mid_error = abs(avg_mid_temp - 60.0) / 60.0
    report["case_c_thermal_gradient"] = {
        "t_cold_c": 20.0,
        "t_hot_c": 100.0,
        "analytical_mid_temp_c": 60.0,
        "simulated_mid_temp_c": avg_mid_temp,
        "relative_error": t_mid_error,
        "gradient_verified": (t_mid_error < 1e-3)
    }

    # =========================================================================
    # CASE E: Rigid-Body Under-Constrained Model (Singularity Detection)
    # =========================================================================
    Mdb()
    m_e = mdb.models['Model-1']
    s_e = m_e.ConstrainedSketch(name='sketch_e', sheetSize=50.0)
    s_e.rectangle(point1=(0.0, 0.0), point2=(10.0, 10.0))
    p_e = m_e.Part(name='BlockE', dimensionality=THREE_D, type=DEFORMABLE_BODY)
    p_e.BaseSolidExtrude(sketch=s_e, depth=20.0)

    mat_e = m_e.Material(name='Steel')
    mat_e.Elastic(table=((210000.0, 0.3), ))
    m_e.HomogeneousSolidSection(name='SolidE', material='Steel', thickness=None)
    p_e.SectionAssignment(region=(p_e.cells, ), sectionName='SolidE')

    a_e = m_e.rootAssembly
    inst_e = a_e.Instance(name='BlockE-1', part=p_e, dependent=ON)
    p_e.seedPart(size=10.0, deviationFactor=0.1, minSizeFactor=0.1)
    p_e.generateMesh()
    a_e.regenerate()

    m_e.StaticStep(name='Step-1', previous='Initial')
    # Apply load WITHOUT any BC -> 6 rigid body modes
    tip_e = inst_e.faces.findAt(((5.0, 5.0, 20.0), ))
    a_e.Surface(name='TopE', side1Faces=tip_e)
    m_e.Pressure(name='FreePressure', createStepName='Step-1',
                 region=a_e.surfaces['TopE'], magnitude=1.0)

    job_e = mdb.Job(name='Tier2_CaseE_Job', model='Model-1', description='Case E Singularity')
    job_e.writeInput()
    job_e.submit(consistencyChecking=OFF)
    job_e.waitForCompletion()

    # Inspect .msg file for numerical singularity / zero pivot
    msg_path = 'Tier2_CaseE_Job.msg'
    singularity_detected = False
    singularity_matches = []
    if os.path.exists(msg_path):
        with open(msg_path, 'r') as mf:
            content = mf.read()
            for pattern in ['NUMERICAL SINGULARITY', 'ZERO PIVOT', 'SOLVER PROBLEM']:
                if pattern in content:
                    singularity_detected = True
                    singularity_matches.append(pattern)

    report["case_e_singularity_detection"] = {
        "job_status": str(job_e.status),
        "singularity_detected": singularity_detected,
        "matched_diagnostics": singularity_matches,
        "verified": singularity_detected
    }

    # Evaluate Overall Status
    passed = (
        report["case_a_cf_equilibrium"].get("balanced", False) and
        report["case_b_pressure_equilibrium"].get("balanced", False) and
        report["case_c_thermal_gradient"].get("gradient_verified", False) and
        report["case_e_singularity_detection"].get("verified", False)
    )
    report["passed"] = bool(passed)

except Exception as err:
    report["passed"] = False
    report["diagnostics"].append(str(err))

with open('%s', 'w') as f:
    json.dump(report, f, indent=2)

print("__TIER2_RESULT__=" + json.dumps({"passed": report["passed"]}))
''' % (result_json_escaped)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tier 2 Real-Machine BC/Load Equivalence Live Validation")
    parser.add_argument("--launcher", default=os.environ.get("ABAQUS_COMMAND", "abaqus"))
    parser.add_argument("--workdir", default=os.path.join(str(ROOT), "runs", "tier2_workdir"))
    parser.add_argument("--job-name", default="Tier2_LiveValidation")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)

    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # CASE D: Host-Side Structural Conflict Preflight Test
    # =========================================================================
    print("--- [Step 1] Testing Case D: Structural Conflict Preflight Interception ---")
    act_fix = fixed_bc("Model-1", "BC-Fix", "a.sets['EndFace']", step="Step-1")
    act_disp = displacement_bc("Model-1", "BC-Move", "a.sets['EndFace']", step="Step-1", u1=5.0)
    
    preflight_res = preflight_plan([act_fix, act_disp])
    conflict_detected = not preflight_res.passed and any(
        b.get("name") == "bc_structural_conflict" for b in preflight_res.blockers
    )
    print(f"  Preflight check passed: {preflight_res.passed}")
    print(f"  Preflight blockers detected: {preflight_res.blockers}")
    assert conflict_detected, "Case D structural conflict was not intercepted by preflight!"
    print("  Case D structural conflict preflight: PASS")

    # =========================================================================
    # CASES A, B, C, E: Live Abaqus Execution
    # =========================================================================
    print("\n--- [Step 2] Executing Live Abaqus 2025 Tier 2 Script (Cases A, B, C, E) ---")
    script_path = workdir / f"{args.job_name}_script.py"
    evidence_json = ROOT / "machine_validation" / "tier2_bc_load_evidence.json"

    script_content = build_tier2_abaqus_script(
        str(workdir).replace("\\", "/"),
        str(evidence_json).replace("\\", "/"),
    )
    script_path.write_text(script_content, encoding="utf-8")

    executor = BatchExecutor(
        launcher=args.launcher,
        workdir=str(workdir),
        timeout=args.timeout,
    )
    process = executor.run_nogui(str(script_path), timeout=args.timeout)
    print(f"  Abaqus process return code: {process.return_code}")

    if not evidence_json.is_file():
        print(f"ERROR: Evidence JSON was not generated at {evidence_json}")
        print("STDOUT:\n", process.stdout)
        print("STDERR:\n", process.stderr)
        return 1

    with open(evidence_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Attach Case D and provenance
    data["case_d_structural_conflict"] = {
        "preflight_passed": preflight_res.passed,
        "blockers_caught": list(preflight_res.blockers),
        "verified": conflict_detected,
    }
    data["provenance"] = {
        "launcher": args.launcher,
        "workdir": str(workdir),
        "return_code": process.return_code,
        "solver": "Abaqus/Standard 2025",
    }
    overall_passed = data.get("passed", False) and conflict_detected
    data["passed"] = overall_passed

    with open(evidence_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print("\n--- [Step 3] Tier 2 Real-Machine Evidence Summary ---")
    print("  Case A (CF Balance):", json.dumps(data.get("case_a_cf_equilibrium", {}), indent=2))
    print("  Case B (Pressure Balance):", json.dumps(data.get("case_b_pressure_equilibrium", {}), indent=2))
    print("  Case C (Thermal Gradient):", json.dumps(data.get("case_c_thermal_gradient", {}), indent=2))
    print("  Case D (Structural Conflict):", json.dumps(data.get("case_d_structural_conflict", {}), indent=2))
    print("  Case E (Singularity Detection):", json.dumps(data.get("case_e_singularity_detection", {}), indent=2))
    print(f"\n  Tier 2 Overall Result: {'PASS' if overall_passed else 'FAIL'}")
    print(f"  Evidence File: {evidence_json}")

    return 0 if overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())
