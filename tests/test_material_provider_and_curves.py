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


def test_material_resolver_blocks_unphysical_elastic_properties():
    cond = MaterialCondition(temperature=23.0)
    source = MaterialSource(
        provider="TDS",
        source_type="datasheet_pdf",
        locator="test://unphysical",
        retrieved_at="2026-10-10T00:00:00Z",
    )
    # 1. Non-positive Young's modulus
    rec_bad_e = MaterialRecord(
        identity=MaterialIdentity(polymer_family="Steel", manufacturer="Generic", grade="Zero-E"),
        source=source,
        properties=(MaterialProperty(name="youngs_modulus", value=-1000.0, unit="MPa", quantity="stress", condition=cond),),
    )
    res_e = MaterialResolver.resolve(rec_bad_e)
    assert res_e.status == "BLOCKED"
    assert any("Invalid Young's modulus" in d for d in res_e.diagnostics)

    # 2. Thermodynamically impossible Poisson's ratio (nu >= 0.5)
    rec_bad_nu = MaterialRecord(
        identity=MaterialIdentity(polymer_family="Steel", manufacturer="Generic", grade="Bad-Nu"),
        source=source,
        properties=(
            MaterialProperty(name="youngs_modulus", value=200000.0, unit="MPa", quantity="stress", condition=cond),
            MaterialProperty(name="poissons_ratio", value=0.55, unit="", quantity="dimensionless", condition=cond),
        ),
    )
    res_nu = MaterialResolver.resolve(rec_bad_nu)
    assert res_nu.status == "BLOCKED"
    assert any("Thermodynamically invalid Poisson's ratio" in d for d in res_nu.diagnostics)

    # 3. Non-positive density
    rec_bad_rho = MaterialRecord(
        identity=MaterialIdentity(polymer_family="Steel", manufacturer="Generic", grade="Bad-Rho"),
        source=source,
        properties=(
            MaterialProperty(name="youngs_modulus", value=200000.0, unit="MPa", quantity="stress", condition=cond),
            MaterialProperty(name="poissons_ratio", value=0.3, unit="", quantity="dimensionless", condition=cond),
            MaterialProperty(name="density", value=-7.8, unit="g/cm3", quantity="density", condition=cond),
        ),
    )
    res_rho = MaterialResolver.resolve(rec_bad_rho)
    assert res_rho.status == "BLOCKED"
    assert any("Invalid density" in d for d in res_rho.diagnostics)


def test_material_resolver_interpolates_rp02_and_clamps_softening():
    cond = MaterialCondition(temperature=23.0)
    source = MaterialSource(
        provider="TDS",
        source_type="datasheet_pdf",
        locator="test://rp02-test",
        retrieved_at="2026-10-10T00:00:00Z",
    )
    # Stress-strain curve with explicit post-yield softening:
    # E = 10000 MPa
    # Point 1: eps=0.001 (0.1%), sig=10.0 MPa -> eps_p = 0.001 - 10/10000 = 0.0
    # Point 2: eps=0.0035 (0.35%), sig=25.0 MPa -> eps_p = 0.0035 - 25/10000 = 0.001
    # Point 3: eps=0.006 (0.6%), sig=30.0 MPa -> eps_p = 0.006 - 30/10000 = 0.003
    # 0.002 is halfway between Point 2 (eps_p=0.001, sig=25) and Point 3 (eps_p=0.003, sig=30)
    # Expected Rp0.2 interpolated = 25 + 0.5 * (30 - 25) = 27.5 MPa
    # Point 4: eps=0.010, sig=22.0 MPa -> softening!
    rec = MaterialRecord(
        identity=MaterialIdentity(polymer_family="Polymer", manufacturer="Test", grade="Softening-Grade"),
        source=source,
        properties=(MaterialProperty(name="youngs_modulus", value=10000.0, unit="MPa", quantity="stress", condition=cond),),
        curves=(
            MaterialCurve(
                curve_type="stress_strain",
                x_name="strain",
                x_unit="%",
                y_name="stress",
                y_unit="MPa",
                condition=cond,
                points=(
                    (0.0, 0.0),
                    (0.1, 10.0),
                    (0.35, 25.0),
                    (0.6, 35.0),
                    (1.0, 32.0),  # Softening from 35.0 to 32.0 (both above yield)
                ),
            ),
        ),
    )
    res = MaterialResolver.resolve(rec, constitutive_intent="elastoplastic")
    assert res.is_executable
    mat = res.material_definition
    assert mat is not None
    assert mat.plastic is not None
    # Check linear interpolation of Rp0.2 (interpolated between 25.0875 and 35.21 at eps_p=0.002)
    assert mat.plastic.yield_stress == pytest.approx(32.05, abs=0.2)
    # First point of hardening table must be (sy, 0.0)
    assert mat.plastic.hardening_table[0][1] == 0.0
    # Softening point must be clamped to prevent negative slope
    stresses_in_table = [pt[0] for pt in mat.plastic.hardening_table]
    for i in range(len(stresses_in_table) - 1):
        assert stresses_in_table[i + 1] >= stresses_in_table[i]  # Monotonically non-decreasing
    assert any("softening" in a.lower() for a in res.assumptions)


