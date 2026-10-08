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
    assert summary.get("report_md_bytes", 0) > 3000
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
    assert summary.get("report_md_bytes", 0) > 3000
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
    assert summary.get("report_md_bytes", 0) > 3000
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
    assert summary.get("report_md_bytes", 0) > 3000
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
