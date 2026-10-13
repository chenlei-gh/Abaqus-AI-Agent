"""Tests for Phase I.4 JEV-Powered Product UX & TypeSafe Intent Routing."""

from __future__ import annotations

from pathlib import Path
import pytest

from abaqus_ai_agent.typesafe_intent import (
    ChoiceJudgment,
    IntentAmbiguityError,
    JevDecisionBundle,
    JevIntentRouter,
    NoulJudgment,
    ScoreJudgment,
)
from tools.i4_jev_intent_e2e import run_jev_intent_e2e

ROOT = Path(__file__).resolve().parent.parent


def test_jev_primitives_contracts():
    c = ChoiceJudgment(value="linear_static", confidence=0.98, distribution={"linear_static": 0.98})
    assert c.value == "linear_static"
    assert c.confidence == 0.98

    n1 = NoulJudgment(probability=0.85)
    assert n1.is_yes is True
    n2 = NoulJudgment(probability=0.25)
    assert n2.is_yes is False

    s = ScoreJudgment(score=4.5)
    assert s.score == 4.5


def test_jev_intent_router_static_prompt():
    router = JevIntentRouter()
    prompt = "对100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm和最大Mises应力不超过600MPa。"
    intent, bundle = router.route_prompt_to_intent(prompt)

    assert bundle.physics_choice.value == "linear_static"
    assert bundle.unit_system_choice.value == "MM_N_MPA"
    assert bundle.is_well_constrained_noul.is_yes is True
    assert bundle.completeness_score.score >= 4.0
    assert intent.material is not None
    assert intent.material["name"] == "Structural_Steel"
    assert len(intent.boundary_conditions) > 0
    assert len(intent.loads) > 0
    assert len(intent.acceptance_criteria) >= 2


def test_jev_intent_router_thermal_prompt():
    router = JevIntentRouter()
    prompt = "1D heat conduction bar with hot end at 100C and cold end at 0C. Check midpoint temperature."

    # Default strict=True must fail-closed on incomplete specification
    with pytest.raises(IntentAmbiguityError):
        router.route_prompt_to_intent(prompt)

    # Even explicit strict=False must fail-closed: executable intents are NEVER generated for ambiguous input
    with pytest.raises(IntentAmbiguityError):
        router.route_prompt_to_intent(prompt, strict=False)

    # Exploratory draft intent must be explicitly requested via create_draft_intent
    draft, bundle = router.create_draft_intent(prompt)
    assert draft.is_executable is False
    assert bundle.physics_choice.value == "steady_thermal"
    assert bundle.unit_system_choice.value == "MM_N_MPA"
    assert draft.analysis_type == "steady_thermal"


def test_jev_intent_e2e_runner(tmp_path: Path):
    out_file = tmp_path / "i4_jev_intent_evidence.json"
    manifest = run_jev_intent_e2e(out_file)

    assert manifest["schema_version"] == "jev_intent_routing_v1"
    assert manifest["total_prompts"] == 3
    assert manifest["passed_prompts"] == 3
    assert manifest["all_passed"] is True
    assert out_file.is_file()


def test_jev_intent_ambiguity_fails_closed():
    """Ambiguous prompts missing loads/materials/constraints must NOT silently pass."""
    router = JevIntentRouter()
    ambiguous_prompt = "帮我分析这个支架强度。"
    res = router.route(ambiguous_prompt)

    assert res.status == "NEEDS_CLARIFICATION"
    assert res.intent is None
    assert len(res.missing_requirements) >= 3
    assert "missing_geometry_dimensions" in res.missing_requirements
    assert "missing_material_specification" in res.missing_requirements
    assert "missing_applied_loads" in res.missing_requirements
    assert res.clarification_prompt is not None

    # Strict mode must raise explicit IntentAmbiguityError
    with pytest.raises(Exception) as excinfo:
        router.route_prompt_to_intent(ambiguous_prompt, strict=True)
    assert "Missing prerequisites" in str(excinfo.value)


def test_jev_intent_context_merge_unblocks_existing_model_evidence():
    """Verify that upstream model context (geometry, material, constraints) satisfies prerequisites without prompt duplication."""
    router = JevIntentRouter()
    # Prompt only specifies load and constraint, omitting dimensions and material
    prompt = "固定悬臂梁根部，端部施加1000N向下集中载荷。"

    # Without context -> fails closed due to missing dimensions & material
    res_no_ctx = router.route(prompt)
    assert res_no_ctx.status == "NEEDS_CLARIFICATION"
    assert "missing_geometry_dimensions" in res_no_ctx.missing_requirements
    assert "missing_material_specification" in res_no_ctx.missing_requirements

    # With model context -> prerequisites satisfied, successfully routes and merges context
    model_context = {
        "dimensions": [{"value": 200.0, "unit": "mm"}],
        "material": {
            "name": "Aluminum_6061",
            "elastic_modulus": 70000.0,
            "poisson_ratio": 0.33,
            "unit": "MPa",
        },
    }
    res_with_ctx = router.route(prompt, context=model_context)
    assert res_with_ctx.status == "ROUTED"
    assert res_with_ctx.intent is not None
    assert res_with_ctx.intent.material is not None
    assert res_with_ctx.intent.material["name"] == "Aluminum_6061"
    assert res_with_ctx.intent.metadata.get("context_merged") is True
    assert res_with_ctx.intent.metadata.get("dimensions") == [{"value": 200.0, "unit": "mm"}]
    assert len(res_with_ctx.intent.loads) > 0
    assert len(res_with_ctx.intent.boundary_conditions) > 0
