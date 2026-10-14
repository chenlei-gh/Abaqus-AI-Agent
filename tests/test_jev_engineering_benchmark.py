"""Tests for Phase B: JEV Independent Engineering Evaluation Benchmark Suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

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

    assert report["benchmark_version"] == "jev_engineering_eval_v4"
    assert report["cases_hash"].startswith("sha256_")
    assert report["provider_type"] == "offline_deterministic_baseline"
    assert report["is_offline_baseline"] is True
    assert report["total_cases"] >= 20
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
    assert missing_m["missing_prereqs_precision_pct"] > 0.0

    evidence_m = report["context_evidence_metrics"]
    assert evidence_m["evidence_adversarial_cases"] > 0
    assert evidence_m["false_acceptance_cases"] == 0
    assert evidence_m["false_acceptance_rate_pct"] == 0.0

    assert report["false_negative_rate_pct"] == 0.0
    assert report["false_positive_rate_pct"] == 0.0
    assert report["latency_stats"]["avg_ms"] >= 0.0

    # Ensure all dimensions are evaluated
    expected_dims = {
        "physics_classification",
        "missing_prerequisites",
        "exploratory_gating",
        "compliance_enforcement",
        "ambiguity_clarification",
        "adversarial_blocking",
        "conflict_detection",
        "evidence_validation",
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
    assert loaded["benchmark_version"] == "jev_engineering_eval_v4"
    assert loaded["total_cases"] == report["total_cases"]
    assert loaded["provider_type"] == "offline_deterministic_baseline"

    md_report = format_markdown_report(report)
    assert "# JEV Engineering Intent Evaluation Benchmark Report: [Offline Deterministic Rule Baseline]" in md_report
    assert "Evaluation Identity Notice" in md_report
    assert "Overall Accuracy" in md_report
    assert "Safety False Negative Rate" in md_report
    assert "Physics Domain Accuracy" in md_report
    assert "Missing Prerequisites Precision" in md_report
    assert "Context Evidence False Acceptance Rate" in md_report
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
    res = router.route("100mm cantilever steel beam with 1000N load at tip, fixed root, check stress <= 600MPa")
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
    assert safety["safety_critical_cases"] >= 14
    assert usability["usability_cases"] == 8
    assert safety["safety_critical_cases"] + usability["usability_cases"] == report["total_cases"]

    # Verify no dilution: rates are based on respective categories
    assert safety["false_negative_rate_pct"] == round((safety["false_negatives"] / safety["safety_critical_cases"]) * 100.0, 2)
    assert usability["false_positive_rate_pct"] == round((usability["false_positives"] / usability["usability_cases"]) * 100.0, 2)
    assert physics["physics_accuracy_pct"] == round((physics["physics_matches"] / physics["physics_evaluated_cases"]) * 100.0, 2)
    assert missing["missing_prereqs_recall_pct"] == round((missing["missing_prereqs_detected"] / missing["missing_prereqs_total"]) * 100.0, 2)


def test_draft_intent_solver_execution_blocked_in_agent():
    """Verify that DraftEngineeringIntent is strictly blocked at the agent entry level."""
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.contracts.task import TaskStatus

    router = JevIntentRouter(mode="offline")
    draft, _ = router.create_draft_intent("100mm悬臂梁，材料结构钢，端部受1000N载荷")
    assert draft.is_executable is False

    class DummyExecutor:
        launcher = "dummy"

    agent = AbaqusAIAgent(executor=DummyExecutor())
    res = agent.solve_requirement(draft)
    assert res.status == TaskStatus.BLOCKED
    assert "Draft engineering intents" in res.errors[0]
    assert res.summary_card.get("status") == "DRAFT_INTENT_BLOCKED"


def test_evidence_conflict_flag_rejection():
    """Verify that evidence with explicit conflict: True marker is rejected."""
    from abaqus_ai_agent.typesafe_intent import _is_unverified_or_expired_evidence, _validate_dimensions_entity

    assert _is_unverified_or_expired_evidence({"conflict": True}) is True
    assert _is_unverified_or_expired_evidence({"conflict": "true"}) is True
    assert _is_unverified_or_expired_evidence({"conflict": False}) is False

    ok, _, err = _validate_dimensions_entity({"length": 100.0, "conflict": True})
    assert ok is False
    assert err == "unverified_or_expired_evidence"


def test_boundary_condition_strict_type_and_displacement_dofs():
    """Verify that substring BC types (e.g. not_fixed) and displacement BCs missing DOFs are rejected."""
    from abaqus_ai_agent.typesafe_intent import _validate_boundary_conditions_entity

    # Substring illegal type
    ok, _, err = _validate_boundary_conditions_entity({"type": "not_fixed", "region": "RootFace"})
    assert ok is False
    assert "unsupported_boundary_condition_type_not_fixed" in str(err)

    # Displacement BC missing DOFs
    ok, _, err = _validate_boundary_conditions_entity({"type": "displacement", "region": "RootFace"})
    assert ok is False
    assert err == "displacement_bc_missing_constrained_dofs"

    # Displacement BC with valid DOFs
    ok, norm, _ = _validate_boundary_conditions_entity({"type": "displacement", "region": "RootFace", "dofs": (1, 2, 3)})
    assert ok is True
    assert norm[0]["type"] == "displacement"
    assert norm[0]["dofs"] == (1, 2, 3)


def test_load_type_strict_matching_and_thermal_bc_magnitude():
    """Verify exact load type whitelist and mandatory thermal magnitude requirement."""
    from abaqus_ai_agent.typesafe_intent import _validate_loads_entity, _validate_thermal_bcs_entity

    # Substring illegal load type
    ok, _, err = _validate_loads_entity({"type": "not_pressure", "magnitude": 100.0, "region": "TopFace"}, require_region=True)
    assert ok is False
    assert "unsupported_load_type_not_pressure" in str(err)

    # Thermal BC missing magnitude must be rejected
    ok, _, err = _validate_thermal_bcs_entity({"type": "temperature", "region": "HotEnd"})
    assert ok is False
    assert err == "missing_or_invalid_thermal_magnitude"

    # Valid thermal BC with magnitude
    ok, norm, _ = _validate_thermal_bcs_entity({"type": "temperature", "region": "HotEnd", "magnitude": 100.0})
    assert ok is True
    assert norm[0]["magnitude"] == 100.0


def test_acceptance_criteria_operator_whitelist():
    """Verify that criteria with non-whitelisted operators are strictly rejected."""
    from abaqus_ai_agent.typesafe_intent import _validate_acceptance_criteria_entity

    ok, _, err = _validate_acceptance_criteria_entity({"metric": "stress", "limit": 300.0, "operator": "~="})
    assert ok is False
    assert "invalid_criteria_operator_~=" in str(err)

    ok, norm, _ = _validate_acceptance_criteria_entity({"metric": "stress", "limit": 300.0, "operator": "<="})
    assert ok is True
    assert norm[0]["operator"] == "<="


def test_dimension_keys_whitelist_rejection():
    """Verify that dicts without recognizable dimension keys (e.g. stress: 300) are rejected."""
    from abaqus_ai_agent.typesafe_intent import _validate_dimensions_entity

    ok, _, err = _validate_dimensions_entity({"stress": 300.0})
    assert ok is False
    assert err == "no_valid_dimension_keys_found"

    ok, norm, _ = _validate_dimensions_entity({"length": 100.0, "width": 20.0})
    assert ok is True
    assert norm["length"] == 100.0


def test_load_magnitude_conflict_detection():
    """Verify that same load type with conflicting magnitude (>5% deviation) triggers clarification."""
    router = JevIntentRouter(mode="offline")
    prompt = "100mm悬臂梁端部受1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm。"
    context = {
        "loads": [{"type": "concentrated_force", "region": "TipFace", "magnitude": 5000.0}],
    }
    res = router.route(prompt, context=context)
    assert res.status == "NEEDS_CLARIFICATION"
    assert any("conflict_load_magnitude" in req for req in res.missing_requirements)


def test_geometric_region_de_forgery_contract():
    """Verify that intent construction never forges FixedFace when explicit region is not provided,
    and preserves verified context boundary regions without overwriting them."""
    router = JevIntentRouter(mode="offline")

    # 1. When context provides verified boundary conditions on custom region (e.g. Surface-Root)
    custom_ctx = {
        "boundary_conditions": [{"type": "encastre", "region": "Surface-Root", "dofs": (1, 2, 3, 4, 5, 6)}],
    }
    prompt = "100mm悬臂梁端部受1000N垂直载荷，材料为结构钢，校核端部挠度不超过2.5mm。"
    res = router.route(prompt, context=custom_ctx)
    assert res.status == "ROUTED"
    assert res.intent is not None
    # Must preserve the verified context region "Surface-Root", never overwrite with "FixedFace"
    assert any(bc.get("region") == "Surface-Root" for bc in res.intent.boundary_conditions)
    assert not any(bc.get("region") == "FixedFace" for bc in res.intent.boundary_conditions)


def test_draft_intent_compiler_rejected():
    """Verify that compiler compile_engineering_intent strictly rejects non-executable intent."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import compile_engineering_intent

    non_exec_intent = EngineeringIntent(
        id="NON_EXEC_01",
        kind="linear_static",
        description="test",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        is_executable=False,
    )
    with pytest.raises(ValueError, match="Draft or non-executable"):
        compile_engineering_intent(non_exec_intent)


