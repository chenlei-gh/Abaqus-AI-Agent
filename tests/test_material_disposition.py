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
        mesh_requirements={
            "global_size": 2.5,
            "primary_wall_thickness": 2.5,
            "primary_wall_thickness_source": "USER_SPECIFIED",
        },
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


def test_fibre_grade_is_refused_under_every_common_spelling():
    """Renaming the card must not walk through the fibre gate.

    PA6-GF50, PA6 50GF and the trade shorthand PA6G50 are the same filled
    grade. An earlier gate tested one spelling only, so the others resolved to
    LINEAR_ELASTIC with the same E and nu.
    """
    card = {"youngs_modulus": 16000.0, "poisson": 0.35}
    for name in (
        "PA6-GF50",
        "PA6+GF50",
        "PA6_GF50",
        "GF50",
        "PA6 50GF",
        "PA66 GF30",
        "PA66-GF30",
        "PA6G50",
        "PA66G30",
    ):
        disposition = classify_material_input({"name": name, **card}, analysis="linear_static")
        assert disposition.status == "UNSUPPORTED", name
        assert disposition.allows_solve is False, name
        assert "fiber_orientation" in disposition.required_data, name


def test_fibre_gate_does_not_fire_on_names_that_merely_contain_gf():
    """MgF2 and AGFA are not glass-fibre grades; a substring test would refuse them."""
    card = {"youngs_modulus": 3000.0, "poisson": 0.35}
    for name in ("MgF2", "AGFA_X100", "PGF_resin", "PA6", "PA12", "PA66", "POM"):
        disposition = classify_material_input({"name": name, **card}, analysis="linear_static")
        assert disposition.status == "LINEAR_ELASTIC", name


def test_catalog_grades_are_never_refused_by_the_fibre_gate():
    """No shipped standard material or alias may be mistaken for a fibre grade."""
    from abaqus_ai_agent.reasoning.material_catalog import STANDARD_MATERIALS, _is_glass_fibre_grade

    for profile in STANDARD_MATERIALS:
        for name in (profile.canonical_name, *profile.aliases):
            assert not _is_glass_fibre_grade(str(name)), f"{name} was read as a glass-fibre grade"


def test_isotropic_fibre_equivalent_needs_an_explicit_acceptance():
    """The gate opens only on a user-owned flag, and never without E and nu."""
    card = {"name": "PA6-GF50", "youngs_modulus": 16000.0, "poisson": 0.35}

    refused = classify_material_input(card, analysis="linear_static")
    assert refused.status == "UNSUPPORTED"

    incomplete = classify_material_input(
        {"name": "PA6-GF50", "accept_isotropic_fibre_equivalent": True},
        analysis="linear_static",
    )
    assert incomplete.status == "BLOCKED"
    assert incomplete.allows_solve is False

    accepted = classify_material_input(
        {**card, "accept_isotropic_fibre_equivalent": True}, analysis="linear_static"
    )
    assert accepted.status == "LINEAR_ELASTIC"
    assert accepted.metadata["isotropic_fibre_equivalent"] is True
    assert accepted.metadata["fibre_orientation_not_modelled"] is True
    assert "linear_elastic_below_yield" in accepted.allowed_claims


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


def _registered_grade(grade):
    from abaqus_ai_agent.materials.provider import MaterialProvider

    record = MaterialProvider.default().find_record(grade)
    assert record is not None, grade
    return record


def _fibre_record(grade, reinforcement_type, reinforcement_content=None):
    from abaqus_ai_agent.contracts.material_record import (
        MaterialCondition,
        MaterialIdentity,
        MaterialProperty,
        MaterialRecord,
        MaterialSource,
    )

    cond = MaterialCondition(temperature=23.0, temperature_unit="C")
    return MaterialRecord(
        identity=MaterialIdentity(
            polymer_family="PA66",
            manufacturer="Lab",
            grade=grade,
            reinforcement_type=reinforcement_type,
            reinforcement_content=reinforcement_content,
        ),
        source=MaterialSource(
            provider="Lab_Test",
            source_type="internal",
            locator=f"LAB://{grade}",
            retrieved_at="2026-10-10T00:00:00Z",
        ),
        properties=(
            MaterialProperty(name="youngs_modulus", value=8500.0, unit="MPa", quantity="stress", condition=cond),
            MaterialProperty(name="poissons_ratio", value=0.35, unit="ratio", quantity="dimensionless", condition=cond),
        ),
    )


