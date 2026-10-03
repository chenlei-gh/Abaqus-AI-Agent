"""Regression tests for Phase J official Abaqus benchmarks catalog, theoretical reference gate, and live matrix."""

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.contracts.benchmarks_catalog import (
    OFFICIAL_TIER_A_CATALOG,
    get_benchmark_spec,
    list_benchmarks_by_domain,
    OfficialBenchmarkSpec,
)
from tools.j_comprehensive_physics_matrix import (
    evaluate_benchmark_instance,
    run_comprehensive_physics_suite,
    _verify_parameter_contract,
)
from tools.j_live_abaqus_matrix import _generate_cae_script

ROOT = Path(__file__).resolve().parent.parent


def test_benchmarks_catalog_completeness():
    """Verify that all 22 official Tier A benchmarks are loaded with valid specifications."""
    assert len(OFFICIAL_TIER_A_CATALOG) == 22
    ids = {b.benchmark_id for b in OFFICIAL_TIER_A_CATALOG}
    assert len(ids) == len(OFFICIAL_TIER_A_CATALOG), "Benchmark IDs must be unique"

    required_keys = [
        "S1_UNIAXIAL_TENSION",
        "S2_PURE_COMPRESSION",
        "S3_PURE_SHEAR",
        "S4_SAINT_VENANT_TORSION",
        "M1_ELASTOPLASTIC_UNLOADING",
        "M2_CYCLIC_PLASTICITY",
        "M3_LARGE_DEFLECTION_NLGEOM",
        "B1_EULER_BUCKLING",
        "B2_NONLINEAR_POST_BUCKLING",
        "D1_CANTILEVER_MODAL",
        "D2_PRELOADED_MODAL",
        "T1_SEQUENTIAL_THERMAL_STRESS",
        "T2_COUPLED_TEMP_DISPLACEMENT",
        "MAT1_HYPERELASTIC_RUBBER",
        "F1_CONTINUUM_DAMAGE",
        "C1_COMPOSITE_LAMINATE",
        "CTC1_CONTACT_SEPARATION",
        "CTC2_LARGE_SLIDING_FRICTION",
        "CONN_TRANSLATIONAL_SPRING",
        "I1_GRAVITY_MASS_EQUILIBRIUM",
        "E2_EXPLICIT_DYNAMIC_IMPACT",
        "NEG01_SOLVER_HEALING",
    ]
    for rk in required_keys:
        assert rk in ids, f"Missing benchmark: {rk}"


def test_benchmarks_catalog_spec_integrity():
    """Verify each benchmark spec adheres strictly to official guides and non-zero tolerances."""
    for b in OFFICIAL_TIER_A_CATALOG:
        assert b.benchmark_id
        assert b.official_guide.startswith("Abaqus ") or "Verification" in b.official_guide
        assert b.title
        assert b.physics_domain
        assert b.governing_physics
        assert b.reference_metric_name
        assert b.reference_metric_unit
        assert b.tolerance > 0.0
        assert isinstance(b.official_model_params, dict)
        assert b.documentation_locator.startswith("SIMULIA Abaqus 2025")
        assert b.reference_source_type in {"closed_form_theory", "published_fe_reference"}


def test_benchmarks_catalog_lookup():
    """Test lookup by ID and domain filtering."""
    s1 = get_benchmark_spec("S1_UNIAXIAL_TENSION")
    assert s1 is not None
    assert s1.physics_domain == "solid_mechanics"

    none_spec = get_benchmark_spec("NON_EXISTENT_ID")
    assert none_spec is None

    contact_specs = list_benchmarks_by_domain("contact_tribology")
    assert len(contact_specs) >= 2


def test_benchmark_instance_evaluation():
    """Test the single-instance evaluation logic on a known benchmark."""
    s1 = get_benchmark_spec("S1_UNIAXIAL_TENSION")
    assert s1 is not None
    res = evaluate_benchmark_instance(s1)
    assert res.passed is True
    assert res.evaluation_mode == "ANALYTICAL_CLOSED_FORM"
    assert res.relative_discrepancy <= s1.tolerance
    assert res.status == "PASS"


def test_benchmark_contract_mode_evaluation():
    """Test that published FE reference benchmarks run under THEORETICAL_PARAMETER_CONTRACT."""
    m3 = get_benchmark_spec("M3_LARGE_DEFLECTION_NLGEOM")
    assert m3 is not None
    res = evaluate_benchmark_instance(m3)
    assert res.passed is True
    assert res.evaluation_mode == "THEORETICAL_PARAMETER_CONTRACT"
    assert res.relative_discrepancy == 0.0
    assert "Real FE execution" in res.provenance["note"]


def test_verify_parameter_contract_fail_closed():
    """Verify that corrupt or incomplete model parameters fail closed."""
    corrupt_spec = OfficialBenchmarkSpec(
        benchmark_id="M3_LARGE_DEFLECTION_NLGEOM",
        official_guide="Abaqus Benchmarks Guide 1.2.1",
        title="Corrupted M3",
        physics_domain="geometric_nonlinearity",
        numerical_formulation="large_displacement_nlgeom",
        governing_physics="Nonlinear Euler-Bernoulli Elastica Theory",
        official_model_params={"L": 100.0},  # Missing b, h, E, nu, tip_load
        reference_metric_name="tip_vertical_deflection",
        reference_metric_unit="mm",
        official_reference_value=41.28,
        tolerance=0.015,
        documentation_locator="SIMULIA Abaqus 2025 Benchmarks Guide §1.2.1",
        reference_source_type="published_fe_reference",
    )
    ok, issues = _verify_parameter_contract(corrupt_spec)
    assert ok is False
    assert len(issues) >= 3


def test_run_tier_a_matrix_output():
    """Test full matrix execution with custom output evidence path."""
    envelope = run_comprehensive_physics_suite(strict=True)
    assert envelope["all_passed"] is True
    assert envelope["benchmark_count"] == 22
    assert envelope["passed_count"] == 22
    assert envelope["analytical_count"] == 13
    assert envelope["contract_count"] == 9
    assert len(envelope["benchmarks"]) == 22


def test_live_script_generation():
    """Verify that CAE script generation produces well-formed Abaqus Python code."""
    s1 = get_benchmark_spec("S1_UNIAXIAL_TENSION")
    assert s1 is not None
    script = _generate_cae_script(s1, ROOT / "machine_validation")
    assert "Job_S1_UNIAXIAL_TENSION" in script
    assert "S1_UNIAXIAL_TENSION" in script
    assert "openOdb" in script
    assert "AIAgent_LIVE_BENCHMARK_COMPLETED" in script


def test_live_abaqus_evidence_file_integrity():
    """Verify that the real Abaqus 2025 evidence envelope contains 22 passed live benchmarks."""
    evidence_path = ROOT / "machine_validation" / "j_live_abaqus_evidence.json"
    assert evidence_path.is_file(), "j_live_abaqus_evidence.json must exist"

    with open(evidence_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["benchmark_count"] == 22
    assert data["passed_count"] == 22
    assert data["all_passed"] is True
    assert len(data["benchmarks"]) == 22

    # Verify that real process execution artifacts were recorded
    for b in data["benchmarks"]:
        assert b["passed"] is True
        assert b["status"] == "PASS"
        assert b["execution"]["real_process"] is True
        assert b["execution"]["exit_code"] == 0
        assert b["observed_value"] is not None
        assert b["relative_error"] <= b["tolerance"]
