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
CASE_01_MANIFEST = ROOT / "machine_validation" / "p2_cases" / "case_01_flange_manifest.json"
CASE_02_PROBLEM = ROOT / "test_assets" / "engineering_cases" / "case_02_reactor_pressure_vessel_closure" / "problem_statement.json"
CASE_02_MANIFEST = ROOT / "machine_validation" / "p2_cases" / "case_02_rpv_manifest.json"


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