def test_context_conflict_detection_prevents_silent_override():
    """Verify that contradictory specifications between prompt and context trigger NEEDS_CLARIFICATION."""
    router = JevIntentRouter(mode="offline")
    prompt = "100mm梁受1000N力，固定根部，材料为铝合金。"
    context = {"material": {"name": "Structural_Steel", "elastic_modulus": 210000.0, "poisson_ratio": 0.3}}

    res = router.route(prompt, context=context)
    assert res.status == "NEEDS_CLARIFICATION"
    assert any("conflict_material_specification" in item for item in res.missing_requirements)


def test_context_unverified_and_invalid_physics_rejected():
    """Verify that UNVERIFIED context and physically invalid Poisson ratio (nu=0.5 singularity) are rejected."""
    router = JevIntentRouter(mode="offline")
    prompt = "悬臂梁受1000N力，固定端。"

    # UNVERIFIED
    ctx_unverified = {
        "dimensions": {"status": "UNVERIFIED", "value": 100.0},
        "material": {"verified": False, "name": "Steel"},
    }
    res_unv = router.route(prompt, context=ctx_unverified)
    assert res_unv.status == "NEEDS_CLARIFICATION"
    assert "missing_geometry_dimensions" in res_unv.missing_requirements
    assert "missing_material_specification" in res_unv.missing_requirements

    # Singular Poisson ratio (nu=0.5)
    ctx_singular = {
        "dimensions": [{"value": 100.0, "unit": "mm"}],
        "material": {"name": "Steel", "poisson_ratio": 0.5},
    }
    res_sing = router.route(prompt, context=ctx_singular)
    assert res_sing.status == "NEEDS_CLARIFICATION"
    assert "missing_material_specification" in res_sing.missing_requirements


def test_strict_entity_validation_bc_loads_dimensions():
    """Verify that malformed entities in context (missing region, magnitude, invalid units) are rejected."""
    from abaqus_ai_agent.typesafe_intent import (
        _validate_boundary_conditions_entity,
        _validate_dimensions_entity,
        _validate_loads_entity,
    )

    # 1. Boundary conditions missing region or bare strings
    ok, _, err = _validate_boundary_conditions_entity("fixed")
    assert ok is False
    assert err in ("bare_string_without_region", "unsupported_boundary_conditions_type")

    ok, _, err = _validate_boundary_conditions_entity({"type": "encastre"})
    assert ok is False
    assert err == "missing_boundary_condition_region"

    # 2. Loads in context missing magnitude or missing region
    ok, _, err = _validate_loads_entity({"type": "pressure", "region": "TopFace"}, require_region=True)
    assert ok is False
    assert err == "missing_or_non_finite_load_magnitude"

    ok, _, err = _validate_loads_entity({"type": "pressure", "magnitude": 1.0}, require_region=True)
    assert ok is False
    assert err == "missing_load_region"

    # 3. Dimensions with unsupported units
    ok, _, err = _validate_dimensions_entity({"value": 100.0, "unit": "kg"})
    assert ok is False
    assert err == "invalid_dimension_unit_kg"


def test_zero_raw_context_fallback_for_unverified_entities():
    """Verify that unverified or invalid context evidence is never leaked into the final EngineeringIntent."""
    router = JevIntentRouter(mode="offline")
    # Prompt contains valid dimensions, material, and loads, but no boundary conditions
    prompt = "100mm悬臂梁，材料为结构钢，受1000N载荷，校核应力300MPa。"

    # Context contains unverified boundary conditions
    context = {
        "boundary_conditions": {"status": "UNVERIFIED", "type": "encastre", "region": "RootFace"}
    }
    res = router.route(prompt, context=context)
    # Must ask for clarification rather than silently falling back to raw context
    assert res.status == "NEEDS_CLARIFICATION"
    assert "missing_boundary_constraints" in res.missing_requirements


