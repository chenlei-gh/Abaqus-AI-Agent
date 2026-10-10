"""Tests for MaterialProvider, authentic datasheet resolution, and true stress-strain calibration."""

import json
import pytest

from abaqus_ai_agent.contracts.material import MaterialDefinition
from abaqus_ai_agent.contracts.material_record import (
    MaterialCondition,
    MaterialCurve,
    MaterialIdentity,
    MaterialProperty,
    MaterialRecord,
    MaterialSource,
)
from abaqus_ai_agent.contracts.material_resolver import MaterialResolver
from abaqus_ai_agent.materials.provider import MaterialNotFoundError, MaterialProvider
from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, compile_intent_to_actions
from abaqus_ai_agent.reasoning.material_catalog import resolve_material_to_definition


def test_material_provider_builtin_records():
    provider = MaterialProvider.default()

    # Search by standard grade
    rec_pa = provider.find_record("Ultramid A3WG6")
    assert rec_pa is not None
    assert rec_pa.identity.polymer_family == "PA66"
    assert rec_pa.identity.manufacturer == "BASF"

    # Search by alias
    rec_alias = provider.find_record("pa66_gf30")
    assert rec_alias is not None
    assert rec_alias.identity.grade == "Ultramid A3WG6"

    # Search metals
    rec_al = provider.find_record("al6061_t6_real")
    assert rec_al is not None
    assert rec_al.identity.grade == "6061-T6"

    rec_ti = provider.find_record("TC4")
    # Both standard catalog or provider can resolve TC4
    mat_def = resolve_material_to_definition("TC4", fail_closed=True)
    assert mat_def is not None


def test_material_provider_resolve_with_true_stress_strain():
    provider = MaterialProvider.default()
    rec_pa = provider.find_record("Ultramid A3WG6")
    assert rec_pa is not None

    res = provider.resolve(
        query_or_record=rec_pa,
        constitutive_intent="elastoplastic",
        target_unit_system="MM_N_MPA",
    )
    assert res.is_executable
    mat_def = res.material_definition
    assert mat_def is not None
    assert mat_def.plastic is not None
    assert mat_def.plastic.yield_stress == pytest.approx(175.0, rel=1e-2)

    # Abaqus requirement: hardening table must begin with (yield_stress, 0.0)
    table = mat_def.plastic.hardening_table
    assert len(table) >= 2
    assert table[0][0] == pytest.approx(175.0, rel=1e-2)
    assert table[0][1] == 0.0

    # Ensure plastic strains are strictly monotonically increasing
    for i in range(len(table) - 1):
        assert table[i + 1][1] > table[i][1]


def test_material_resolver_deduces_yield_stress_from_curve():
    """When single-point yield_stress is omitted, deduce from offset/inelasticity."""
    cond_rt = MaterialCondition(temperature=23.0, humidity_state="dry")
    record = MaterialRecord(
        identity=MaterialIdentity(
            polymer_family="POM",
            manufacturer="Generic",
            grade="POM-C",
        ),
        source=MaterialSource(
            provider="TDS",
            source_type="technical_datasheet",
            locator="TDS://Generic/POM-C",
            retrieved_at="2026-10-10T00:00:00Z",
        ),
        properties=(
            MaterialProperty(name="youngs_modulus", value=3000.0, unit="MPa", quantity="stress", condition=cond_rt),
            MaterialProperty(name="density", value=1.41, unit="g/cm3", quantity="density", condition=cond_rt),
        ),
        curves=(
            MaterialCurve(
                curve_type="stress_strain",
                x_name="nominal_strain",
                x_unit="%",
                y_name="nominal_stress",
                y_unit="MPa",
                points=(
                    (0.0, 0.0),
                    (0.5, 15.0),
                    (1.0, 30.0),
                    (1.5, 43.0),
                    (2.0, 52.0),
                    (2.5, 58.0),
                    (3.0, 62.0),
                ),
                condition=cond_rt,
            ),
        ),
        default_condition=cond_rt,
    )

    res = MaterialResolver.resolve(
        record=record,
        constitutive_intent="elastoplastic",
    )
    assert res.is_executable
    mat_def = res.material_definition
    assert mat_def is not None
    assert mat_def.plastic is not None
    assert mat_def.plastic.yield_stress > 30.0  # Deduced around inelastic transition
    assert len(mat_def.plastic.hardening_table) >= 1
    assert mat_def.plastic.hardening_table[0][1] == 0.0


def test_material_provider_fail_closed_on_unrecognized():
    provider = MaterialProvider.default()
    with pytest.raises(MaterialNotFoundError, match="not found in registered"):
        provider.resolve("Completely_Unknown_Fictional_Polymer_999", fail_closed=True)


def test_compiler_consumes_material_record_hardening():
    provider = MaterialProvider.default()
    rec_al = provider.find_record("al6061_t6_real")
    assert rec_al is not None

    res = provider.resolve(rec_al, constitutive_intent="elastoplastic")
    mat_def = res.material_definition
    assert mat_def is not None

    plan = compile_intent_to_actions(
        model_name="Model_Material_Test",
        part_name="Part_Test",
        job_name="Job_Material_Test",
        geometry=IntentGeometrySpec(shape="plate", length=100.0, width=50.0, height=5.0),
        material=mat_def,
    )

    action_types = [a.action_type for a in plan.actions]
    assert "material_elastic" in action_types
    assert "material_plastic" in action_types

    plastic_action = next(a for a in plan.actions if a.action_type == "material_plastic")
    table = plastic_action.parameters["table"]
    assert len(table) >= 2
    assert table[0][1] == 0.0
    assert "mat.Plastic(table=" in plan.cae_script
