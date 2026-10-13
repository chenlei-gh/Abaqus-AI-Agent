"""Tests for Phase B: JEV Independent Engineering Evaluation Benchmark Suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from abaqus_ai_agent.typesafe_intent import (
    EngineeringIntentRouter,
    JevIntentRouter,
)
from tools.jev_engineering_benchmark import (
    BENCHMARK_CASES,
    format_markdown_report,
    run_engineering_benchmark,
)


def test_jev_engineering_benchmark_suite_passes():
    """Verify that the 6-dimensional benchmark suite achieves 100% accuracy and 0% false negatives."""
    report = run_engineering_benchmark()

    assert report["benchmark_version"] == "jev_engineering_eval_v3"
    assert report["provider_type"] == "offline_deterministic_baseline"
    assert report["is_offline_baseline"] is True
    assert report["total_cases"] >= 15
    assert report["passed_cases"] == report["total_cases"]
    assert report["overall_accuracy_pct"] == 100.0

    # Segregated metric assertions
    safety_m = report["safety_metrics"]
    assert safety_m["safety_critical_cases"] > 0
    assert safety_m["false_negatives"] == 0
    assert safety_m["false_negative_rate_pct"] == 0.0

    usability_m = report["usability_metrics"]
    assert usability_m["usability_cases"] > 0
    assert usability_m["false_positives"] == 0
    assert usability_m["false_positive_rate_pct"] == 0.0
    assert safety_m["safety_critical_cases"] + usability_m["usability_cases"] == report["total_cases"]

    physics_m = report["physics_metrics"]
    assert physics_m["physics_evaluated_cases"] > 0
    assert physics_m["physics_accuracy_pct"] == 100.0

    missing_m = report["missing_prerequisites_metrics"]
    assert missing_m["missing_prereqs_total"] > 0
    assert missing_m["missing_prereqs_recall_pct"] == 100.0
    assert missing_m["missing_prereqs_miss_rate_pct"] == 0.0

    assert report["false_negative_rate_pct"] == 0.0
    assert report["false_positive_rate_pct"] == 0.0
    assert report["latency_stats"]["avg_ms"] >= 0.0

    # Ensure all 6 dimensions are evaluated
    expected_dims = {
        "physics_classification",
        "missing_prerequisites",
        "exploratory_gating",
        "compliance_enforcement",
        "ambiguity_clarification",
        "adversarial_blocking",
    }
    breakdown = report["dimension_breakdown"]
    for dim in expected_dims:
        assert dim in breakdown
        assert breakdown[dim]["accuracy_pct"] == 100.0


def test_jev_engineering_benchmark_json_and_md_export(tmp_path: Path):
    """Verify benchmark reporting exports valid JSON and formatted markdown."""
    out_file = tmp_path / "benchmark_report.json"
    report = run_engineering_benchmark(output_path=out_file)

    assert out_file.is_file()
    with open(out_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["benchmark_version"] == "jev_engineering_eval_v3"
    assert loaded["total_cases"] == report["total_cases"]
    assert loaded["provider_type"] == "offline_deterministic_baseline"

    md_report = format_markdown_report(report)
    assert "# JEV Engineering Intent Evaluation Benchmark Report: [Offline Deterministic Rule Baseline]" in md_report
    assert "Evaluation Identity Notice" in md_report
    assert "Overall Accuracy" in md_report
    assert "Safety False Negative Rate" in md_report
    assert "Physics Domain Accuracy" in md_report
    assert "Dimension Breakdown" in md_report
    assert "physics_classification" in md_report


def test_jev_engineering_benchmark_with_mock_live_provider():
    """Verify benchmark harness operates seamlessly when an external provider is injected."""
    class CompliantMockProvider:
        def is_configured(self) -> bool:
            return True

        def judge(self, prompt: str, timeout: float = 5.0) -> Dict[str, Any]:
            return {
                "answers": {
                    "physics": {"choice": "linear_static", "confidence": 0.98},
                    "units": {"choice": "MM_N_MPA", "confidence": 0.95},
                    "solver": {"choice": "abaqus_standard", "confidence": 0.97},
                    "well_constrained": {"probability": 0.95},
                    "has_acceptance_criteria": {"probability": 0.95},
                    "completeness": {"score": 4.5},
                }
            }

    router = EngineeringIntentRouter(
        mode="live",
        external_provider=CompliantMockProvider(),
    )
    # Single case verification under live provider
    res = router.route("100mm cantilever steel beam with 1000N load, fixed root, check stress <= 600MPa")
    assert res.status == "ROUTED"
    assert res.intent is not None
    assert res.decision_bundle.execution_mode == "live"


def test_jev_engineering_benchmark_context_merge_end_to_end():
    """End-to-end verification of upstream CAE/INP model context unblocking missing parameters."""
    router = JevIntentRouter(mode="offline")

    # Incomplete prompt: no dimensions, no material
    vague_prompt = "对结构件端部施加5000N集中力，固定底面约束。"
    res_raw = router.route(vague_prompt)
    assert res_raw.status == "NEEDS_CLARIFICATION"
    assert "missing_geometry_dimensions" in res_raw.missing_requirements
    assert "missing_material_specification" in res_raw.missing_requirements

    # Upstream model context provides geometry and material
    cae_context = {
        "dimensions": [{"value": 100.0, "unit": "mm"}, {"value": 50.0, "unit": "mm"}],
        "material": {
            "name": "Structural_Steel",
            "elastic_modulus": 210000.0,
            "poisson_ratio": 0.3,
            "unit": "MPa",
        },
        "has_model": True,
    }
    res_merged = router.route(vague_prompt, context=cae_context)
    assert res_merged.status == "ROUTED"
    assert res_merged.intent is not None
    assert res_merged.intent.material["name"] == "Structural_Steel"
    assert res_merged.intent.metadata.get("context_merged") is True
    assert res_merged.intent.metadata.get("routing_gate_passed") is True
    assert res_merged.intent.metadata.get("preflight_required") is True
    assert res_merged.intent.metadata.get("solver_ready") is False
    assert len(res_merged.intent.loads) > 0
    assert len(res_merged.intent.boundary_conditions) > 0


def test_context_merge_rejects_nominal_boolean_flags():
    """Verify that passing nominal boolean flags without real entity data fails closed."""
    router = JevIntentRouter(mode="offline")
    vague_prompt = "对结构件端部施加5000N集中力，固定底面约束。"

    # Attempt to bypass prerequisites using only nominal boolean flags
    boolean_stub_context = {
        "has_model": True,
        "has_geometry": True,
        "has_material": True,
        "has_constraints": True,
        "has_loads": True,
        "is_well_constrained": True,
    }
    res_blocked = router.route(vague_prompt, context=boolean_stub_context)
    assert res_blocked.status == "NEEDS_CLARIFICATION"
    assert "missing_geometry_dimensions" in res_blocked.missing_requirements
    assert "missing_material_specification" in res_blocked.missing_requirements

    # Attempt with empty containers
    empty_containers_context = {
        "dimensions": [],
        "geometry": {},
        "material": "",
        "boundary_conditions": [],
    }
    res_empty_blocked = router.route(vague_prompt, context=empty_containers_context)
    assert res_empty_blocked.status == "NEEDS_CLARIFICATION"
    assert "missing_geometry_dimensions" in res_empty_blocked.missing_requirements
    assert "missing_material_specification" in res_empty_blocked.missing_requirements


def test_context_merge_structured_inp_evidence():
    """Verify that structured non-empty INP entity evidence correctly satisfies prerequisites."""
    router = JevIntentRouter(mode="offline")
    vague_prompt = "对结构件端部施加5000N集中力，固定底面约束。"

    valid_inp_context = {
        "inp_evidence": {
            "parts": ["BeamPart"],
            "nodes": [1, 2, 3],
            "material": {
                "name": "Alloy_7075",
                "elastic_modulus": 71700.0,
                "poisson_ratio": 0.33,
            },
        },
    }
    res = router.route(vague_prompt, context=valid_inp_context)
    assert res.status == "ROUTED"
    assert res.intent is not None
    assert res.intent.material["name"] == "Alloy_7075"


def test_benchmark_metrics_strict_denominators_calculation():
    """Verify that false negative and false positive rates use mathematically strict segregated denominators."""
    report = run_engineering_benchmark()

    safety = report["safety_metrics"]
    usability = report["usability_metrics"]
    physics = report["physics_metrics"]
    missing = report["missing_prerequisites_metrics"]

    # Verify denominator definitions
    assert safety["safety_critical_cases"] == 9   # 9 benchmark cases requiring clarification or blocking (Missing + Compliance + Ambiguity + Adversarial)
    assert usability["usability_cases"] == 8      # 8 benchmark cases expecting ROUTED (Physics + Exploratory)
    assert safety["safety_critical_cases"] + usability["usability_cases"] == report["total_cases"]

    # Verify no dilution: rates are based on respective categories
    assert safety["false_negative_rate_pct"] == round((safety["false_negatives"] / safety["safety_critical_cases"]) * 100.0, 2)
    assert usability["false_positive_rate_pct"] == round((usability["false_positives"] / usability["usability_cases"]) * 100.0, 2)
    assert physics["physics_accuracy_pct"] == round((physics["physics_matches"] / physics["physics_evaluated_cases"]) * 100.0, 2)
    assert missing["missing_prereqs_recall_pct"] == round((missing["missing_prereqs_detected"] / missing["missing_prereqs_total"]) * 100.0, 2)