def test_material_resolver_rejects_unknown_stress_and_density_units():
    cond = MaterialCondition(temperature=23.0)
    source = MaterialSource(
        provider="TDS",
        source_type="datasheet_pdf",
        locator="test://bad-units",
        retrieved_at="2026-10-10T00:00:00Z",
    )
    # 1. Unknown stress unit
    rec_bad_stress = MaterialRecord(
        identity=MaterialIdentity(polymer_family="Steel", manufacturer="Generic", grade="Bad-Unit"),
        source=source,
        properties=(
            MaterialProperty(name="youngs_modulus", value=200000.0, unit="furlong_per_sec", quantity="stress", condition=cond),
        ),
    )
    res_s = MaterialResolver.resolve(rec_bad_stress)
    assert res_s.status == "BLOCKED"
    assert any("Unrecognized or unsupported stress unit" in d for d in res_s.diagnostics)

    # 2. Unknown density unit
    rec_bad_dens = MaterialRecord(
        identity=MaterialIdentity(polymer_family="Steel", manufacturer="Generic", grade="Bad-Dens"),
        source=source,
        properties=(
            MaterialProperty(name="youngs_modulus", value=200000.0, unit="MPa", quantity="stress", condition=cond),
            MaterialProperty(name="density", value=7.8, unit="bushels", quantity="density", condition=cond),
        ),
    )
    res_d = MaterialResolver.resolve(rec_bad_dens)
    assert res_d.status == "BLOCKED"
    assert any("Unrecognized or unsupported density unit" in d for d in res_d.diagnostics)


def test_material_resolver_avoids_duplicate_conversion_for_true_strain_curves():
    cond = MaterialCondition(temperature=23.0)
    source = MaterialSource(
        provider="TDS",
        source_type="datasheet_pdf",
        locator="test://true-strain",
        retrieved_at="2026-10-10T00:00:00Z",
    )
    rec_true = MaterialRecord(
        identity=MaterialIdentity(polymer_family="Steel", manufacturer="Generic", grade="True-Curve"),
        source=source,
        properties=(
            MaterialProperty(name="youngs_modulus", value=200000.0, unit="MPa", quantity="stress", condition=cond),
            MaterialProperty(name="poissons_ratio", value=0.3, unit="", quantity="dimensionless", condition=cond),
        ),
        curves=(
            MaterialCurve(
                curve_type="stress_strain",
                x_name="true_plastic_strain",
                x_unit="1",
                y_name="true_stress",
                y_unit="MPa",
                condition=cond,
                points=(
                    (0.002, 350.0),
                    (0.010, 420.0),
                    (0.050, 500.0),
                ),
            ),
        ),
    )
    res = MaterialResolver.resolve(rec_true, constitutive_intent="elastoplastic")
    assert res.is_executable
    mat = res.material_definition
    assert mat is not None
    assert mat.plastic is not None
    assert any("avoided duplicate logarithmic/engineering conversion" in a for a in res.assumptions)


