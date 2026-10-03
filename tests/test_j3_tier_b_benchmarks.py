"""Regression tests for Phase J.3 Tier B Extended Engineering Physics Benchmarks."""

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.contracts.benchmarks_catalog import (
    OFFICIAL_TIER_B_CATALOG,
    get_tier_b_benchmark,
    get_official_benchmark,
    list_benchmarks_by_domain,
)
from tools.j3_tier_b_extended_physics import (
    evaluate_tier_b_instance,
    run_tier_b_physics_suite,
)

ROOT = Path(__file__).resolve().parent.parent


def test_tier_b_catalog_completeness():
    """Verify that all 7 Tier B extended benchmarks are present with unique IDs."""
    assert len(OFFICIAL_TIER_B_CATALOG) == 7
    ids = {b.benchmark_id for b in OFFICIAL_TIER_B_CATALOG}
    assert len(ids) == 7

    expected_ids = {
        "B_VISCOELASTIC_RELAXATION",
        "B_NORTON_POWER_CREEP",
        "B_COHESIVE_DELAMINATION",
        "B_FRACTURE_J_INTEGRAL",
        "B_OPEN_HOLE_COMPOSITE",
        "B_BOLT_PRETENSION_SERVICE",
        "B_TRANSIENT_MASS_DIFFUSION",
    }
    assert ids == expected_ids


def test_tier_b_spec_integrity():
    """Verify each Tier B specification conforms to official guidelines and V&V 10 standards."""
    for b in OFFICIAL_TIER_B_CATALOG:
        assert b.benchmark_id.startswith("B_")
        assert "Abaqus" in b.official_guide
        assert b.documentation_locator.startswith("SIMULIA Abaqus 2025")
        assert b.title
        assert b.physics_domain
        assert b.governing_physics
        assert b.reference_metric_name
        assert b.reference_metric_unit
        assert b.tolerance > 0.0
        assert b.official_reference_value != 0.0
        assert isinstance(b.official_model_params, dict)
        assert len(b.official_model_params) >= 3


def test_tier_b_lookups():
    """Test lookup helper functions for Tier B specifications."""
    spec = get_tier_b_benchmark("B_VISCOELASTIC_RELAXATION")
    assert spec is not None
    assert spec.physics_domain == "time_dependent_materials"

    # Also retrievable via global get_official_benchmark
    global_spec = get_official_benchmark("B_COHESIVE_DELAMINATION")
    assert global_spec is not None
    assert global_spec.benchmark_id == "B_COHESIVE_DELAMINATION"

    # Filter with include_tier_b
    time_dep = list_benchmarks_by_domain("time_dependent_materials", include_tier_b=True)
    assert len(time_dep) == 2  # Viscoelasticity and Creep


@pytest.mark.parametrize("spec", OFFICIAL_TIER_B_CATALOG, ids=lambda s: s.benchmark_id)
def test_each_tier_b_benchmark_evaluation(spec):
    """Verify each individual Tier B benchmark evaluates analytically and satisfies tolerance."""
    res = evaluate_tier_b_instance(spec)
    assert res.passed is True
    assert res.status == "PASS"
    assert res.relative_discrepancy <= spec.tolerance
    assert res.evaluation_mode == "ANALYTICAL_CLOSED_FORM"
    assert res.provenance["note"]


def test_run_tier_b_physics_suite_end_to_end():
    """Test end-to-end execution of Tier B suite."""
    summary = run_tier_b_physics_suite()
    assert summary["all_passed"] is True
    assert summary["total_benchmarks"] == 7
    assert summary["passed_benchmarks"] == 7
    assert summary["failed_benchmarks"] == 0
    assert len(summary["results"]) == 7


def test_tier_b_evidence_manifest_exists():
    """Verify that the committed Tier B evidence JSON manifest is well-formed."""
    evidence_file = ROOT / "machine_validation" / "j3_tier_b_evidence.json"
    assert evidence_file.exists(), "Evidence manifest must exist on disk"
    with open(evidence_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["all_passed"] is True
    assert data["total_benchmarks"] == 7
    assert len(data["results"]) == 7