def test_thermal_zero_degree_magnitude_and_convection_radiation_contracts():
    """Verify 0.0 magnitude (e.g. 0°C) is valid, and convection/radiation require specific parameters."""
    from abaqus_ai_agent.typesafe_intent import _validate_thermal_bcs_entity

    # 1. 0.0 magnitude (0°C) must be accepted, not treated as falsy
    ok, norm, err = _validate_thermal_bcs_entity({"type": "temperature", "region": "ColdEnd", "temperature": 0.0})
    assert ok is True
    assert norm[0]["magnitude"] == 0.0

    # 2. Convection missing sink temperature or film coefficient
    ok, _, err = _validate_thermal_bcs_entity({"type": "convection", "region": "OuterSurface", "magnitude": 100.0})
    assert ok is False
    assert err == "convection_missing_ambient_temp_or_film_coefficient"

    # Valid convection
    ok, norm, _ = _validate_thermal_bcs_entity({
        "type": "convection",
        "region": "OuterSurface",
        "magnitude": 25.0,
        "sink_temperature": 25.0,
        "film_coefficient": 15.0,
    })
    assert ok is True

    # 3. Radiation missing emissivity or ambient temperature
    ok, _, err = _validate_thermal_bcs_entity({"type": "radiation", "region": "OuterSurface", "magnitude": 300.0})
    assert ok is False
    assert err == "radiation_missing_ambient_temp_or_emissivity"

    # Valid radiation
    ok, norm, _ = _validate_thermal_bcs_entity({
        "type": "radiation",
        "region": "OuterSurface",
        "magnitude": 300.0,
        "ambient_temperature": 293.15,
        "emissivity": 0.85,
    })
    assert ok is True


def test_load_magnitude_must_be_strictly_non_zero():
    """Verify that zero magnitude loads are rejected with load_magnitude_must_be_non_zero."""
    from abaqus_ai_agent.typesafe_intent import _validate_loads_entity

    ok, _, err = _validate_loads_entity({"type": "concentrated_force", "magnitude": 0.0, "region": "TipFace"})
    assert ok is False
    assert err == "load_magnitude_must_be_non_zero"


def test_displacement_bc_dof_range_and_non_empty():
    """Verify that displacement BC dofs must be non-empty and bounded in 1..6."""
    from abaqus_ai_agent.typesafe_intent import _validate_boundary_conditions_entity

    ok, _, err = _validate_boundary_conditions_entity({"type": "displacement", "region": "RootFace", "dofs": []})
    assert ok is False
    assert err == "displacement_bc_missing_or_invalid_dofs"

    ok, _, err = _validate_boundary_conditions_entity({"type": "displacement", "region": "RootFace", "dofs": [7]})
    assert ok is False
    assert err == "displacement_bc_missing_or_invalid_dofs"


def test_acceptance_criteria_metrics_whitelist_enforcement():
    """Verify that non-whitelisted metrics are rejected."""
    from abaqus_ai_agent.typesafe_intent import _validate_acceptance_criteria_entity

    ok, _, err = _validate_acceptance_criteria_entity({"metric": "arbitrary_unknown_foo", "limit": 100.0})
    assert ok is False
    assert "unsupported_criteria_metric_arbitrary_unknown_foo" in str(err)

    ok, norm, _ = _validate_acceptance_criteria_entity({"metric": "max_mises", "limit": 355.0})
    assert ok is True
    assert norm[0]["metric"] == "max_mises"


def test_material_property_strictness_rejects_missing_poisson():
    """Verify material having only elastic_modulus without poisson_ratio is blocked as unverified_material_properties."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode="offline")
    prompt = "100mm悬臂梁端部受1000N垂直载荷，固定根部，校核端部挠度不超过2.5mm。"

    # Context provides material with E but NO nu
    incomplete_mat_ctx = {
        "material": {"name": "Custom_Steel", "elastic_modulus": 210000.0},
    }
    res = router.route(prompt, context=incomplete_mat_ctx)
    assert res.status == "NEEDS_CLARIFICATION"
    assert "unverified_material_properties" in res.missing_requirements

    # Complete material with both E and nu
    complete_mat_ctx = {
        "material": {"name": "Custom_Steel", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
    }
    res_ok = router.route(prompt, context=complete_mat_ctx)
    assert res_ok.status == "ROUTED"
    assert res_ok.intent is not None
    assert res_ok.intent.material.get("has_verified_properties") is True


def test_mechanical_load_requires_explicit_application_region():
    """Verify mechanical load lacking an application region fails closed with missing_load_application_region."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode="offline")
    # Prompt specifies 1000N load, but omits application region (no 端部 / 顶面 / tip / top)
    unplaced_load_prompt = "100mm悬臂梁施加1000N垂直载荷，材料为结构钢，固定根部，校核挠度不超过2.5mm。"
    res = router.route(unplaced_load_prompt)
    assert res.status == "NEEDS_CLARIFICATION"
    assert "missing_load_application_region" in res.missing_requirements

    # When application region is explicitly provided (端部 -> TipFace)
    placed_load_prompt = "100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm。"
    res_ok = router.route(placed_load_prompt)
    assert res_ok.status == "ROUTED"
    assert res_ok.intent is not None
    assert len(res_ok.intent.loads) > 0
    for ld in res_ok.intent.loads:
        assert bool(ld.get("region")) is True
        assert ld["region"] == "TipFace"


