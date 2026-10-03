"""Tests for Phase K: MaterialRecord, MaterialResolver, and external CAMPUS / TDS adapters."""

import pytest
from abaqus_ai_agent.contracts.material_record import (
    MaterialCondition,
    MaterialCurve,
    MaterialIdentity,
    MaterialProperty,
    MaterialRecord,
    MaterialSource,
)
from abaqus_ai_agent.contracts.material_resolver import MaterialResolver
from abaqus_ai_agent.adapters.materials.campus import CampusAdapter
from abaqus_ai_agent.adapters.materials.manufacturer import ManufacturerAdapter


def test_material_record_lifecycle_and_serialization():
    identity = MaterialIdentity(
        polymer_family="PA66",
        manufacturer="BASF",
        grade="Ultramid A3WG6",
        trade_name="Ultramid",
        reinforcement_type="glass_fiber",
        reinforcement_content=30.0,
        variant="heat_stabilized",
    )
    source = MaterialSource(
        provider="CAMPUS",
        source_type="iso_database",
        locator="CAMPUS://BASF/Ultramid_A3WG6",
        retrieved_at="2026-10-03T00:00:00Z",
        source_version="5.2",
    )
    cond_rt = MaterialCondition(temperature=23.0, humidity_state="dry", test_standard="ISO 527")
    prop_e = MaterialProperty(name="youngs_modulus", value=8500.0, unit="MPa", quantity="stress", condition=cond_rt)
    prop_sy = MaterialProperty(name="yield_stress", value=175.0, unit="MPa", quantity="stress", condition=cond_rt)
    prop_rho = MaterialProperty(name="density", value=1.36, unit="g/cm3", quantity="density", condition=cond_rt)

    curve_ss = MaterialCurve(
        curve_type="stress_strain",
        x_name="nominal_strain",
        x_unit="%",
        y_name="nominal_stress",
        y_unit="MPa",
        points=((0.0, 0.0), (1.0, 85.0), (2.0, 150.0), (3.0, 175.0), (4.0, 185.0)),
        condition=cond_rt,
    )

    record = MaterialRecord(
        identity=identity,
        source=source,
        properties=(prop_e, prop_sy, prop_rho),
        curves=(curve_ss,),
        default_condition=cond_rt,
        metadata={"commercial_status": "active"},
    )

    # Serialization roundtrip
    d = record.to_dict()
    reconstructed = MaterialRecord.from_dict(d)

    assert reconstructed.identity.grade == "Ultramid A3WG6"
    assert reconstructed.identity.reinforcement_content == 30.0
    assert reconstructed.source.provider == "CAMPUS"
    assert len(reconstructed.properties) == 3
    assert len(reconstructed.curves) == 1
    assert reconstructed.get_property("youngs_modulus").value == 8500.0


def test_campus_adapter_parsing():
    sample_campus_data = {
        "general_info": {
            "polymer_family": "PA66",
            "manufacturer": "BASF",
            "grade_name": "Ultramid A3WG6",
            "reinforcement_type": "glass_fiber",
            "reinforcement_content": 30.0,
        },
        "source_meta": {
            "locator": "https://www.campusplastics.com/campus/datasheet/Ultramid+A3WG6/BASF",
            "retrieved_at": "2026-10-03T12:00:00Z",
            "version": "CAMPUS 5.2",
        },
        "iso_10350_single_point": [
            {
                "name": "youngs_modulus",
                "value": 8500.0,
                "unit": "MPa",
                "test_standard": "ISO 527-1/-2",
                "condition": {"temperature": 23.0, "humidity_state": "dry"},
            },
            {
                "name": "yield_stress",
                "value": 175.0,
                "unit": "MPa",
                "test_standard": "ISO 527-1/-2",
                "condition": {"temperature": 23.0, "humidity_state": "dry"},
            },
            {
                "name": "density",
                "value": 1.36,
                "unit": "g/cm3",
                "test_standard": "ISO 1183",
                "condition": {"temperature": 23.0, "humidity_state": "dry"},
            },
        ],
        "iso_11403_multi_point": [
            {
                "curve_type": "stress_strain",
                "x_name": "nominal_strain",
                "x_unit": "%",
                "y_name": "nominal_stress",
                "y_unit": "MPa",
                "test_standard": "ISO 11403-1",
                "condition": {"temperature": 23.0, "humidity_state": "dry"},
                "points": [[0.0, 0.0], [1.0, 85.0], [2.0, 160.0], [3.0, 175.0]],
            }
        ],
    }

    record = CampusAdapter.parse_datasheet(sample_campus_data)
    assert record.identity.polymer_family == "PA66"
    assert record.source.provider == "CAMPUS"
    assert record.get_property("youngs_modulus").value == 8500.0
    assert len(record.curves) == 1
    assert len(record.curves[0].points) == 4


