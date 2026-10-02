"""Tests for Phase I.4 JEV-Powered Product UX & TypeSafe Intent Routing."""

from __future__ import annotations

from pathlib import Path

from abaqus_ai_agent.typesafe_intent import (
    ChoiceJudgment,
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
    intent, bundle = router.route_prompt_to_intent(prompt)

    assert bundle.physics_choice.value == "steady_thermal"
    assert bundle.unit_system_choice.value == "MM_N_MPA"
    assert intent.analysis_type == "steady_thermal"


def test_jev_intent_e2e_runner():
    out_file = ROOT / "machine_validation" / "i4_jev_intent_evidence.json"
    manifest = run_jev_intent_e2e(out_file)

    assert manifest["schema_version"] == "jev_intent_routing_v1"
    assert manifest["total_prompts"] == 3
    assert manifest["passed_prompts"] == 3
    assert manifest["all_passed"] is True
    assert out_file.is_file()
