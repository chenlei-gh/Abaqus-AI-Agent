#!/usr/bin/env python3
"""Tier 3 Live Real-Machine Validation: UnitSystem Physical Invariance.

Builds and runs two physically identical models in live Abaqus 2025:
- Model 1: MM_N_MPA (b=10mm, h=10mm, L=100mm, E=210000MPa, F=1000N)
- Model 2: SI / M_N_PA (b=0.01m, h=0.01m, L=0.1m, E=2.1e11Pa, F=1000N)

Verifies:
1. Converted Mises stress: sigma_SI / 1e6 == sigma_MM_N_MPA (relative error < 1e-4).
2. Converted displacement: U_SI * 1e3 == U_MM_N_MPA (relative error < 1e-4).
3. Non-dimensional equivalent plastic/elastic strain equality.
4. Host-side UnitSystem schema validation and consistency checking.
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
from abaqus_ai_agent.contracts.units import UnitSystem, validate_quantity_unit


def build_tier3_abaqus_script(result_json_escaped: str) -> str:
    """Build Abaqus CAE noGUI script for UnitSystem invariance."""
    return '''# -*- coding: mbcs -*-
import sys
import json
import math
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
    "tier": "Tier 3: UnitSystem Physical Invariance",
    "model_mm_n_mpa": {},
    "model_si_m_n_pa": {},
    "comparison": {},
    "passed": False,
    "diagnostics": []
}

def extract_max_fields(odb_name):
    odb = odbAccess.openOdb(odb_name)
    step1 = odb.steps['Step-1']
    frame = step1.frames[-1]
    
    s_field = frame.fieldOutputs['S']
    max_mises = 0.0
    for val in s_field.values:
        if val.mises is not None and val.mises > max_mises:
            max_mises = float(val.mises)
            
    u_field = frame.fieldOutputs['U']
    max_u = 0.0
    for val in u_field.values:
        if val.magnitude is not None and val.magnitude > max_u:
            max_u = float(val.magnitude)
            
    e_field = frame.fieldOutputs['E']
    max_e_mag = 0.0
    for val in e_field.values:
        # Principal or max component of strain
        if val.data is not None:
            comp_max = max(abs(float(x)) for x in val.data)
            if comp_max > max_e_mag:
                max_e_mag = comp_max
                
    odb.close()
    return max_mises, max_u, max_e_mag

try:
    # =========================================================================
    # MODEL 1: MM_N_MPA (mm, N, MPa, s)
    # =========================================================================
    Mdb()
    m1 = mdb.models['Model-1']
    s1 = m1.ConstrainedSketch(name='sketch1', sheetSize=200.0)
    s1.rectangle(point1=(0.0, 0.0), point2=(10.0, 10.0))
    p1 = m1.Part(name='BeamMM', dimensionality=THREE_D, type=DEFORMABLE_BODY)
    p1.BaseSolidExtrude(sketch=s1, depth=100.0)

    mat1 = m1.Material(name='SteelMM')
    mat1.Elastic(table=((210000.0, 0.3), ))
    m1.HomogeneousSolidSection(name='SolidSecMM', material='SteelMM', thickness=None)
    p1.SectionAssignment(region=(p1.cells, ), sectionName='SolidSecMM')

    a1 = m1.rootAssembly
    inst1 = a1.Instance(name='BeamMM-1', part=p1, dependent=ON)
    p1.seedPart(size=10.0, deviationFactor=0.1, minSizeFactor=0.1)
    p1.generateMesh()
    a1.regenerate()

    fix_face1 = inst1.faces.findAt(((5.0, 5.0, 0.0), ))
    a1.Set(name='FixEnd', faces=fix_face1)
    tip_nodes1 = inst1.nodes.getByBoundingBox(xMin=-1.0, xMax=11.0, yMin=-1.0, yMax=11.0, zMin=99.0, zMax=101.0)
    a1.Set(name='TipNodes', nodes=tip_nodes1)

    m1.StaticStep(name='Step-1', previous='Initial')
    m1.DisplacementBC(name='FixBC', createStepName='Initial', region=a1.sets['FixEnd'],
                      u1=0.0, u2=0.0, u3=0.0)
    cf_per_node1 = -1000.0 / float(len(tip_nodes1))
    m1.ConcentratedForce(name='TipLoad', createStepName='Step-1',
                         region=a1.sets['TipNodes'], cf2=cf_per_node1)

    job1 = mdb.Job(name='Tier3_MM_Job', model='Model-1', description='Tier 3 MM_N_MPA')
    job1.writeInput()
    job1.submit(consistencyChecking=OFF)
    job1.waitForCompletion()

    mises1, u1, e1 = extract_max_fields('Tier3_MM_Job.odb')
    report["model_mm_n_mpa"] = {
        "unit_system": "MM_N_MPA",
        "length_mm": 100.0,
        "width_mm": 10.0,
        "height_mm": 10.0,
        "modulus_mpa": 210000.0,
        "load_n": -1000.0,
        "max_mises_mpa": mises1,
        "max_displacement_mm": u1,
        "max_strain": e1
    }

    # =========================================================================
    # MODEL 2: SI / M_N_PA (m, N, Pa, s)
    # =========================================================================
    Mdb()
    m2 = mdb.models['Model-1']
    s2 = m2.ConstrainedSketch(name='sketch2', sheetSize=2.0)
    s2.rectangle(point1=(0.0, 0.0), point2=(0.01, 0.01))
    p2 = m2.Part(name='BeamSI', dimensionality=THREE_D, type=DEFORMABLE_BODY)
    p2.BaseSolidExtrude(sketch=s2, depth=0.1)

    mat2 = m2.Material(name='SteelSI')
    mat2.Elastic(table=((2.1e11, 0.3), ))
    m2.HomogeneousSolidSection(name='SolidSecSI', material='SteelSI', thickness=None)
    p2.SectionAssignment(region=(p2.cells, ), sectionName='SolidSecSI')

    a2 = m2.rootAssembly
    inst2 = a2.Instance(name='BeamSI-1', part=p2, dependent=ON)
    p2.seedPart(size=0.01, deviationFactor=0.1, minSizeFactor=0.1)
    p2.generateMesh()
    a2.regenerate()

    fix_face2 = inst2.faces.findAt(((0.005, 0.005, 0.0), ))
    a2.Set(name='FixEnd', faces=fix_face2)
    tip_nodes2 = inst2.nodes.getByBoundingBox(xMin=-0.001, xMax=0.011, yMin=-0.001, yMax=0.011, zMin=0.099, zMax=0.101)
    a2.Set(name='TipNodes', nodes=tip_nodes2)

    m2.StaticStep(name='Step-1', previous='Initial')
    m2.DisplacementBC(name='FixBC', createStepName='Initial', region=a2.sets['FixEnd'],
                      u1=0.0, u2=0.0, u3=0.0)
    cf_per_node2 = -1000.0 / float(len(tip_nodes2))
    m2.ConcentratedForce(name='TipLoad', createStepName='Step-1',
                         region=a2.sets['TipNodes'], cf2=cf_per_node2)

    job2 = mdb.Job(name='Tier3_SI_Job', model='Model-1', description='Tier 3 SI')
    job2.writeInput()
    job2.submit(consistencyChecking=OFF)
    job2.waitForCompletion()

    mises2, u2, e2 = extract_max_fields('Tier3_SI_Job.odb')
    report["model_si_m_n_pa"] = {
        "unit_system": "SI",
        "length_m": 0.1,
        "width_m": 0.01,
        "height_m": 0.01,
        "modulus_pa": 2.1e11,
        "load_n": -1000.0,
        "max_mises_pa": mises2,
        "max_displacement_m": u2,
        "max_strain": e2
    }

    # =========================================================================
    # COMPARISON & INVARIANCE CHECK
    # =========================================================================
    # 1. Stress: Pa / 1e6 -> MPa
    converted_mises_si_to_mpa = mises2 / 1.0e6
    stress_diff = abs(converted_mises_si_to_mpa - mises1)
    rel_stress_err = stress_diff / mises1 if mises1 > 0 else 0.0

    # 2. Displacement: m * 1000 -> mm
    converted_u_si_to_mm = u2 * 1000.0
    u_diff = abs(converted_u_si_to_mm - u1)
    rel_u_err = u_diff / u1 if u1 > 0 else 0.0

    # 3. Strain: non-dimensional
    strain_diff = abs(e2 - e1)
    rel_strain_err = strain_diff / e1 if e1 > 0 else 0.0

    stress_match = (rel_stress_err < 1.0e-4)
    disp_match = (rel_u_err < 1.0e-4)
    strain_match = (rel_strain_err < 1.0e-4)

    report["comparison"] = {
        "mises_mm_mpa": mises1,
        "mises_si_converted_mpa": converted_mises_si_to_mpa,
        "stress_rel_error": rel_stress_err,
        "stress_invariance_passed": stress_match,

        "u_mm": u1,
        "u_si_converted_mm": converted_u_si_to_mm,
        "displacement_rel_error": rel_u_err,
        "displacement_invariance_passed": disp_match,

        "strain_mm": e1,
        "strain_si": e2,
        "strain_rel_error": rel_strain_err,
        "strain_invariance_passed": strain_match,
    }

    report["passed"] = bool(stress_match and disp_match and strain_match)

except Exception as err:
    report["passed"] = False
    report["diagnostics"].append(str(err))

with open('%s', 'w') as f:
    json.dump(report, f, indent=2)

print("__TIER3_RESULT__=" + json.dumps({"passed": report["passed"]}))
''' % (result_json_escaped)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tier 3 Real-Machine UnitSystem Invariance Live Validation")
    parser.add_argument("--launcher", default=os.environ.get("ABAQUS_COMMAND", "abaqus"))
    parser.add_argument("--workdir", default=os.path.join(str(ROOT), "machine_validation"))
    parser.add_argument("--job-name", default="Tier3_LiveValidation")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)

    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    # 1. Host-side UnitSystem contracts validation
    print("--- [Step 1] Testing Host-Side UnitSystem Declarations ---")
    u_mm = UnitSystem.named("MM_N_MPA")
    assert u_mm.unit("length") == "mm"
    assert u_mm.unit("stress") == "MPa"
    assert u_mm.unit("force") == "N"

    u_si = UnitSystem.named("SI")
    assert u_si.unit("length") == "m"
    assert u_si.unit("stress") == "Pa"
    assert u_si.unit("force") == "N"

    # Validate quantity checking: quantity, unit, unit_system
    assert validate_quantity_unit("stress", "MPa", "MM_N_MPA") is True
    assert validate_quantity_unit("stress", "Pa", "SI") is True
    print("  Host-side UnitSystem schema and unit checking: PASS")

    # 2. Run Abaqus dual-model simulation
    print("\n--- [Step 2] Executing Live Abaqus 2025 Tier 3 Dual-Model Script ---")
    script_path = workdir / f"{args.job_name}_script.py"
    evidence_json = workdir / "tier3_unit_system_evidence.json"

    script_content = build_tier3_abaqus_script(str(evidence_json).replace("\\", "/"))
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

    data["provenance"] = {
        "launcher": args.launcher,
        "workdir": str(workdir),
        "return_code": process.return_code,
        "solver": "Abaqus/Standard 2025",
        "dual_models_run": ["Tier3_MM_Job", "Tier3_SI_Job"],
    }

    with open(evidence_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print("\n--- [Step 3] Tier 3 Real-Machine Evidence Summary ---")
    print("  MM_N_MPA Model Result:", json.dumps(data.get("model_mm_n_mpa", {}), indent=2))
    print("  SI / M_N_PA Model Result:", json.dumps(data.get("model_si_m_n_pa", {}), indent=2))
    print("  Comparison & Invariance:", json.dumps(data.get("comparison", {}), indent=2))
    print(f"\n  Tier 3 Overall Result: {'PASS' if data.get('passed') else 'FAIL'}")
    print(f"  Evidence File: {evidence_json}")

    return 0 if data.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