def test_manufacturer_tds_adapter_parsing():
    sample_tds = {
        "header": {
            "polymer_family": "POM",
            "manufacturer": "Celanese",
            "grade": "Hostaform C 9021",
            "trade_name": "Hostaform",
        },
        "document": {
            "locator": "TDS_Hostaform_C9021_2026.pdf",
            "retrieved_at": "2026-10-03T10:00:00Z",
            "disclaimer": "Informative properties only.",
        },
        "properties": [
            {
                "name": "youngs_modulus",
                "value": 2800.0,
                "unit": "MPa",
                "condition": {"temperature": 23.0, "humidity_state": "dry"},
            },
            {
                "name": "density",
                "value": 1.41,
                "unit": "g/cm3",
                "condition": {"temperature": 23.0, "humidity_state": "dry"},
            },
        ],
    }

    record = ManufacturerAdapter.parse_tds(sample_tds)
    assert record.identity.manufacturer == "Celanese"
    assert record.identity.grade == "Hostaform C 9021"
    assert record.get_property("youngs_modulus").value == 2800.0


def test_material_resolver_linear_elastic():
    record = CampusAdapter.parse_datasheet({
        "general_info": {"polymer_family": "PA66", "manufacturer": "BASF", "grade_name": "Ultramid A3WG6"},
        "source_meta": {"locator": "CAMPUS://BASF/A3WG6", "retrieved_at": "2026-10-03T00:00:00Z"},
        "iso_10350_single_point": [
            {"name": "youngs_modulus", "value": 8500.0, "unit": "MPa", "condition": {"temperature": 23.0, "humidity_state": "dry"}},
            {"name": "density", "value": 1.36, "unit": "g/cm3", "condition": {"temperature": 23.0, "humidity_state": "dry"}},
        ],
    })

    result = MaterialResolver.resolve(
        record=record,
        target_temperature=23.0,
        target_humidity="dry",
        constitutive_intent="linear_elastic",
        target_unit_system="MM_N_MPA",
    )

    assert result.is_executable
    mat_def = result.material_definition
    assert mat_def is not None
    assert mat_def.elastic.youngs_modulus == 8500.0
    assert abs(mat_def.density - 1.36e-9) < 1e-12  # 1.36 g/cm3 -> 1.36e-9 tonne/mm3
    assert "Provider=CAMPUS" in mat_def.provenance


def test_material_resolver_si_unit_conversion():
    record = CampusAdapter.parse_datasheet({
        "general_info": {"polymer_family": "PA66", "manufacturer": "BASF", "grade_name": "Ultramid A3WG6"},
        "source_meta": {"locator": "CAMPUS://BASF/A3WG6", "retrieved_at": "2026-10-03T00:00:00Z"},
        "iso_10350_single_point": [
            {"name": "youngs_modulus", "value": 8500.0, "unit": "MPa", "condition": {"temperature": 23.0, "humidity_state": "dry"}},
            {"name": "density", "value": 1.36, "unit": "g/cm3", "condition": {"temperature": 23.0, "humidity_state": "dry"}},
        ],
    })

    result = MaterialResolver.resolve(
        record=record,
        target_temperature=23.0,
        target_humidity="dry",
        constitutive_intent="linear_elastic",
        target_unit_system="SI",
    )

    assert result.is_executable
    mat_def = result.material_definition
    assert mat_def.elastic.youngs_modulus == 8.5e9  # 8500 MPa -> 8.5e9 Pa
    assert mat_def.density == 1360.0  # 1.36 g/cm3 -> 1360 kg/m3