def test_registered_fibre_grade_is_refused_through_its_identity():
    """The gate reads the record identity, not the grade spelling.

    Ultramid A3WG6 is PA66-GF30. Its name carries neither "GF30" nor "G30", so
    a name-only screen passed it as LINEAR_ELASTIC while the registry already
    held ``reinforcement_type='glass_fiber'``.
    """
    refused = classify_material_input(_registered_grade("Ultramid A3WG6"), analysis="linear_static")
    assert refused.status == "UNSUPPORTED"
    assert refused.allows_solve is False
    assert "fiber_orientation" in refused.required_data

    for grade in ("Makrolon 2800", "6061-T6", "Ti-6Al-4V"):
        allowed = classify_material_input(_registered_grade(grade), analysis="linear_static")
        assert allowed.status == "LINEAR_ELASTIC", grade


def test_grade_string_is_screened_through_the_same_registry_identity():
    """A plain string resolves to the same record, so it must reach the same verdict."""
    assert classify_material_input("Ultramid A3WG6", analysis="linear_static").status == "UNSUPPORTED"
    assert classify_material_input("6061-T6", analysis="linear_static").status == "LINEAR_ELASTIC"


def test_resolved_material_definition_keeps_the_fibre_refusal():
    """MaterialDefinition carries ``metadata['identity']``; the gate must read it."""
    from abaqus_ai_agent.reasoning.material_catalog import resolve_material_to_definition

    record = _registered_grade("Ultramid A3WG6")
    resolved = resolve_material_to_definition(record)
    assert resolved is not None and resolved.elastic is not None

    disposition = classify_material_input(resolved, analysis="linear_static")
    assert disposition.status == "UNSUPPORTED"
    assert disposition.allows_solve is False


def test_declared_reinforcement_type_outranks_the_grade_name():
    """One screen, structured first. Name tokens only stand in when nothing declared."""
    # A fibre grade whose name says nothing about fibres is still refused.
    unlabelled = _fibre_record("Delrin 100", "glass_fiber", 30.0)
    assert classify_material_input(unlabelled, analysis="linear_static").status == "UNSUPPORTED"

    # A declaration of no reinforcement outranks a name that looks like one, so
    # the string heuristic cannot become a second, competing decision.
    unfilled = _fibre_record("PA6-GF50", "unfilled", 0.0)
    assert classify_material_input(unfilled, analysis="linear_static").status == "LINEAR_ELASTIC"


def test_dict_identity_card_is_refused_like_the_record_it_serialises():
    card = _registered_grade("Ultramid A3WG6").to_dict()
    card = {
        **card,
        "identity": {**card["identity"], "reinforcement_type": "glass_fiber", "reinforcement_content": 30.0},
    }
    disposition = classify_material_input(card, analysis="linear_static")
    assert disposition.status == "UNSUPPORTED"


def test_isotropic_acceptance_still_opens_the_gate_for_a_registered_fibre_grade():
    """The explicit escape hatch keeps working on the identity path too."""
    card = {
        "name": "Ultramid A3WG6",
        "youngs_modulus": 8500.0,
        "poisson": 0.35,
        "accept_isotropic_fibre_equivalent": True,
    }
    disposition = classify_material_input(card, analysis="linear_static")
    assert disposition.status == "LINEAR_ELASTIC"
    assert disposition.metadata["isotropic_fibre_equivalent"] is True


def test_compiler_refuses_a_registered_fibre_grade_before_any_deck():
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        compile_engineering_intent(_intent("Ultramid A3WG6"))