def test_thermal_bc_bare_keywords_rejected_without_entity_data():
    """Verify bare thermal keywords (e.g. 对流, 辐射) without parameters/regions are strictly rejected."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode="offline")
    # Bare keyword without temperatures, film coefficients, or regions
    bare_kw_prompt = "500mm导热棒，材料为结构钢，对流换热分析，计算温度分布。"
    res = router.route(bare_kw_prompt)
    assert res.status == "NEEDS_CLARIFICATION"
    assert "missing_thermal_boundary_conditions" in res.missing_requirements

    # Real thermal BCs with temperatures and regions
    real_th_prompt = "500mm导热棒，材料为结构钢，热端固定100°C，冷端固定20°C，计算稳态温度梯度分布。"
    res_ok = router.route(real_th_prompt)
    assert res_ok.status == "ROUTED"
    assert res_ok.intent is not None
    assert len(res_ok.intent.boundary_conditions) > 0
    th_regions = {bc.get("region") for bc in res_ok.intent.boundary_conditions}
    assert "HotEnd" in th_regions
    assert "ColdEnd" in th_regions


def test_region_grounding_status_in_intent_metadata():
    """Verify semantic candidate regions are tagged SEMANTIC_CANDIDATE_UNRESOLVED,
    while verified topology models are strictly verified via 1-to-1 subset matching."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode="offline")
    prompt = "100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm。"

    # Prompt only: semantic candidates (RootFace for BC, TipFace for load)
    res_semantic = router.route(prompt)
    assert res_semantic.status == "ROUTED"
    assert res_semantic.intent.metadata["region_grounding_status"] == "SEMANTIC_CANDIDATE_UNRESOLVED"

    # Incomplete topology context: has TipFace and FixedFace, but missing RootFace!
    # Must remain SEMANTIC_CANDIDATE_UNRESOLVED (rejecting false-positive nominal grounding)
    incomplete_ctx = {
        "inp_evidence": {
            "verified": True,
            "parts": ["BeamPart"],
            "surfaces": ["FixedFace", "TipFace"],
        }
    }
    res_incomplete = router.route(prompt, context=incomplete_ctx)
    assert res_incomplete.status == "ROUTED"
    assert res_incomplete.intent.metadata["region_grounding_status"] == "SEMANTIC_CANDIDATE_UNRESOLVED"

    # Context with complete 1-to-1 matching verified topology evidence (RootFace and TipFace)
    complete_ctx = {
        "inp_evidence": {
            "verified": True,
            "parts": ["BeamPart"],
            "surfaces": ["RootFace", "TipFace"],
        }
    }
    res_grounded = router.route(prompt, context=complete_ctx)
    assert res_grounded.status == "ROUTED"
    assert res_grounded.intent.metadata["region_grounding_status"] == "MODEL_TOPOLOGY_GROUNDED"


def test_load_region_clause_scoping_does_not_steal_from_criteria():
    """Verify clause scoping prevents loads without explicit application regions from stealing '端部' from acceptance criteria."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter, _extract_prompt_load_region

    # Bare load clause: '100mm悬臂梁施加1000N垂直载荷' lacks explicit load application face.
    # Acceptance clause: '校核端部挠度不超过2.5mm' mentions '端部', but must NOT be stolen!
    trap_prompt = "100mm悬臂梁施加1000N垂直载荷，固定根部，校核端部挠度不超过2.5mm。"

    region = _extract_prompt_load_region(trap_prompt, "concentrated_force")
    assert region is None  # Anti-Theft: region must NOT be TipFace!

    router = JevIntentRouter(mode="offline")
    res = router.route(trap_prompt)
    assert res.status == "NEEDS_CLARIFICATION"
    assert "missing_load_application_region" in res.missing_requirements


def test_thermal_bc_normalization_preserves_convection_and_radiation_params():
    """Verify that thermal BC validator preserves ambient temperature, film coefficient, and emissivity."""
    from abaqus_ai_agent.typesafe_intent import _validate_thermal_bcs_entity, _extract_prompt_thermal_bcs

    # Convection entity validation & preservation
    conv_input = {
        "type": "convection",
        "region": "TopFace",
        "magnitude": 25.0,
        "ambient_temperature": 25.0,
        "film_coefficient": 150.0,
        "unit": "W/m2-K",
    }
    ok, norm_conv, err = _validate_thermal_bcs_entity(conv_input)
    assert ok is True
    assert norm_conv[0]["ambient_temperature"] == 25.0
    assert norm_conv[0]["film_coefficient"] == 150.0
    assert norm_conv[0]["unit"] == "W/m2-K"

    # Radiation entity validation & preservation
    rad_input = {
        "type": "radiation",
        "region": "HotEnd",
        "magnitude": 500.0,
        "ambient_temperature": 20.0,
        "emissivity": 0.85,
    }
    ok_rad, norm_rad, err_rad = _validate_thermal_bcs_entity(rad_input)
    assert ok_rad is True
    assert norm_rad[0]["ambient_temperature"] == 20.0
    assert norm_rad[0]["emissivity"] == 0.85

    # Zero Forgery: Heat flux without explicit region does NOT forge 'Surface'
    flux_without_region = _extract_prompt_thermal_bcs("计算热传导，热流 1000 W/m2，冷端固定20°C。")
    flux_bcs = [b for b in flux_without_region if b["type"] == "heat_flux"]
    assert len(flux_bcs) == 1
    assert flux_bcs[0]["region"] is None  # Must NOT be 'Surface'!


def test_material_reference_library_distinguished_from_verified():
    """Verify standard reference library assumptions are explicitly tracked and distinguished from verified model cards."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode="offline")
    prompt = "100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm。"

    # Prompt with standard steel keyword: tagged REFERENCE_LIBRARY and assumption=True
    res = router.route(prompt)
    assert res.status == "ROUTED"
    assert res.intent.metadata["material_evidence_level"] == "REFERENCE_LIBRARY"
    assert res.intent.metadata["material_assumption"] is True

    # 2. Context with user-provided numerical properties: tagged USER_EXPLICIT_VALUES and assumption=False
    user_explicit_ctx = {
        "material": {
            "name": "Structural_Steel_Custom",
            "elastic_modulus": 206000.0,
            "poisson_ratio": 0.29,
            "unit": "MPa",
        }
    }
    res_user = router.route(prompt, context=user_explicit_ctx)
    assert res_user.status == "ROUTED"
    assert res_user.intent.metadata["material_evidence_level"] == "USER_EXPLICIT_VALUES"
    assert res_user.intent.metadata["material_assumption"] is False

    # 3. Context with verified INP model card: tagged MODEL_CARD_VERIFIED and assumption=False
    model_card_ctx = {
        "inp_evidence": {
            "verified": True,
            "material": {
                "name": "Structural_Steel_Certified",
                "elastic_modulus": 210000.0,
                "poisson_ratio": 0.30,
            },
        }
    }
    res_card = router.route(prompt, context=model_card_ctx)
    assert res_card.status == "ROUTED"
    assert res_card.intent.metadata["material_evidence_level"] == "MODEL_CARD_VERIFIED"
    assert res_card.intent.metadata["material_assumption"] is False


def test_no_speculative_region_when_prompt_only_says_fixed():
    """Verify that prompt with bare '固定' without location does not forge RootFace and fails closed."""
    from abaqus_ai_agent.typesafe_intent import _extract_prompt_boundary_conditions, JevIntentRouter

    # Bare fixed prompt
    bcs = _extract_prompt_boundary_conditions("100mm悬臂梁，材料结构钢，端部受1000N载荷，固定，校核挠度。")
    assert bcs == []  # No region forged

    router = JevIntentRouter(mode="offline")
    res = router.route("100mm悬臂梁，材料结构钢，端部受1000N载荷，固定，校核端部挠度不超过2mm。")
    assert res.status == "NEEDS_CLARIFICATION"
    assert "missing_boundary_constraints" in res.missing_requirements


