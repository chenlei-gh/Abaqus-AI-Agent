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

    assert report["benchmark_version"] == "jev_engineering_eval_v2"
    assert report["total_cases"] >= 15
    assert report["passed_cases"] == report["total_cases"]
    assert report["overall_accuracy_pct"] == 100.0
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
    assert loaded["benchmark_version"] == "jev_engineering_eval_v2"
    assert loaded["total_cases"] == report["total_cases"]

    md_report = format_markdown_report(report)
    assert "# JEV Engineering Intent Evaluation Benchmark Report" in md_report
    assert "Overall Accuracy" in md_report
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
    assert len(res_merged.intent.loads) > 0
    assert len(res_merged.intent.boundary_conditions) > 0