def test_material_resolver_polymer_family_aware_poisson_ratio():
    cond = MaterialCondition(temperature=23.0)
    source = MaterialSource(
        provider="TDS",
        source_type="datasheet_pdf",
        locator="test://nu-derivation",
        retrieved_at="2026-10-10T00:00:00Z",
    )
    # 1. Steel without nu in datasheet -> 0.30
    rec_steel = MaterialRecord(
        identity=MaterialIdentity(polymer_family="Steel", manufacturer="Generic", grade="S355"),
        source=source,
        properties=(
            MaterialProperty(name="youngs_modulus", value=210000.0, unit="MPa", quantity="stress", condition=cond),
        ),
    )
    res_st = MaterialResolver.resolve(rec_steel)
    assert res_st.is_executable
    assert res_st.material_definition.elastic.poisson_ratio == 0.30
    assert any("assumed standard metal alloy value nu=0.3" in a for a in res_st.assumptions)

    # 2. Aluminum without nu in datasheet -> 0.33
    rec_al = MaterialRecord(
        identity=MaterialIdentity(polymer_family="Aluminum", manufacturer="Generic", grade="6061"),
        source=source,
        properties=(
            MaterialProperty(name="youngs_modulus", value=70000.0, unit="MPa", quantity="stress", condition=cond),
        ),
    )
    res_al = MaterialResolver.resolve(rec_al)
    assert res_al.is_executable
    assert res_al.material_definition.elastic.poisson_ratio == 0.33

    # 3. Unknown material without nu and allow_assisted_assumptions=False -> BLOCKED
    rec_unknown = MaterialRecord(
        identity=MaterialIdentity(polymer_family="ExoticCompositeMetaMaterial", manufacturer="Generic", grade="X1"),
        source=source,
        properties=(
            MaterialProperty(name="youngs_modulus", value=50000.0, unit="MPa", quantity="stress", condition=cond),
        ),
    )
    res_unk = MaterialResolver.resolve(rec_unknown, allow_assisted_assumptions=False)
    assert res_unk.status == "BLOCKED"
    assert any("unassisted assumption is strictly prohibited" in d for d in res_unk.diagnostics)


def test_material_condition_normalizes_kelvin_temperature():
    cond_c = MaterialCondition(temperature=20.0, temperature_unit="C")
    cond_k = MaterialCondition(temperature=293.15, temperature_unit="K")
    assert cond_c.matches(cond_k) is True
    assert cond_k.matches(cond_c) is True

    # 100 C vs 293.15 K (20 C) -> should NOT match
    cond_hot_c = MaterialCondition(temperature=100.0, temperature_unit="C")
    assert cond_hot_c.matches(cond_k) is False


def test_material_resolver_blocks_unphysical_thermal_properties():
    cond = MaterialCondition(temperature=23.0)
    source = MaterialSource(
        provider="TDS",
        source_type="datasheet_pdf",
        locator="test://bad-thermal",
        retrieved_at="2026-10-10T00:00:00Z",
    )
    # Non-positive thermal conductivity
    rec_bad_tc = MaterialRecord(
        identity=MaterialIdentity(polymer_family="Steel", manufacturer="Generic", grade="Bad-TC"),
        source=source,
        properties=(
            MaterialProperty(name="youngs_modulus", value=200000.0, unit="MPa", quantity="stress", condition=cond),
            MaterialProperty(name="thermal_conductivity", value=-15.0, unit="W/m-K", quantity="thermal_conductivity", condition=cond),
        ),
    )
    res_tc = MaterialResolver.resolve(rec_bad_tc)
    assert res_tc.status == "BLOCKED"
    assert any("Invalid thermal conductivity" in d for d in res_tc.diagnostics)