def test_unverified_material_properties_clarification_in_elastic_domains():
    """Verify that a material entity with name only but no properties triggers clarification in elastic domains."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode="offline")
    prompt = "100mm悬臂梁，端部受1000N载荷，固定根部，校核端部挠度不超过2mm。"
    context = {
        "material": {"name": "Uncharacterized_Composite_X"},
    }
    res = router.route(prompt, context=context)
    assert res.status == "NEEDS_CLARIFICATION"
    assert "unverified_material_properties" in res.missing_requirements


def test_contradictory_load_and_bc_types_trigger_clarification():
    """Verify that contradictions in load types and boundary condition types trigger clarification."""
    router = JevIntentRouter(mode="offline")

    # Contradiction in load type: prompt asks for 1000N concentrated force, context provides pressure
    prompt_load = "100mm悬臂梁，材料结构钢，固定端部，施加1000N集中力，校核应力300MPa。"
    ctx_load = {"loads": {"type": "pressure", "magnitude": 2.5, "region": "TopFace"}}
    res_load = router.route(prompt_load, context=ctx_load)
    assert res_load.status == "NEEDS_CLARIFICATION"
    assert any("conflict_load_type" in item for item in res_load.missing_requirements)

    # Contradiction in BC type: prompt says simply supported, context provides encastre/fixed
    prompt_bc = "100mm梁受1000N载荷，简支约束，材料为结构钢，校核应力300MPa。"
    ctx_bc = {"boundary_conditions": {"type": "encastre", "region": "RootFace"}}
    res_bc = router.route(prompt_bc, context=ctx_bc)
    assert res_bc.status == "NEEDS_CLARIFICATION"
    assert any("conflict_boundary_constraints" in item for item in res_bc.missing_requirements)


def test_grounding_rejects_part_names_and_populates_region_resolutions():
    """Verify that part names cannot serve as surface/set targets, resolving to 'unresolved' and SEMANTIC_CANDIDATE_UNRESOLVED."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode="offline")
    prompt = "100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm。"

    # Context provides 'parts' containing 'RootFace' and 'TipFace', but NO surfaces or sets!
    # A part is NOT a valid topological boundary/load target.
    part_only_ctx = {
        "inp_evidence": {
            "verified": True,
            "parts": ["RootFace", "TipFace"],
        }
    }
    res = router.route(prompt, context=part_only_ctx)
    assert res.status == "ROUTED"
    # Must remain unresolved because parts are not surfaces or sets
    assert res.intent.metadata["region_grounding_status"] == "SEMANTIC_CANDIDATE_UNRESOLVED"
    resolutions = res.intent.metadata["region_resolutions"]
    assert "RootFace" in resolutions
    assert resolutions["RootFace"]["resolved"] is False
    assert resolutions["RootFace"]["target_type"] == "unresolved"
    assert "TipFace" in resolutions
    assert resolutions["TipFace"]["resolved"] is False


def test_grounding_rejects_string_false_in_inp_evidence():
    """Verify that inp_evidence with verified: 'false' or non-boolean is strictly rejected."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode="offline")
    prompt = "100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm。"

    # String "false" is truthy in Python, but must be rejected by strict boolean check!
    fake_ctx = {
        "inp_evidence": {
            "verified": "false",
            "surfaces": ["RootFace", "TipFace"],
        }
    }
    res = router.route(prompt, context=fake_ctx)
    assert res.status == "ROUTED"
    assert res.intent.metadata["region_grounding_status"] == "SEMANTIC_CANDIDATE_UNRESOLVED"
    assert res.intent.metadata["region_resolutions"]["RootFace"]["resolved"] is False


def test_cantilever_beam_without_explicit_tip_requires_clarification():
    """Verify that 'cantilever beam with 1000N load' without explicit tip location fails closed with missing_load_application_region."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode="offline")
    # 'cantilever' defines structural form, NOT load application location
    prompt = "100mm cantilever steel beam with 1000N load, fixed root, check deflection <= 2mm"
    res = router.route(prompt)
    assert res.status == "NEEDS_CLARIFICATION"
    assert "missing_load_application_region" in res.missing_requirements

    # With explicit tip location
    prompt_with_tip = "100mm cantilever steel beam with 1000N load at tip, fixed root, check deflection <= 2mm"
    res_ok = router.route(prompt_with_tip)
    assert res_ok.status == "ROUTED"
    assert any(ld.get("region") == "TipFace" for ld in res_ok.intent.loads)


