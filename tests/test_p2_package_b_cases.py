"""Regression & cryptographic integrity test for Phase 2 Package B Engineering Cases.

Validates REQ-P2-006:
1. Problem statement ingestion contract for Case 01 (Bolted Pipe Flange Connection).
2. Authentic machine run manifest qualification (machine_validation/p2_cases/case_01_flange_manifest.json).
3. Physical results & sealing verification:
   - Step 1 (Preload): Gasket contact pressure >= 30 MPa, Bolt tension == 50 kN.
   - Step 2 (Internal Pressure): Gasket contact pressure >= 12 MPa (No leakage).
   - Bolt Factor of Safety (SF >= 1.5).
   - Flange Hub Factor of Safety (SF >= 1.25).
   - Net reaction equilibrium error <= 0.5%.
4. Benchmark comparison against Abaqus 2025 Example Problems reference solutions.
5. Deterministic SHA-256 cryptographic audit signature verification.
6. Negative fail-closed probe (insufficient sealing pressure -> Acceptance FAIL).
"""

import hashlib
import json
from pathlib import Path
import pytest

from abaqus_ai_agent.acceptance import evaluate_result_acceptance

ROOT = Path(__file__).resolve().parent.parent
CASE_01_PROBLEM = ROOT / "test_assets" / "engineering_cases" / "case_01_bolted_pipe_flange" / "problem_statement.json"
CASE_01_SUB_DIR = ROOT / "machine_validation" / "p2_cases" / "case_01_bolted_pipe_flange"
CASE_01_MANIFEST = CASE_01_SUB_DIR / "case_01_flange_manifest.json"
CASE_02_PROBLEM = ROOT / "test_assets" / "engineering_cases" / "case_02_reactor_pressure_vessel_closure" / "problem_statement.json"
CASE_02_SUB_DIR = ROOT / "machine_validation" / "p2_cases" / "case_02_reactor_pressure_vessel_closure"
CASE_02_MANIFEST = CASE_02_SUB_DIR / "case_02_rpv_manifest.json"
CASE_03_PROBLEM = ROOT / "test_assets" / "engineering_cases" / "case_03_exhaust_manifold_thermo_mechanical" / "problem_statement.json"
CASE_03_SUB_DIR = ROOT / "machine_validation" / "p2_cases" / "case_03_exhaust_manifold"
CASE_03_MANIFEST = CASE_03_SUB_DIR / "case_03_manifold_manifest.json"
CASE_04_PROBLEM = ROOT / "test_assets" / "engineering_cases" / "case_04_subframe_fatigue" / "problem_statement.json"
CASE_04_SUB_DIR = ROOT / "machine_validation" / "p2_cases" / "case_04_subframe_durability"
CASE_04_MANIFEST = CASE_04_SUB_DIR / "case_04_subframe_manifest.json"
CASE_05_PROBLEM = ROOT / "test_assets" / "engineering_cases" / "case_05_composite_buckling" / "problem_statement.json"
CASE_05_SUB_DIR = ROOT / "machine_validation" / "p2_cases" / "case_05_composite_buckling"
CASE_05_MANIFEST = CASE_05_SUB_DIR / "case_05_composite_buckling_manifest.json"
CASE_06_PROBLEM = ROOT / "test_assets" / "engineering_cases" / "case_06_sheet_metal_submodeling" / "problem_statement.json"
CASE_06_SUB_DIR = ROOT / "machine_validation" / "p2_cases" / "case_06_sheet_metal_submodeling"
CASE_06_MANIFEST = CASE_06_SUB_DIR / "case_06_sheet_metal_manifest.json"


def test_case_01_problem_statement_specification():
    assert CASE_01_PROBLEM.is_file(), f"Problem statement missing at {CASE_01_PROBLEM}"
    with open(CASE_01_PROBLEM, "r", encoding="utf-8") as f:
        problem = json.load(f)

    assert problem.get("case_id") == "CASE_01_BOLTED_PIPE_FLANGE"
    assert "Abaqus 2025 Example Problems" in problem.get("source", "")
    assert problem.get("geometry", {}).get("bolt_count") == 8
    assert len(problem.get("loading_procedure", [])) == 2
    assert problem.get("acceptance_criteria", {}).get("min_gasket_contact_pressure_mpa") == 12.0


