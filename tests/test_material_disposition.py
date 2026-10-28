"""REQ-4.8: material completeness must be classified before any solve path."""

import pytest

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition, PlasticProperties
from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, compile_engineering_intent
from abaqus_ai_agent.reasoning.material_catalog import classify_material_input
from abaqus_ai_agent.workflow.static import build_static_plan


def _intent(material, analysis="linear_static", description="check", metadata=None):
    return EngineeringIntent(
        id="MAT-DISP",
        kind=analysis,
        analysis_type=analysis,
        description=description,
        material=material,
        metadata={"geometry": IntentGeometrySpec(), **(metadata or {})},
    )


def test_family_query_is_screening_and_does_not_select_q235():
    disposition = classify_material_input("钢")
    assert disposition.status == "SCREENING"
    assert "Q235" in disposition.candidates
    assert disposition.allows_solve is False
    with pytest.raises(ValueError, match="SCREENING"):
        compile_engineering_intent(_intent("钢"))


def test_named_grade_is_linear_elastic_screening_not_plastic():
    disposition = classify_material_input("Q235", analysis="linear_static")
    assert disposition.status == "LINEAR_ELASTIC"
    plan = compile_engineering_intent(_intent("Q235"))
    assert "material_plastic" not in [a.action_type for a in plan.actions]
    with pytest.raises(ValueError, match="BLOCKED"):
        compile_engineering_intent(_intent("Q235", analysis="plasticity", description="residual strain"))


def test_scalar_card_blocks_hardening_claim_unless_ideal_plasticity_is_explicit():
    card = {"name": "LabHeat_42", "youngs_modulus": 200000.0, "poisson": 0.3, "yield_strength": 250.0}
    blocked = classify_material_input(card, analysis="elastoplastic")
    assert blocked.status == "BLOCKED"
    accepted = classify_material_input(
        {**card, "accept_ideal_plasticity": True},
        analysis="elastoplastic",
    )
    assert accepted.status == "IDEAL_PLASTIC_ASSUMPTION"
    plan = compile_engineering_intent(
        _intent({**card, "metadata": {"accept_ideal_plasticity": True}}, analysis="plasticity")
    )
    plastic = [a for a in plan.actions if a.action_type == "material_plastic"]
    assert plastic
    assert plastic[0].parameters["table"] == ((250.0, 0.0),)


def test_user_hardening_curve_is_emitted_and_catalog_curve_is_not_invented():
    card = {
        "name": "LabHeat_42",
        "youngs_modulus": 200000.0,
        "poisson": 0.3,
        "yield_strength": 250.0,
        "hardening_table": ((250.0, 0.0), (300.0, 0.02)),
    }
    reviewed = classify_material_input(card, analysis="plasticity")
    assert reviewed.status == "HARDENING_VERIFIED"
    assert reviewed.material.metadata.get("deck_reviewed") is True
    catalog = classify_material_input("Q235", analysis="plasticity", description="残余应变")
    assert catalog.status == "BLOCKED"


def test_condition_mismatch_and_workflow_bypass_fail_closed():
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        build_static_plan("M", {"name": "PA66-GF30", "youngs_modulus": 8000.0, "poisson": 0.35}, {})
    with pytest.raises(ValueError, match="SCREENING"):
        build_static_plan("M", "钢", {})


def test_acceptance_blocks_unreviewed_material_nonlinearity():
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_mises": 180.0},
        physics_domain="plasticity",
        material_disposition={"status": "BLOCKED"},
    )
    assert res.deliverable is False
    assert any("hardening_curve_not_deck_reviewed" in item for item in res.blocked)


def test_nlgeom_alone_does_not_demand_a_hardening_curve():
    material = MaterialDefinition(
        name="Q235",
        elastic=ElasticProperties(210000.0, 0.3),
        plastic=PlasticProperties(235.0),
        metadata={"catalog_reference_only": True, "yield_strength_mpa": 235.0},
    )
    disposition = classify_material_input(material, analysis="linear_static", description="nlgeom contact")
    assert disposition.status == "LINEAR_ELASTIC"