def test_thermal_bc_convection_radiation_end_to_end_preservation():
    """Verify convection and radiation parameters flow end-to-end into EngineeringIntent.boundary_conditions."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode="offline")
    prompt = "500mm导热棒，材料为结构钢，计算稳态热传导温度场。"
    th_ctx = {
        "thermal_bcs": [
            {
                "type": "convection",
                "region": "OuterSurface",
                "magnitude": 25.0,
                "ambient_temperature": 25.0,
                "film_coefficient": 150.0,
                "unit": "W/m2-K",
            },
            {
                "type": "radiation",
                "region": "HotEnd",
                "magnitude": 500.0,
                "ambient_temperature": 20.0,
                "emissivity": 0.85,
            },
        ]
    }
    res = router.route(prompt, context=th_ctx)
    assert res.status == "ROUTED"
    assert res.intent is not None
    assert len(res.intent.boundary_conditions) == 2

    conv_bc = next(b for b in res.intent.boundary_conditions if b["type"] == "convection")
    assert conv_bc["ambient_temperature"] == 25.0
    assert conv_bc["film_coefficient"] == 150.0
    assert conv_bc["canonical_ambient_temperature_c"] == 25.0
    assert conv_bc["canonical_ambient_temperature_k"] == 298.15

    rad_bc = next(b for b in res.intent.boundary_conditions if b["type"] == "radiation")
    assert rad_bc["ambient_temperature"] == 20.0
    assert rad_bc["emissivity"] == 0.85
    assert rad_bc["canonical_ambient_temperature_c"] == 20.0
    assert rad_bc["canonical_ambient_temperature_k"] == 293.15


def test_thermal_bc_regex_rejects_bare_numbers_without_unit_or_anchor():
    """Verify that numbers lacking temperature units or keywords are not misparsed as temperatures."""
    from abaqus_ai_agent.typesafe_intent import _extract_prompt_thermal_bcs

    # '顶面 1000 N' or '端部 500' without temperature unit/keyword must NOT be parsed as temperature
    bcs = _extract_prompt_thermal_bcs("100mm悬臂梁，顶面 1000 N 压力，端部 500，固定根部。")
    assert len(bcs) == 0

    # With explicit unit
    bcs_valid = _extract_prompt_thermal_bcs("导热棒热端固定100°C，冷端20C。")
    assert len(bcs_valid) == 2
    assert any(b["region"] == "HotEnd" and b["magnitude"] == 100.0 for b in bcs_valid)
    assert any(b["region"] == "ColdEnd" and b["magnitude"] == 20.0 for b in bcs_valid)


def test_thermal_flux_without_region_fails_closed_end_to_end():
    """Verify that a heat flux without explicit application region fails closed in routing."""
    from abaqus_ai_agent.typesafe_intent import JevIntentRouter

    router = JevIntentRouter(mode="offline")
    prompt = "500mm导热棒，材料为结构钢，热流 1000 W/m2，冷端固定20°C，计算稳态温度梯度。"
    res = router.route(prompt)
    assert res.status == "NEEDS_CLARIFICATION"
    assert "missing_thermal_boundary_conditions" in res.missing_requirements


def test_jev_engineering_benchmark_shadow_mode_reporting():
    """Verify benchmark harness aggregates shadow mode differences and unconfigured status."""
    # 1. Unconfigured external provider in shadow mode (isolated from developer ambient env credentials)
    with patch.dict("os.environ", {}, clear=True):
        report_unconf = run_engineering_benchmark(mode="shadow")
    assert report_unconf["provider_type"] == "shadow_comparative_eval"
    assert report_unconf["is_offline_baseline"] is False
    assert report_unconf["shadow_metrics"] is not None
    assert report_unconf["shadow_metrics"]["evaluated_cases"] == 0
    assert report_unconf["shadow_metrics"]["error_categories"]["NOT_CONFIGURED"] == report_unconf["total_cases"]

    # 2. Injected external provider in shadow mode
    class MockEvaluator:
        model = "evaluator-v1"

        def is_configured(self) -> bool:
            return True

        def judge(self, prompt: str, timeout: float = 5.0) -> Dict[str, Any]:
            # Returns linear_static for all cases to observe divergence on thermal/contact cases
            return {
                "answers": {
                    "physics": {"choice": "linear_static", "confidence": 0.95},
                    "units": {"choice": "MM_N_MPA", "confidence": 0.95},
                    "solver": {"choice": "abaqus_standard", "confidence": 0.98},
                    "well_constrained": {"probability": 0.95},
                    "has_acceptance_criteria": {"probability": 0.90},
                    "completeness": {"score": 4.5},
                }
            }

    shadow_router = JevIntentRouter(mode="shadow", external_provider=MockEvaluator())
    report_eval = run_engineering_benchmark(router=shadow_router)
    sm = report_eval["shadow_metrics"]
    assert sm is not None
    assert sm["evaluated_cases"] == report_eval["total_cases"]
    assert sm["physics_matches"] > 0
    # Because MockEvaluator returns linear_static for thermal/contact, divergence must be captured
    assert len(sm["divergent_cases"]) > 0
    assert "PHYS-02-THERMAL" in sm["divergent_cases"]
    assert sm["physics_agreement_pct"] < 100.0
    assert sm["live_physics_accuracy_pct"] < 100.0
    assert len(sm["divergent_details"]) == len(sm["divergent_cases"])
    assert sm["avg_live_latency_ms"] >= 0.0
    assert sm["coverage_pct"] == 100.0
    assert sm["success_accuracy_pct"] == sm["live_physics_accuracy_pct"]
    assert sm["effective_accuracy_pct"] > 0.0

    # Test Markdown formatting of shadow mode
    md_report = format_markdown_report(report_eval)
    assert "## Shadow Dual-Run Comparative Audit" in md_report
    assert "External Evaluation Coverage" in md_report
    assert "Agreement with Baseline Rule Engine" in md_report
    assert "External Provider Success-Subset Accuracy" in md_report
    assert "External Provider End-to-End Effective Accuracy" in md_report
    assert "Average Latency" in md_report
    assert "### Divergent Cases Between Baseline and Live Provider" in md_report


def test_shadow_mode_live_latency_recorded_and_metadata_forwarded():
    """Verify shadow mode measures live latency (>0ms) and forwards shadow_diff into intent.metadata."""
    import time

    class LatencyTestingProvider:
        def is_configured(self) -> bool:
            return True

        def judge(self, prompt: str, timeout: float = 5.0) -> Dict[str, Any]:
            time.sleep(0.005)  # 5ms artificial sleep
            return {
                "answers": {
                    "physics": {"choice": "linear_static", "confidence": 0.99},
                    "units": {"choice": "MM_N_MPA", "confidence": 0.95},
                    "solver": {"choice": "abaqus_standard", "confidence": 0.98},
                    "well_constrained": {"probability": 0.95},
                    "has_acceptance_criteria": {"probability": 0.90},
                    "completeness": {"score": 4.5},
                }
            }

    router = EngineeringIntentRouter(
        mode="shadow",
        external_provider=LatencyTestingProvider(),
    )
    prompt = "100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm。"
    res = router.route(prompt)

    assert res.status == "ROUTED"
    assert res.intent is not None
    assert "shadow_diff" in res.intent.metadata
    sd = res.intent.metadata["shadow_diff"]
    assert sd["status"] == "EVALUATED"
    assert sd["live_latency_ms"] >= 3.0  # Measured accurately, not 0.0!
    assert sd["baseline_latency_ms"] >= 0.0
    assert sd["physics_match"] is True


def test_compiler_fails_closed_on_unresolved_grounding_for_step_file():
    """Verify compiler fails closed when external STEP file is used without resolved topological grounding."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, compile_engineering_intent

    intent = EngineeringIntent(
        id="STEP_UNRESOLVED_01",
        kind="linear_static",
        description="External bracket under load",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "Steel", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        boundary_conditions=({"type": "encastre", "region": "MountingHole"},),
        loads=({"type": "concentrated_force", "region": "LoadBearingEye", "magnitude": 1000.0},),
        metadata={
            "region_grounding_status": "SEMANTIC_CANDIDATE_UNRESOLVED",
            "region_resolutions": {
                "MountingHole": {"resolved": False, "target_type": "unresolved"},
                "LoadBearingEye": {"resolved": False, "target_type": "unresolved"},
            },
        },
    )

    step_geom = IntentGeometrySpec(
        shape="step_file",
        step_file_path="/path/to/bracket.step",
    )

    with pytest.raises(ValueError, match="geometry relies on external STEP file"):
        compile_engineering_intent(intent, geometry=step_geom, allow_missing_step_file=True)