def test_material_resolver_elastoplastic_calibration():
    record = CampusAdapter.parse_datasheet({
        "general_info": {"polymer_family": "PA66", "manufacturer": "BASF", "grade_name": "Ultramid A3WG6"},
        "source_meta": {"locator": "CAMPUS://BASF/A3WG6", "retrieved_at": "2026-10-03T00:00:00Z"},
        "iso_10350_single_point": [
            {"name": "youngs_modulus", "value": 8500.0, "unit": "MPa", "condition": {"temperature": 23.0, "humidity_state": "dry"}},
            {"name": "yield_stress", "value": 175.0, "unit": "MPa", "condition": {"temperature": 23.0, "humidity_state": "dry"}},
        ],
        "iso_11403_multi_point": [
            {
                "curve_type": "stress_strain",
                "x_name": "nominal_strain",
                "x_unit": "%",
                "y_name": "nominal_stress",
                "y_unit": "MPa",
                "condition": {"temperature": 23.0, "humidity_state": "dry"},
                "points": [[0.0, 0.0], [1.0, 85.0], [2.0, 160.0], [2.5, 175.0], [3.0, 185.0]],
            }
        ],
    })

    result = MaterialResolver.resolve(
        record=record,
        target_temperature=23.0,
        constitutive_intent="elastoplastic",
    )

    assert result.is_executable
    mat_def = result.material_definition
    assert mat_def.plastic is not None
    assert mat_def.plastic.yield_stress == 175.0
    assert len(mat_def.plastic.hardening_table) >= 1


def test_material_resolver_condition_incompatibility_fail_closed():
    record = CampusAdapter.parse_datasheet({
        "general_info": {"polymer_family": "PA66", "manufacturer": "BASF", "grade_name": "Ultramid A3WG6"},
        "source_meta": {"locator": "CAMPUS://BASF/A3WG6", "retrieved_at": "2026-10-03T00:00:00Z"},
        "iso_10350_single_point": [
            {"name": "youngs_modulus", "value": 8500.0, "unit": "MPa", "condition": {"temperature": 23.0, "humidity_state": "dry"}},
        ],
    })

    # Extreme temperature discrepancy (150 C vs 23 C data)
    result = MaterialResolver.resolve(
        record=record,
        target_temperature=150.0,
        allow_assisted_assumptions=False,
    )

    assert result.status == "BLOCKED"
    assert result.material_definition is None
    assert "Fail-closed on uncharacterized thermal degradation" in result.diagnostics[0]


def test_material_resolver_unsupported_creep_fails_closed():
    record = CampusAdapter.parse_datasheet({
        "general_info": {"polymer_family": "PA66", "manufacturer": "BASF", "grade_name": "Ultramid A3WG6"},
        "source_meta": {"locator": "CAMPUS://BASF/A3WG6", "retrieved_at": "2026-10-03T00:00:00Z"},
        "iso_10350_single_point": [
            {"name": "youngs_modulus", "value": 8500.0, "unit": "MPa", "condition": {"temperature": 23.0, "humidity_state": "dry"}},
        ],
    })

    result = MaterialResolver.resolve(
        record=record,
        constitutive_intent="creep",
    )

    assert result.status == "UNSUPPORTED"
    assert "requires experimental creep/relaxation curves" in result.diagnostics[0]


def test_material_record_strict_unmatched_condition_fails_closed():
    """Verify that get_property strictly returns None when condition does not match, avoiding silent room-temp fallback."""
    from abaqus_ai_agent.contracts.material_record import MaterialCondition
    record = CampusAdapter.parse_datasheet({
        "general_info": {"polymer_family": "PA66", "manufacturer": "BASF", "grade_name": "Ultramid A3WG6"},
        "source_meta": {"locator": "CAMPUS://BASF/A3WG6", "retrieved_at": "2026-10-03T00:00:00Z"},
        "iso_10350_single_point": [
            {"name": "youngs_modulus", "value": 8500.0, "unit": "MPa", "condition": {"temperature": 23.0, "humidity_state": "dry"}},
        ],
    })

    # Exact room temp match succeeds
    matched = record.get_property("youngs_modulus", MaterialCondition(temperature=23.0, humidity_state="dry"))
    assert matched is not None
    assert matched.value == 8500.0

    # Mismatched condition returns None (fail-closed), never silently returns candidates[0]!
    unmatched_temp = record.get_property("youngs_modulus", MaterialCondition(temperature=80.0, humidity_state="dry"))
    assert unmatched_temp is None

    unmatched_humid = record.get_property("youngs_modulus", MaterialCondition(temperature=23.0, humidity_state="conditioned"))
    assert unmatched_humid is None