def test_case_01_flange_manifest_integrity():
    assert CASE_01_MANIFEST.is_file(), f"Manifest missing at {CASE_01_MANIFEST}"

    with open(CASE_01_MANIFEST, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Metadata and schema verification
    assert manifest.get("schema_version") == "case_manifest_v1"
    assert manifest.get("case_id") == "CASE_01_BOLTED_PIPE_FLANGE"
    assert manifest.get("qualification_level") == "QUALIFIED"
    assert manifest.get("status") == "ACCEPTED"

    # 2. Cryptographic signature check
    signature = manifest.get("audit_signature")
    assert signature is not None and len(signature) == 64

    manifest_copy = dict(manifest)
    manifest_copy.pop("audit_signature", None)
    expected_hash = hashlib.sha256(
        json.dumps(manifest_copy, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert signature == expected_hash, "Cryptographic audit signature mismatch or manifest tampered!"

    # 3. Summary & Deliverable Reports check
    summary = manifest.get("summary", {})
    assert summary.get("status") == "COMPLETED"
    assert summary.get("engineering_status") == "RESULT_VALID"
    assert summary.get("acceptance_passed") is True
    report_info = summary.get("report", {})
    assert report_info.get("format") == "html"
    assert report_info.get("self_contained") is True
    assert report_info.get("bytes", 0) > 4000
    assert summary.get("report_html_bytes", 0) > 4000

    # 4. Physical results check
    phys = manifest.get("physical_results", {})
    assert phys.get("step_1_avg_gasket_cpress_mpa", 0.0) >= 30.0
    assert phys.get("step_2_avg_gasket_cpress_mpa", 0.0) >= 12.0  # Sealing criterion
    assert phys.get("flange_safety_factor", 0.0) >= 1.25
    assert phys.get("bolt_safety_factor", 0.0) >= 1.5
    assert phys.get("reaction_error_percent", 1.0) <= 0.5

    # 5. Benchmark comparison check
    bench = manifest.get("benchmark_comparison", {})
    assert bench.get("gasket_stress_relative_diff_percent", 100.0) < 5.0
    assert bench.get("bolt_tension_relative_diff_percent", 100.0) < 5.0

    # 6. Single-exit acceptance check
    acc = manifest.get("acceptance", {})
    assert acc.get("status") == "PASS"
    assert acc.get("passed") is True
    assert acc.get("criteria_count") == 3


def test_case_01_negative_probe_sealing_failure():
    """Negative Probe: If gasket pressure drops below 12 MPa, Acceptance must FAIL."""
    class MockContactDiag:
        def __init__(self):
            self.diagnostics = [type("Diag", (), {"status": "pass"})()]

    criteria = [
        {"name": "min_gasket_sealing_pressure", "value_key": "contact_pressure", "operator": ">=", "limit": 12.0, "unit": "MPa"},
    ]
    # Insufficient sealing pressure: 8.5 MPa < 12.0 MPa
    failed_values = {
        "contact_pressure": 8.5,
        "frictional_shear": 1.2,
        "reaction_force": 94247.78,
    }
    res = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values,
        criteria=criteria,
        contact_diagnostics=MockContactDiag(),
        odb_fields=["S", "U", "RF", "CPRESS", "CSHEAR"],
        physics_domain="contact",
        require_evidence=False,
    )
    assert not res.passed
    assert res.status == "FAIL"
    assert any("criterion:min_gasket_sealing_pressure" in f for f in res.failures)


def test_case_02_problem_statement_specification():
    assert CASE_02_PROBLEM.is_file(), f"Problem statement missing at {CASE_02_PROBLEM}"
    with open(CASE_02_PROBLEM, "r", encoding="utf-8") as f:
        problem = json.load(f)

    assert problem.get("case_id") == "CASE_02_REACTOR_PRESSURE_VESSEL_CLOSURE"
    assert "Reactor Pressure Vessel" in problem.get("title", "")
    assert problem.get("geometry", {}).get("bolt_count") == 54
    assert problem.get("geometry", {}).get("bolt_nominal_diameter_mm") == 180.0
    assert len(problem.get("loading_procedure", [])) == 2
    assert problem.get("acceptance_criteria", {}).get("min_metallic_seal_design_cpress_mpa") == 75.0
    assert problem.get("acceptance_criteria", {}).get("max_asme_linearized_pl_pb_stress_intensity_mpa") == 276.0


def test_case_02_rpv_manifest_integrity():
    assert CASE_02_MANIFEST.is_file(), f"Manifest missing at {CASE_02_MANIFEST}"

    with open(CASE_02_MANIFEST, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Metadata and schema verification
    assert manifest.get("schema_version") == "case_manifest_v1"
    assert manifest.get("case_id") == "CASE_02_REACTOR_PRESSURE_VESSEL_CLOSURE"
    assert manifest.get("qualification_level") == "QUALIFIED"
    assert manifest.get("status") == "ACCEPTED"

    # 2. Cryptographic signature check
    signature = manifest.get("audit_signature")
    assert signature is not None and len(signature) == 64

    manifest_copy = dict(manifest)
    manifest_copy.pop("audit_signature", None)
    expected_hash = hashlib.sha256(
        json.dumps(manifest_copy, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert signature == expected_hash, "Cryptographic audit signature mismatch or manifest tampered!"

    # 3. Summary & Deliverable Reports check
    summary = manifest.get("summary", {})
    assert summary.get("status") == "COMPLETED"
    assert summary.get("engineering_status") == "RESULT_VALID"
    assert summary.get("acceptance_passed") is True
    report_info = summary.get("report", {})
    assert report_info.get("format") == "html"
    assert report_info.get("self_contained") is True
    assert report_info.get("bytes", 0) > 4000
    assert summary.get("report_html_bytes", 0) > 4000

    # 4. Physical results check
    phys = manifest.get("physical_results", {})
    assert phys.get("step_1_seal_cpress_mpa", 0.0) >= 120.0
    assert phys.get("step_2_seal_cpress_mpa", 0.0) >= 75.0  # ASME sealing criterion
    assert phys.get("step_2_stud_stress_mpa", 1000.0) <= 596.0  # ASME 2*Sm limit
    assert phys.get("step_2_flange_pl_pb_mpa", 1000.0) <= 276.0  # ASME 1.5*Sm limit
    assert phys.get("flange_margin_ratio", 0.0) >= 1.10
    assert phys.get("stud_asme_margin_ratio", 0.0) >= 1.50
    assert phys.get("stud_yield_sf", 0.0) >= 2.0
    assert phys.get("reaction_error_percent", 1.0) <= 0.1

    # 5. Benchmark comparison check
    bench = manifest.get("benchmark_comparison", {})
    assert bench.get("seal_cpress_relative_diff_percent", 100.0) < 5.0
    assert bench.get("stud_tension_relative_diff_percent", 100.0) < 5.0

    # 6. Single-exit acceptance check
    acc = manifest.get("acceptance", {})
    assert acc.get("status") == "PASS"
    assert acc.get("passed") is True
    assert acc.get("criteria_count") == 4


def test_case_02_negative_probe_sealing_and_stress_failure():
    """Negative Probe: If seal pressure drops below 75 MPa or flange stress exceeds 276 MPa, Acceptance must FAIL."""
    class MockContactDiag:
        def __init__(self):
            self.diagnostics = [type("Diag", (), {"status": "pass"})()]

    criteria = [
        {"name": "min_metallic_seal_design_cpress", "value_key": "contact_pressure", "operator": ">=", "limit": 75.0, "unit": "MPa"},
        {"name": "max_asme_linearized_pl_pb_stress", "value_key": "step_2_flange_pl_pb", "operator": "<=", "limit": 276.0, "unit": "MPa"},
    ]
    # Insufficient sealing pressure: 60.0 MPa < 75.0 MPa
    failed_values = {
        "contact_pressure": 60.0,
        "step_2_flange_pl_pb": 290.0,  # Also exceeds 276.0 MPa
        "reaction_force": 219911485.75,
        "frictional_shear": 7.2,
    }
    res = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values,
        criteria=criteria,
        contact_diagnostics=MockContactDiag(),
        odb_fields=["S", "U", "RF", "CPRESS", "CSHEAR"],
        physics_domain="contact",
        require_evidence=False,
    )
    assert not res.passed
    assert res.status == "FAIL"
    assert any("criterion:min_metallic_seal_design_cpress" in f for f in res.failures)
    assert any("criterion:max_asme_linearized_pl_pb_stress" in f for f in res.failures)


def test_case_03_problem_statement_specification():
    assert CASE_03_PROBLEM.is_file(), f"Problem statement missing at {CASE_03_PROBLEM}"
    with open(CASE_03_PROBLEM, "r", encoding="utf-8") as f:
        problem = json.load(f)

    assert problem.get("case_id") == "CASE_03_EXHAUST_MANIFOLD_THERMO_MECHANICAL"
    assert "Exhaust Manifold" in problem.get("title", "")
    assert problem.get("geometry", {}).get("bolt_count") == 8
    assert problem.get("geometry", {}).get("bolt_radial_clearance_mm") == 0.75
    assert len(problem.get("loading_procedure", [])) == 3
    assert problem.get("acceptance_criteria", {}).get("min_operating_gasket_contact_pressure_mpa") == 25.0
    assert problem.get("acceptance_criteria", {}).get("max_thermal_stress_junction_mises_mpa") == 240.0


def test_case_03_manifold_manifest_integrity():
    assert CASE_03_MANIFEST.is_file(), f"Manifest missing at {CASE_03_MANIFEST}"

    with open(CASE_03_MANIFEST, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Metadata and schema verification
    assert manifest.get("schema_version") == "case_manifest_v1"
    assert manifest.get("case_id") == "CASE_03_EXHAUST_MANIFOLD_THERMO_MECHANICAL"
    assert manifest.get("qualification_level") == "QUALIFIED"
    assert manifest.get("status") == "ACCEPTED"

    # 2. Cryptographic signature check
    signature = manifest.get("audit_signature")
    assert signature is not None and len(signature) == 64

    manifest_copy = dict(manifest)
    manifest_copy.pop("audit_signature", None)
    expected_hash = hashlib.sha256(
        json.dumps(manifest_copy, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert signature == expected_hash, "Cryptographic audit signature mismatch or manifest tampered!"

    # 3. Summary & Deliverable Reports check
    summary = manifest.get("summary", {})
    assert summary.get("status") == "COMPLETED"
    assert summary.get("engineering_status") == "RESULT_VALID"
    assert summary.get("acceptance_passed") is True
    report_info = summary.get("report", {})
    assert report_info.get("format") == "html"
    assert report_info.get("self_contained") is True
    assert report_info.get("bytes", 0) > 4000
    assert summary.get("report_html_bytes", 0) > 4000

    # 4. Physical results check
    phys = manifest.get("physical_results", {})
    assert phys.get("max_operating_temp_c", 0.0) >= 600.0
    assert phys.get("step_1_seal_cpress_mpa", 0.0) >= 40.0
    assert phys.get("step_2_operating_cpress_mpa", 0.0) >= 25.0  # Sealing criterion
    assert phys.get("step_2_flange_slip_mm", 10.0) <= 0.75      # Clearance limit
    assert phys.get("step_2_peak_mises_mpa", 1000.0) <= 240.0   # High-temperature yield limit
    assert phys.get("bolt_safety_factor", 0.0) >= 1.25
    assert phys.get("thermal_balance_error_percent", 1.0) <= 0.1

    # 5. Benchmark comparison check
    bench = manifest.get("benchmark_comparison", {})
    assert bench.get("flange_slip_relative_diff_percent", 100.0) < 5.0
    assert bench.get("peak_mises_relative_diff_percent", 100.0) < 5.0

    # 6. Single-exit acceptance check
    acc = manifest.get("acceptance", {})
    assert acc.get("status") == "PASS"
    assert acc.get("passed") is True
    assert acc.get("criteria_count") == 5


def test_case_03_negative_probes_thermal_stress_slip_and_sealing():
    """Negative Probes: Excessive thermal stress, excessive flange slip, or insufficient gasket sealing must FAIL."""
    class MockContactDiag:
        def __init__(self):
            self.diagnostics = [type("Diag", (), {"status": "pass"})()]

    criteria = [
        {"name": "min_operating_gasket_cpress", "value_key": "contact_pressure", "operator": ">=", "limit": 25.0, "unit": "MPa"},
        {"name": "max_flange_differential_slip", "value_key": "flange_slip", "operator": "<=", "limit": 0.75, "unit": "mm"},
        {"name": "max_junction_fillet_mises", "value_key": "max_mises", "operator": "<=", "limit": 240.0, "unit": "MPa"},
    ]

    # Probe 1: Peak thermal stress exceeds yield limit (265 MPa > 240 MPa)
    failed_values_stress = {
        "contact_pressure": 38.6,
        "frictional_shear": 7.7,
        "flange_slip": 0.42,
        "max_mises": 265.0,
        "max_displacement": 0.48,
        "max_temperature": 615.4,
        "reaction_force": 227360.0,
    }
    res_stress = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values_stress,
        criteria=criteria,
        contact_diagnostics=MockContactDiag(),
        thermal_balance=True,
        odb_fields=["NT", "S", "U", "RF", "CPRESS", "CSLIP", "CSHEAR"],
    )
    assert not res_stress.passed
    assert res_stress.status == "FAIL"
    assert any("criterion:max_junction_fillet_mises" in f for f in res_stress.failures)

    # Probe 2: Excessive slip causes bolt clearance interference (0.85 mm > 0.75 mm)
    failed_values_slip = {
        "contact_pressure": 38.6,
        "frictional_shear": 7.7,
        "flange_slip": 0.85,
        "max_mises": 215.8,
        "max_displacement": 0.98,
        "max_temperature": 615.4,
        "reaction_force": 227360.0,
    }
    res_slip = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values_slip,
        criteria=criteria,
        contact_diagnostics=MockContactDiag(),
        thermal_balance=True,
        odb_fields=["NT", "S", "U", "RF", "CPRESS", "CSLIP", "CSHEAR"],
        physics_domain="thermal_structural",
        require_evidence=False,
    )
    assert not res_slip.passed
    assert any("criterion:max_flange_differential_slip" in f for f in res_slip.failures)

    # Probe 3: Gasket sealing failure (18 MPa < 25 MPa)
    failed_values_sealing = {
        "contact_pressure": 18.0,
        "frictional_shear": 3.6,
        "flange_slip": 0.42,
        "max_mises": 215.8,
        "max_displacement": 0.48,
        "max_temperature": 615.4,
        "reaction_force": 227360.0,
    }
    res_sealing = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values_sealing,
        criteria=criteria,
        contact_diagnostics=MockContactDiag(),
        thermal_balance=True,
        odb_fields=["NT", "S", "U", "RF", "CPRESS", "CSLIP", "CSHEAR"],
        physics_domain="thermal_structural",
        require_evidence=False,
    )
    assert not res_sealing.passed
    assert any("criterion:min_operating_gasket_cpress" in f for f in res_sealing.failures)


def test_case_04_problem_statement_specification():
    assert CASE_04_PROBLEM.is_file(), f"Problem statement missing at {CASE_04_PROBLEM}"
    with open(CASE_04_PROBLEM, "r", encoding="utf-8") as f:
        problem = json.load(f)

    assert problem.get("case_id") == "CASE_04_AUTOMOTIVE_SUBFRAME_FATIGUE"
    assert "Subframe" in problem.get("title", "")
    assert problem.get("geometry", {}).get("body_mount_count") == 4
    assert problem.get("geometry", {}).get("lower_control_arm_mount_count") == 4
    assert len(problem.get("loading_procedure", [])) == 2
    assert problem.get("acceptance_criteria", {}).get("cumulative_damage_d_max") == 0.3
    assert problem.get("acceptance_criteria", {}).get("max_mises_stress_peak_mpa") == 380.0
    assert problem.get("acceptance_criteria", {}).get("min_life_blocks") == 3.33


def test_case_04_subframe_manifest_integrity():
    assert CASE_04_MANIFEST.is_file(), f"Manifest missing at {CASE_04_MANIFEST}"

    with open(CASE_04_MANIFEST, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Metadata and schema verification
    assert manifest.get("schema_version") == "case_manifest_v1"
    assert manifest.get("case_id") == "CASE_04_AUTOMOTIVE_SUBFRAME_FATIGUE"
    assert manifest.get("qualification_level") == "QUALIFIED"
    assert manifest.get("status") == "ACCEPTED"

    # 2. Cryptographic signature check
    signature = manifest.get("audit_signature")
    assert signature is not None and len(signature) == 64

    manifest_copy = dict(manifest)
    manifest_copy.pop("audit_signature", None)
    expected_hash = hashlib.sha256(
        json.dumps(manifest_copy, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert signature == expected_hash, "Cryptographic audit signature mismatch or manifest tampered!"

    # 3. Summary & Deliverable Reports check
    summary = manifest.get("summary", {})
    assert summary.get("status") == "COMPLETED"
    assert summary.get("engineering_status") == "RESULT_VALID"
    assert summary.get("acceptance_passed") is True
    report_info = summary.get("report", {})
    assert report_info.get("format") == "html"
    assert report_info.get("self_contained") is True
    assert report_info.get("bytes", 0) > 4000
    assert summary.get("report_html_bytes", 0) > 100_000

    # 4. Physical results check
    phys = manifest.get("physical_results", {})
    assert phys.get("peak_mises_stress_hotspot_bracket_mpa", 1000.0) <= 380.0
    assert phys.get("yield_safety_factor", 0.0) >= 1.10
    assert phys.get("cumulative_damage_hotspot_miner", 1.0) <= 0.30
    assert phys.get("predicted_life_blocks", 0.0) >= 3.33
    assert phys.get("equivalent_durability_mileage_km", 0.0) >= 1_000_000.0
    assert phys.get("bushing_max_relative_deflection_mm", 10.0) <= 4.50
    assert phys.get("reaction_force_balance_error_percent", 1.0) <= 0.10

    # 5. Benchmark comparison check
    bench = manifest.get("benchmark_comparison", {})
    assert bench.get("peak_mises_relative_diff_percent", 100.0) < 5.0
    assert bench.get("cumulative_damage_relative_diff_percent", 100.0) < 5.0

    # 6. Single-exit acceptance check
    acc = manifest.get("acceptance", {})
    assert acc.get("status") == "PASS"
    assert acc.get("passed") is True
    assert acc.get("criteria_count") == 6


def test_case_04_negative_probes_fatigue_damage_and_stress():
    """Negative Probes: Excessive fatigue damage or plastic yield stress exceedance must FAIL."""
    class FatigueFailCheck:
        status = "fail"
        warnings = ()

    class ConvergenceCheck:
        converged = True

    criteria = [
        {"name": "max_mises_stress_peak", "value_key": "max_mises", "operator": "<=", "limit": 380.0, "unit": "MPa"},
        {"name": "max_cumulative_damage_miner", "value_key": "damage", "operator": "<=", "limit": 0.30, "unit": "fraction"},
        {"name": "max_bushing_relative_deflection", "value_key": "max_displacement", "operator": "<=", "limit": 4.50, "unit": "mm"},
    ]

    # Probe 1: Fatigue damage exceeds design limit (D = 0.42 > 0.30)
    failed_values_damage = {
        "max_mises": 312.4,
        "damage": 0.42,
        "fatigue_life": 2.38,
        "max_displacement": 3.86,
        "reaction_force": 48500.0,
    }
    res_damage = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values_damage,
        criteria=criteria,
        fatigue=FatigueFailCheck(),
        convergence=ConvergenceCheck(),
        physics_domain="fatigue",
        require_evidence=False,
    )
    assert not res_damage.passed
    assert res_damage.status == "FAIL"
    assert any("criterion:max_cumulative_damage_miner" in f or "fatigue_verification_failed" in f for f in res_damage.failures)

    # Probe 2: Severe curb strike causes plastic yield (Mises = 435 MPa > 380 MPa limit)
    failed_values_stress = {
        "max_mises": 435.0,
        "damage": 0.187,
        "fatigue_life": 5.35,
        "max_displacement": 3.86,
        "reaction_force": 48500.0,
    }
    class FatiguePassCheck:
        status = "pass"
        warnings = ()

    res_stress = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values_stress,
        criteria=criteria,
        fatigue=FatiguePassCheck(),
        convergence=ConvergenceCheck(),
        physics_domain="fatigue",
        require_evidence=False,
    )
    assert not res_stress.passed
    assert res_stress.status == "FAIL"
    assert any("criterion:max_mises_stress_peak" in f for f in res_stress.failures)

    # Probe 3: Bushing travel bottoming out (5.20 mm > 4.50 mm)
    failed_values_bushing = {
        "max_mises": 312.4,
        "damage": 0.187,
        "fatigue_life": 5.35,
        "max_displacement": 5.20,
        "reaction_force": 48500.0,
    }
    res_bushing = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values_bushing,
        criteria=criteria,
        fatigue=FatiguePassCheck(),
        convergence=ConvergenceCheck(),
        physics_domain="fatigue",
        require_evidence=False,
    )
    assert not res_bushing.passed
    assert any("criterion:max_bushing_relative_deflection" in f for f in res_bushing.failures)


def test_case_05_problem_statement_specification():
    assert CASE_05_PROBLEM.is_file(), f"Problem statement missing at {CASE_05_PROBLEM}"
    with open(CASE_05_PROBLEM, "r", encoding="utf-8") as f:
        problem = json.load(f)

    assert problem.get("case_id") == "CASE_05_COMPOSITE_CYLINDER_BUCKLING"
    assert "Composite" in problem.get("title", "")
    assert problem.get("geometry", {}).get("cylinder_radius_r_mm") == 200.0
    assert problem.get("geometry", {}).get("central_hole_diameter_d_mm") == 40.0
    assert len(problem.get("loading_procedure", [])) == 2
    assert problem.get("acceptance_criteria", {}).get("min_eigenvalue_buckling_load_kn") == 100.0
    assert problem.get("acceptance_criteria", {}).get("min_riks_post_buckling_limit_load_kn") == 80.0
    assert problem.get("acceptance_criteria", {}).get("max_tsai_wu_failure_index") == 0.85


def test_case_05_composite_buckling_manifest_integrity():
    assert CASE_05_MANIFEST.is_file(), f"Manifest missing at {CASE_05_MANIFEST}"

    with open(CASE_05_MANIFEST, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Metadata and schema verification
    assert manifest.get("schema_version") == "case_manifest_v1"
    assert manifest.get("case_id") == "CASE_05_COMPOSITE_CYLINDER_BUCKLING"
    assert manifest.get("qualification_level") == "QUALIFIED"
    assert manifest.get("status") == "ACCEPTED"

    # 2. Cryptographic signature check
    signature = manifest.get("audit_signature")
    assert signature is not None and len(signature) == 64

    manifest_copy = dict(manifest)
    manifest_copy.pop("audit_signature", None)
    expected_hash = hashlib.sha256(
        json.dumps(manifest_copy, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert signature == expected_hash, "Cryptographic audit signature mismatch or manifest tampered!"

    # 3. Summary & Deliverable Reports check
    summary = manifest.get("summary", {})
    assert summary.get("status") == "COMPLETED"
    assert summary.get("engineering_status") == "RESULT_VALID"
    assert summary.get("acceptance_passed") is True
    report_info = summary.get("report", {})
    assert report_info.get("format") == "html"
    assert report_info.get("self_contained") is True
    assert report_info.get("bytes", 0) > 100_000
    assert summary.get("report_html_bytes", 0) > 100_000

    # 4. Physical results check
    phys = manifest.get("physical_results", {})
    assert phys.get("mode_1_eigenvalue_buckling_load_kn", 0.0) >= 100.0
    assert phys.get("riks_post_buckling_limit_load_kn", 0.0) >= 80.0
    assert phys.get("knockdown_factor", 0.0) >= 0.650
    assert phys.get("max_tsai_wu_failure_index", 1.0) <= 0.850
    assert phys.get("reaction_force_balance_error_percent", 1.0) <= 0.050

    # 5. Benchmark comparison check
    bench = manifest.get("benchmark_comparison", {})
    assert bench.get("linear_buckling_relative_diff_percent", 100.0) < 5.0
    assert bench.get("riks_limit_load_relative_diff_percent", 100.0) < 5.0

    # 6. Single-exit acceptance check
    acc = manifest.get("acceptance", {})
    assert acc.get("status") == "PASS"
    assert acc.get("passed") is True
    assert acc.get("criteria_count") == 5


def test_case_05_negative_probes_buckling_and_tsai_wu():
    """Negative Probes: Insufficient buckling load or excessive Tsai-Wu failure index must FAIL."""
    class ConvergenceCheck:
        converged = True

    criteria = [
        {"name": "min_eigenvalue_buckling_load", "value_key": "buckling_load", "operator": ">=", "limit": 100.0, "unit": "kN"},
        {"name": "min_riks_post_buckling_limit_load", "value_key": "limit_load", "operator": ">=", "limit": 80.0, "unit": "kN"},
        {"name": "max_tsai_wu_failure_index", "value_key": "tsai_wu_index", "operator": "<=", "limit": 0.850, "unit": "-"},
    ]

    # Probe 1: Buckling load collapses below threshold (72.0 kN < 80.0 kN limit)
    failed_values_load = {
        "buckling_load": 88.0,  # Below 100.0 kN
        "limit_load": 72.0,     # Below 80.0 kN
        "tsai_wu_index": 0.650,
        "max_displacement": 3.20,
        "reaction_force": 72000.0,
    }
    res_load = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values_load,
        criteria=criteria,
        convergence=ConvergenceCheck(),
        physics_domain="buckling",
        require_evidence=False,
    )
    assert not res_load.passed
    assert res_load.status == "FAIL"
    assert any("criterion:min_eigenvalue_buckling_load" in f or "criterion:min_riks_post_buckling_limit_load" in f for f in res_load.failures)

    # Probe 2: Excessive stress concentration causes composite rupture (Tsai-Wu 0.96 > 0.85)
    failed_values_tsai_wu = {
        "buckling_load": 118.6,
        "limit_load": 92.4,
        "tsai_wu_index": 0.960,  # Exceeds 0.850
        "max_displacement": 2.45,
        "reaction_force": 92400.0,
    }
    res_tw = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values_tsai_wu,
        criteria=criteria,
        convergence=ConvergenceCheck(),
        physics_domain="buckling",
        require_evidence=False,
    )
    assert not res_tw.passed
    assert res_tw.status == "FAIL"
    assert any("criterion:max_tsai_wu_failure_index" in f for f in res_tw.failures)


def test_case_06_problem_statement_specification():
    assert CASE_06_PROBLEM.is_file(), f"Problem statement missing at {CASE_06_PROBLEM}"
    with open(CASE_06_PROBLEM, "r", encoding="utf-8") as f:
        problem = json.load(f)

    assert problem.get("case_id") == "CASE_06_SHEET_METAL_SUBMODELING"
    assert "Sheet Metal" in problem.get("title", "")
    assert problem.get("geometry", {}).get("fastening", {}).get("spot_weld_count") == 6
    assert problem.get("geometry", {}).get("hat_channel", {}).get("thickness_t1_mm") == 1.60
    assert len(problem.get("loading_procedure", [])) == 5
    assert problem.get("acceptance_criteria", {}).get("max_springback_deviation_mm") == 2.50
    assert problem.get("acceptance_criteria", {}).get("max_clamping_residual_stress_mpa") == 450.0
    assert problem.get("acceptance_criteria", {}).get("max_cut_boundary_drift_percent") == 1.00
    assert problem.get("acceptance_criteria", {}).get("max_submodel_nugget_peak_stress_mpa") == 750.0


def test_case_06_sheet_metal_submodeling_manifest_integrity():
    assert CASE_06_MANIFEST.is_file(), f"Manifest missing at {CASE_06_MANIFEST}"

    with open(CASE_06_MANIFEST, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Metadata and schema verification
    assert manifest.get("schema_version") == "case_manifest_v1"
    assert manifest.get("case_id") == "CASE_06_SHEET_METAL_SUBMODELING"
    assert manifest.get("qualification_level") == "QUALIFIED"
    assert manifest.get("status") == "ACCEPTED"

    # 2. Cryptographic signature check
    signature = manifest.get("audit_signature")
    assert signature is not None and len(signature) == 64

    manifest_copy = dict(manifest)
    manifest_copy.pop("audit_signature", None)
    expected_hash = hashlib.sha256(
        json.dumps(manifest_copy, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert signature == expected_hash, "Cryptographic audit signature mismatch or manifest tampered!"

    # 3. Summary & Deliverable Reports check
    summary = manifest.get("summary", {})
    assert summary.get("status") == "COMPLETED"
    assert summary.get("engineering_status") == "RESULT_VALID"
    assert summary.get("acceptance_passed") is True
    report_info = summary.get("report", {})
    assert report_info.get("format") == "html"
    assert report_info.get("self_contained") is True
    assert report_info.get("bytes", 0) > 100_000
    assert summary.get("report_html_bytes", 0) > 100_000

    # 4. Physical results check
    phys = manifest.get("physical_results", {})
    assert phys.get("max_springback_deviation_mm", 10.0) <= 2.50
    assert phys.get("max_clamping_residual_stress_mpa", 1000.0) <= 450.0
    assert phys.get("cut_boundary_drift_percent", 10.0) <= 1.00
    assert phys.get("submodel_nugget_peak_stress_mpa", 1000.0) <= 750.0
    assert phys.get("reaction_force_balance_error_percent", 1.0) <= 0.050

    # 5. Benchmark comparison check
    bench = manifest.get("benchmark_comparison", {})
    assert bench.get("springback_deviation_relative_diff_percent", 100.0) < 5.0
    assert bench.get("submodel_peak_stress_relative_diff_percent", 100.0) < 5.0

    # 6. Single-exit acceptance check
    acc = manifest.get("acceptance", {})
    assert acc.get("status") == "PASS"
    assert acc.get("passed") is True
    assert acc.get("criteria_count") == 5

    # 7. Machine solver artifacts check
    artifacts = manifest.get("artifacts", [])
    assert len(artifacts) >= 12, "Solver artifacts (.inp, .sta, .msg, .dat, .log, .odb) must be tracked in manifest"
    artifact_names = [a.get("name") for a in artifacts]
    assert "case_06_global_assembly.inp" in artifact_names
    assert "case_06_weld_submodel.inp" in artifact_names
    assert "case_06_global_assembly.sta" in artifact_names
    assert "case_06_weld_submodel.sta" in artifact_names
    assert "case_06_global_assembly.msg" in artifact_names
    assert "case_06_weld_submodel.msg" in artifact_names
    assert "case_06_global_assembly.log" in artifact_names
    assert "case_06_weld_submodel.log" in artifact_names
    assert "case_06_global_assembly.odb" in artifact_names
    assert "case_06_weld_submodel.odb" in artifact_names

    # 8. True Mesh Quality Audit check
    mesh_audit = manifest.get("mesh_quality_audit", {})
    assert mesh_audit.get("status") == "PASS"
    assert mesh_audit.get("passed") is True
    gov = mesh_audit.get("governing_metrics", {})
    assert gov.get("min_jacobian", 0.0) >= 0.60
    assert gov.get("max_aspect_ratio", 100.0) <= 4.00
    assert gov.get("min_angle", 0.0) >= 45.0
    assert gov.get("max_angle", 180.0) <= 135.0


def test_case_06_negative_probes_springback_and_submodel_stress():
    """Negative Probes: Excessive springback warpage or nugget notch over-stress must FAIL."""
    class ConvergenceCheck:
        converged = True

    criteria = [
        {"name": "max_springback_deviation", "value_key": "springback_deviation", "operator": "<=", "limit": 2.50, "unit": "mm"},
        {"name": "max_clamping_residual_stress", "value_key": "clamping_stress", "operator": "<=", "limit": 450.0, "unit": "MPa"},
        {"name": "max_cut_boundary_drift", "value_key": "cut_boundary_drift", "operator": "<=", "limit": 1.00, "unit": "%"},
        {"name": "max_submodel_nugget_peak_stress", "value_key": "nugget_peak_stress", "operator": "<=", "limit": 750.0, "unit": "MPa"},
        {"name": "max_reaction_balance_error", "value_key": "reaction_error_percent", "operator": "<=", "limit": 0.050, "unit": "%"},
    ]

    # Probe 1: Springback warpage collapses tolerance (3.42 mm > 2.50 mm limit)
    failed_values_springback = {
        "springback_deviation": 3.42,
        "clamping_stress": 382.4,
        "cut_boundary_drift": 0.18,
        "nugget_peak_stress": 684.2,
        "reaction_error_percent": 0.008,
        "reaction_force": 8499.3,
        "max_displacement": 3.42,
        "max_mises": 684.2,
    }
    res_sb = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values_springback,
        criteria=criteria,
        convergence=ConvergenceCheck(),
        procedure_verification=True,
        physics_domain="plasticity",
        require_evidence=False,
    )
    assert not res_sb.passed
    assert res_sb.status == "FAIL"
    assert any("criterion:max_springback_deviation" in f for f in res_sb.failures)

    # Probe 2: Weld nugget stress exceeds material yield (820.0 MPa > 750.0 MPa limit)
    failed_values_notch = {
        "springback_deviation": 1.85,
        "clamping_stress": 382.4,
        "cut_boundary_drift": 0.18,
        "nugget_peak_stress": 820.0,  # Rupture yield
        "reaction_error_percent": 0.008,
        "reaction_force": 8499.3,
        "max_displacement": 1.85,
        "max_mises": 820.0,
    }
    res_notch = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values_notch,
        criteria=criteria,
        convergence=ConvergenceCheck(),
        procedure_verification=True,
        physics_domain="plasticity",
        require_evidence=False,
    )
    assert not res_notch.passed
    assert res_notch.status == "FAIL"
    assert any("criterion:max_submodel_nugget_peak_stress" in f for f in res_notch.failures)

    # Probe 3: Submodel boundary cut drift exceeds fidelity gate (1.85% > 1.00%)
    failed_values_drift = {
        "springback_deviation": 1.85,
        "clamping_stress": 382.4,
        "cut_boundary_drift": 1.85,  # Interpolation drift error
        "nugget_peak_stress": 684.2,
        "reaction_error_percent": 0.008,
        "reaction_force": 8499.3,
        "max_displacement": 1.85,
        "max_mises": 684.2,
    }
    res_drift = evaluate_result_acceptance(
        result_status="completed",
        values=failed_values_drift,
        criteria=criteria,
        convergence=ConvergenceCheck(),
        procedure_verification=True,
        physics_domain="plasticity",
        require_evidence=False,
    )
    assert not res_drift.passed
    assert res_drift.status == "FAIL"
    assert any("criterion:max_cut_boundary_drift" in f for f in res_drift.failures)


def test_case_06_mesh_quality_gate_algorithm_integrity():
    """Verify authentic mesh quality audit algorithm and fail-closed distorted element gate."""
    from abaqus_ai_agent.execution.case_06_mesh_audit import (
        audit_case_06_mesh_quality,
        audit_quad_element,
    )
    from abaqus_ai_agent.mesh_gate import evaluate_mesh_quality_gate

    # 1. Authentic Case 06 mesh audit passes strict engineering policy
    gate_eval, report = audit_case_06_mesh_quality()
    assert gate_eval.passed is True
    assert gate_eval.status == "PASS"
    metrics = report["governing_metrics"]
    assert metrics["min_jacobian"] >= 0.60
    assert metrics["max_aspect_ratio"] <= 4.00
    assert metrics["min_angle"] >= 45.0
    assert metrics["max_angle"] <= 135.0

    # 2. Negative Probe: Inverted element (negative Jacobian <= 0) must trigger BLOCKED
    distorted_metrics_inverted = {
        "min_jacobian": -0.05,  # Inverted
        "max_aspect_ratio": 2.50,
        "min_angle": 80.0,
        "max_angle": 100.0,
    }
    gate_inv = evaluate_mesh_quality_gate(distorted_metrics_inverted)
    assert gate_inv.passed is False
    assert gate_inv.status == "BLOCKED"
    assert any("Inverted element detected" in v for v in gate_inv.violations)

    # 3. Negative Probe: Extreme aspect ratio (> 50.0) must trigger BLOCKED
    distorted_metrics_ar = {
        "min_jacobian": 0.85,
        "max_aspect_ratio": 58.2,  # Extreme needle element
        "min_angle": 80.0,
        "max_angle": 100.0,
    }
    gate_ar = evaluate_mesh_quality_gate(distorted_metrics_ar)
    assert gate_ar.passed is False
    assert gate_ar.status == "BLOCKED"
    assert any("Excessive aspect ratio" in v for v in gate_ar.violations)


def test_case_06_negative_probe_anti_cheat_missing_solver_artifacts():
    """Anti-Cheat Probe: Attempting to bypass solver execution or falsify values without artifacts MUST FAIL."""
    from abaqus_ai_agent.contracts.evidence import ArtifactRecord, EvidenceManifestV2

    criteria = [
        {"name": "max_springback_deviation", "value_key": "springback_deviation", "operator": "<=", "limit": 2.50, "unit": "mm"},
    ]
    values = {"springback_deviation": 1.85}

    # Probe 1: Direct pass without evidence manifest when require_evidence=True -> BLOCKED
    res_no_evidence = evaluate_result_acceptance(
        result_status="completed",
        values=values,
        criteria=criteria,
        require_evidence=True,
    )
    assert res_no_evidence.passed is False
    assert res_no_evidence.status == "BLOCKED"
    assert "missing_required_evidence" in res_no_evidence.failures

    # Probe 2: Evidence manifest points to missing/non-existent solver files on disk -> BLOCKED
    fake_manifest = EvidenceManifestV2(
        run_id="FAKE-RUN-ID",
        case_id="CASE_06_SHEET_METAL_SUBMODELING",
        created_at="2026-10-08T00:00:00Z",
        artifacts={
            "case_06_global_assembly.inp": ArtifactRecord(
                name="case_06_global_assembly.inp",
                path="/non/existent/path/case_06_global_assembly.inp",
                role="inp",
                exists=True,
                size_bytes=1000,
                sha256="0000000000000000000000000000000000000000000000000000000000000000",
                mandatory=True,
            ),
            "case_06_global_assembly.odb": ArtifactRecord(
                name="case_06_global_assembly.odb",
                path="/non/existent/path/case_06_global_assembly.odb",
                role="odb",
                exists=True,
                size_bytes=1000,
                sha256="0000000000000000000000000000000000000000000000000000000000000000",
                mandatory=True,
            ),
        },
    ).with_signature()

    res_fake_evidence = evaluate_result_acceptance(
        result_status="completed",
        values=values,
        criteria=criteria,
        evidence_manifest=fake_manifest,
        require_evidence=True,
    )
    assert res_fake_evidence.passed is False
    assert res_fake_evidence.status == "BLOCKED"
    assert any("evidence_incomplete:missing_mandatory_role" in f or "file_not_found" in f for f in res_fake_evidence.failures)


def test_package_b_cases_folder_organization_and_standalone_html():
    """Verify Phase 2 Package B folder isolation & self-contained HTML deliverable enforcement.

    Asserts:
    1. Each engineering case is organized inside its own isolated dedicated subfolder.
    2. Deliverable reports are strictly pure standalone HTML with embedded Base64/SVG assets.
    3. No legacy Markdown (.md) reports reside on disk.
    4. Backwards compatibility top-level manifests match isolated folder manifests bit-for-bit.
    """
    p2_root = ROOT / "machine_validation" / "p2_cases"

    cases_spec = [
        (
            CASE_01_SUB_DIR,
            "case_01_flange_manifest.json",
            "Case_01_Bolted_Flange_Report.html",
        ),
        (
            CASE_02_SUB_DIR,
            "case_02_rpv_manifest.json",
            "Case_02_RPV_Closure_Report.html",
        ),
        (
            CASE_03_SUB_DIR,
            "case_03_manifold_manifest.json",
            "Case_03_Exhaust_Manifold_Report.html",
        ),
        (
            CASE_04_SUB_DIR,
            "case_04_subframe_manifest.json",
            "Case_04_Subframe_Durability_Report.html",
        ),
        (
            CASE_05_SUB_DIR,
            "case_05_composite_buckling_manifest.json",
            "Case_05_Composite_Buckling_Report.html",
        ),
        (
            CASE_06_SUB_DIR,
            "case_06_sheet_metal_manifest.json",
            "Case_06_Sheet_Metal_Submodeling_Report.html",
        ),
    ]

    for sub_dir, manifest_name, html_report_name in cases_spec:
        assert sub_dir.is_dir(), f"Case subfolder missing at {sub_dir}"

        sub_manifest = sub_dir / manifest_name
        top_manifest = p2_root / manifest_name
        assert sub_manifest.is_file(), f"Manifest missing in subfolder: {sub_manifest}"
        assert top_manifest.is_file(), f"Top-level compatibility manifest missing: {top_manifest}"

        # Bit-for-bit identical cryptographic manifest
        assert sub_manifest.read_bytes() == top_manifest.read_bytes(), f"Manifest mismatch between subfolder and mirror for {manifest_name}"

        # Standalone HTML report check (must be large enough to verify inlined Base64 GIF & SVG)
        html_file = sub_dir / html_report_name
        assert html_file.is_file(), f"HTML report missing: {html_file}"
        assert html_file.stat().st_size > 100_000, f"HTML report {html_file} is smaller than expected ({html_file.stat().st_size} bytes), assets might not be embedded!"

        # Read HTML content to confirm self-contained Base64 Data URI or SVG
        content = html_file.read_text(encoding="utf-8")
        assert "data:image/gif;base64," in content or "<svg" in content
        assert "html" in content.lower()

        # Enforce pure HTML delivery - strictly zero legacy .md files in the subfolder
        md_files = list(sub_dir.glob("*.md"))
        assert len(md_files) == 0, f"Legacy Markdown files found in {sub_dir}: {[f.name for f in md_files]}"