def test_compiler_step_file_grounding_gate_rejects_dummy_and_invalid_mappings():
    """Verify compiler gate strictly validates referenced regions and rejects dummy dictionaries or invalid anchor points."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, compile_engineering_intent

    intent = EngineeringIntent(
        id="STEP_GATE_STRICT_01",
        kind="linear_static",
        description="Bracket with referenced regions",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "Steel", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        boundary_conditions=({"type": "encastre", "region": "MountingHole"},),
        loads=({"type": "concentrated_force", "region": "LoadBearingEye", "magnitude": 1000.0},),
        metadata={},  # Omitted region_grounding_status must NOT bypass the gate!
    )
    step_geom = IntentGeometrySpec(shape="step_file", step_file_path="/path/to/part.step")

    # 1. Non-empty dummy dictionary that lacks the referenced regions
    dummy_grounded = {"UnrelatedFace": {"anchor_point": (0.0, 0.0, 0.0)}}
    with pytest.raises(ValueError, match="lack valid GroundedRegion mappings") as exc_info:
        compile_engineering_intent(intent, geometry=step_geom, allow_missing_step_file=True, grounded_regions=dummy_grounded)
    assert "MountingHole" in str(exc_info.value)
    assert "LoadBearingEye" in str(exc_info.value)

    # 2. Referenced regions present but have invalid coordinates (< 3 items or resolved: False)
    invalid_coords_grounded = {
        "MountingHole": {"anchor_point": (0.0, 0.0)},  # Invalid: only 2D
        "LoadBearingEye": {"anchor_points": []},         # Invalid: empty
    }
    with pytest.raises(ValueError, match="lack valid GroundedRegion mappings"):
        compile_engineering_intent(intent, geometry=step_geom, allow_missing_step_file=True, grounded_regions=invalid_coords_grounded)

    # 3. Explicitly unresolved dict
    unresolved_grounded = {
        "MountingHole": {"resolved": False, "anchor_point": (0.0, 0.0, 0.0)},
        "LoadBearingEye": {"anchor_point": (10.0, 0.0, 0.0)},
    }
    with pytest.raises(ValueError, match="lack valid GroundedRegion mappings") as exc_unres:
        compile_engineering_intent(intent, geometry=step_geom, allow_missing_step_file=True, grounded_regions=unresolved_grounded)
    assert "MountingHole" in str(exc_unres.value)


def test_compiler_step_file_grounding_gate_accepts_valid_grounded_regions():
    """Verify compiler gate successfully compiles when all referenced regions have genuine GroundedRegion mappings."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, compile_engineering_intent

    intent = EngineeringIntent(
        id="STEP_GATE_PASS_01",
        kind="linear_static",
        description="Bracket with valid grounding",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "Steel", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        boundary_conditions=({"type": "encastre", "region": "MountingHole"},),
        loads=({"type": "concentrated_force", "region": "LoadBearingEye", "magnitude": 1000.0},),
        metadata={
            "grounded_regions": {
                "MountingHole": {"surface": "Surf-Mount", "anchor_points": [(0.0, 0.0, 0.0)]},
                "LoadBearingEye": {"anchor_point": (50.0, 10.0, 0.0)},
            }
        },
    )
    step_geom = IntentGeometrySpec(shape="step_file", step_file_path="/path/to/part.step")

    # Should not raise ValueError for missing/invalid grounded regions
    plan = compile_engineering_intent(intent, geometry=step_geom, allow_missing_step_file=True)
    assert plan is not None
    assert plan.model_name is not None
    assert len(plan.actions) > 0


def test_benchmark_cases_sha256_hash_integrity():
    """Verify compute_benchmark_cases_hash produces deterministic SHA-256 and detects mutations."""
    from dataclasses import replace
    from tools.jev_engineering_benchmark import (
        BENCHMARK_CASES,
        compute_benchmark_cases_hash,
        run_engineering_benchmark,
    )

    report = run_engineering_benchmark()
    expected_hash = compute_benchmark_cases_hash(BENCHMARK_CASES)
    assert report["cases_hash"] == expected_hash
    assert expected_hash.startswith("sha256_")
    assert len(expected_hash) == 7 + 64

    # Verify sensitivity: mutating even one prompt alters the hash
    mutated_cases = list(BENCHMARK_CASES)
    mutated_cases[0] = replace(mutated_cases[0], prompt=mutated_cases[0].prompt + " altered")
    mutated_hash = compute_benchmark_cases_hash(mutated_cases)
    assert mutated_hash != expected_hash
    assert mutated_hash.startswith("sha256_")

    # Verify sensitivity: mutating even one description alters the hash
    mutated_cases_desc = list(BENCHMARK_CASES)
    mutated_cases_desc[0] = replace(mutated_cases_desc[0], description=mutated_cases_desc[0].description + " altered desc")
    mutated_hash_desc = compute_benchmark_cases_hash(mutated_cases_desc)
    assert mutated_hash_desc != expected_hash
    assert mutated_hash_desc != mutated_hash


def test_shadow_mode_status_conservation_law():
    """Verify shadow evaluation satisfies status conservation: N_total = N_eval + N_fail + N_not_conf."""
    from tools.jev_engineering_benchmark import run_engineering_benchmark

    # 1. Unconfigured scenario: all cases are NOT_CONFIGURED (isolated from ambient env)
    with patch.dict("os.environ", {}, clear=True):
        report_unconf = run_engineering_benchmark(mode="shadow")
    sm_u = report_unconf["shadow_metrics"]
    assert sm_u["status_conservation_verified"] is True
    assert sm_u["total_cases"] == sm_u["evaluated_cases"] + sm_u["failed_cases"] + sm_u["not_configured_cases"]
    assert sm_u["not_configured_cases"] == sm_u["total_cases"]
    assert sm_u["evaluated_cases"] == 0
    assert sm_u["failed_cases"] == 0

    # 2. Configured evaluator scenario: all cases are EVALUATED
    class MockPerfectEvaluator:
        def is_configured(self) -> bool:
            return True

        def judge(self, prompt: str, timeout: float = 5.0) -> Dict[str, Any]:
            return {
                "answers": {
                    "physics": {"choice": "linear_static", "confidence": 0.99},
                    "units": {"choice": "MM_N_MPA", "confidence": 0.95},
                    "solver": {"choice": "abaqus_standard", "confidence": 0.98},
                    "well_constrained": {"probability": 0.95},
                    "has_acceptance_criteria": {"probability": 0.90},
                    "completeness": {"score": 4.5},
                }
            }

    shadow_router = JevIntentRouter(mode="shadow", external_provider=MockPerfectEvaluator())
    report_eval = run_engineering_benchmark(router=shadow_router)
    sm_e = report_eval["shadow_metrics"]
    assert sm_e["status_conservation_verified"] is True
    assert sm_e["total_cases"] == sm_e["evaluated_cases"] + sm_e["failed_cases"] + sm_e["not_configured_cases"]
    assert sm_e["evaluated_cases"] == sm_e["total_cases"]
    assert sm_e["failed_cases"] == 0
    assert sm_e["not_configured_cases"] == 0


