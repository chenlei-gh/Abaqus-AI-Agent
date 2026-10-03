"""Regression tests for Phase J official Abaqus benchmarks catalog and matrix engine."""

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
)


def test_benchmarks_catalog_completeness():
    """Verify that all 22 official Tier A benchmarks are loaded with valid specifications."""
    assert len(OFFICIAL_TIER_A_CATALOG) >= 20
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
    assert res.relative_discrepancy <= s1.tolerance
    assert res.status == "PASS"


def test_run_tier_a_matrix_output():
    """Test full matrix execution with custom output evidence path."""
    envelope = run_comprehensive_physics_suite(strict=True)
    assert envelope["all_passed"] is True
    assert envelope["benchmark_count"] == len(OFFICIAL_TIER_A_CATALOG)
    assert len(envelope["benchmarks"]) == len(OFFICIAL_TIER_A_CATALOG)