def test_compiler_step_file_grounding_gate_rejects_unresolved_or_invalid_objects():
    """Verify GroundedRegion dataclass objects with resolved=False, invalid status, or confidence<=0 are rejected."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.grounding.feature_grounding import GroundedRegion
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, compile_engineering_intent

    intent = EngineeringIntent(
        id="STEP_OBJ_GATE_01",
        kind="linear_static",
        description="Bracket with GroundedRegion objects",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "Steel", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        boundary_conditions=({"type": "encastre", "region": "MountingHole"},),
        loads=({"type": "concentrated_force", "region": "LoadBearingEye", "magnitude": 1000.0},),
    )
    step_geom = IntentGeometrySpec(shape="step_file", step_file_path="/path/to/part.step")

    # 1. Object with status="NOT_FOUND"
    gr_not_found = GroundedRegion(
        target_semantic="MountingHole",
        entity_type="Face",
        entity_ids=("F_1",),
        anchor_point=(0.0, 0.0, 0.0),
        status="NOT_FOUND",
    )
    gr_valid = GroundedRegion(
        target_semantic="LoadBearingEye",
        entity_type="Face",
        entity_ids=("F_2",),
        anchor_point=(10.0, 0.0, 0.0),
        status="RESOLVED",
    )
    with pytest.raises(ValueError, match="lack valid GroundedRegion mappings") as exc1:
        compile_engineering_intent(intent, geometry=step_geom, allow_missing_step_file=True, grounded_regions={"MountingHole": gr_not_found, "LoadBearingEye": gr_valid})
    assert "MountingHole" in str(exc1.value)

    # 2. Object with confidence <= 0.0
    gr_zero_conf = GroundedRegion(
        target_semantic="MountingHole",
        entity_type="Face",
        entity_ids=("F_1",),
        anchor_point=(0.0, 0.0, 0.0),
        confidence=0.0,
        status="RESOLVED",
    )
    with pytest.raises(ValueError, match="lack valid GroundedRegion mappings") as exc2:
        compile_engineering_intent(intent, geometry=step_geom, allow_missing_step_file=True, grounded_regions={"MountingHole": gr_zero_conf, "LoadBearingEye": gr_valid})
    assert "MountingHole" in str(exc2.value)


def test_compiler_step_file_grounding_gate_rejects_nan_inf_bool_string_coordinates():
    """Verify coordinate components containing NaN, Inf, bool, or strings are strictly rejected."""
    import math
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, compile_engineering_intent

    intent = EngineeringIntent(
        id="STEP_COORDS_STRICT_01",
        kind="linear_static",
        description="Bracket with non-finite coordinates",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "Steel", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        boundary_conditions=({"type": "encastre", "region": "MountingHole"},),
        loads=({"type": "concentrated_force", "region": "LoadBearingEye", "magnitude": 1000.0},),
    )
    step_geom = IntentGeometrySpec(shape="step_file", step_file_path="/path/to/part.step")

    # NaN in anchor_point
    with pytest.raises(ValueError, match="lack valid GroundedRegion mappings"):
        compile_engineering_intent(
            intent, geometry=step_geom, allow_missing_step_file=True,
            grounded_regions={
                "MountingHole": {"anchor_point": (0.0, float("nan"), 0.0)},
                "LoadBearingEye": {"anchor_point": (10.0, 0.0, 0.0)},
            }
        )

    # Inf in anchor_points
    with pytest.raises(ValueError, match="lack valid GroundedRegion mappings"):
        compile_engineering_intent(
            intent, geometry=step_geom, allow_missing_step_file=True,
            grounded_regions={
                "MountingHole": {"anchor_points": [(0.0, 0.0, float("inf"))]},
                "LoadBearingEye": {"anchor_point": (10.0, 0.0, 0.0)},
            }
        )

    # Boolean in coordinates (bool is a subclass of int, must be rejected)
    with pytest.raises(ValueError, match="lack valid GroundedRegion mappings"):
        compile_engineering_intent(
            intent, geometry=step_geom, allow_missing_step_file=True,
            grounded_regions={
                "MountingHole": {"anchor_point": (True, 0.0, 0.0)},
                "LoadBearingEye": {"anchor_point": (10.0, 0.0, 0.0)},
            }
        )

    # String in coordinates
    with pytest.raises(ValueError, match="lack valid GroundedRegion mappings"):
        compile_engineering_intent(
            intent, geometry=step_geom, allow_missing_step_file=True,
            grounded_regions={
                "MountingHole": {"anchor_point": ("0.0", 0.0, 0.0)},
                "LoadBearingEye": {"anchor_point": (10.0, 0.0, 0.0)},
            }
        )


def test_compiler_step_file_grounding_gate_consumes_named_selectors_without_empty_findat():
    """Verify named sets/surfaces are directly consumed without generating empty findAt() calls."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, compile_engineering_intent

    intent = EngineeringIntent(
        id="STEP_NAMED_SELECTORS_01",
        kind="linear_static",
        description="Bracket with named set and named surface mappings",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "Steel", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        boundary_conditions=({"type": "encastre", "region": "FixedFace"},),
        loads=({"type": "pressure", "region": "PressureFace", "magnitude": 5.0},),
    )
    step_geom = IntentGeometrySpec(shape="step_file", step_file_path="/path/to/part.step")

    # 1. Providing consumable named set for BC and named surface for Load
    plan = compile_engineering_intent(
        intent,
        geometry=step_geom, allow_missing_step_file=True,
        grounded_regions={
            "FixedFace": {"set": "Hole_Fix_Set"},
            "PressureFace": {"surface": "Top_Pres_Surf"},
        },
    )
    assert plan is not None
    # Verify generated script consumes named set and surface directly without findAt()
    cae_script = plan.cae_script
    assert "a.sets['Hole_Fix_Set']" in cae_script
    assert "a.surfaces['Top_Pres_Surf']" in cae_script
    assert "findAt()" not in cae_script  # Never emit empty findAt()!

    # 2. Reject raw non-consumable selectors like raw faces without names or anchors
    with pytest.raises(ValueError, match="lack valid GroundedRegion mappings"):
        compile_engineering_intent(
            intent,
            geometry=step_geom, allow_missing_step_file=True,
            grounded_regions={
                "FixedFace": {"faces": [1, 2]},  # raw unconsumable selector
                "PressureFace": {"surface": "Top_Pres_Surf"},
            },
        )
