import pytest
from abaqus_ai_agent.contracts.material import (
    MaterialDefinition,
    ElasticProperties,
    PlasticProperties,
    ThermalProperties,
)
from abaqus_ai_agent.contracts.step import AnalysisStep
from abaqus_ai_agent.contracts.units import validate_action_quantities


def test_material_definition_semantics_and_actions():
    mat = MaterialDefinition(
        name="StructuralSteel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
        plastic=PlasticProperties(yield_stress=355.0, plastic_strain=0.0),
        provenance="EN 10025-2",
        assumptions=("isotropic", "rate_independent"),
    )
    assert mat.name == "StructuralSteel"
    assert mat.elastic.youngs_modulus == 210000.0
    assert mat.density == 7.85e-9

    d = mat.to_dict()
    assert d["name"] == "StructuralSteel"
    assert d["elastic"]["youngs_modulus"] == 210000.0
    assert d["plastic"]["yield_stress"] == 355.0

    # Materialize into low-level Abaqus actions
    actions = mat.to_actions("Model-1")
    assert len(actions) == 3
    types = [a.action_type for a in actions]
    assert "material_elastic" in types
    assert "material_density" in types
    assert "material_plastic" in types

    # Negative validation
    with pytest.raises(ValueError, match="Young's modulus must be positive"):
        ElasticProperties(youngs_modulus=-1000.0, poisson_ratio=0.3)
    with pytest.raises(ValueError, match="Poisson's ratio"):
        ElasticProperties(youngs_modulus=200000.0, poisson_ratio=0.6)


def test_analysis_step_semantics_and_actions():
    step_static = AnalysisStep(
        name="LoadStep",
        procedure="static",
        time_period=2.0,
        nlgeom=True,
        max_num_inc=200,
        initial_inc=0.1,
    )
    act_static = step_static.to_action("Model-1")
    assert act_static.action_type == "static_step"
    assert act_static.parameters["name"] == "LoadStep"
    assert act_static.parameters["nlgeom"] is True
    assert act_static.parameters["time_period"] == 2.0

    step_dynamic = AnalysisStep(
        name="ImplicitStep",
        procedure="implicit_dynamic",
        time_period=0.5,
        application="MODERATE_DISSIPATION",
        nohaf=True,
    )
    act_dynamic = step_dynamic.to_action("Model-1")
    assert act_dynamic.action_type == "implicit_dynamic_step"
    assert act_dynamic.parameters["application"] == "MODERATE_DISSIPATION"
    assert act_dynamic.parameters["nohaf"] is True

    # Unknown procedure
    with pytest.raises(ValueError, match="unsupported step procedure"):
        AnalysisStep(name="Bad", procedure="unsupported_procedure")


def test_validate_action_quantities():
    # Valid elastic
    assert validate_action_quantities("material_elastic", {"youngs_modulus": 200000.0}) is True

    # Invalid negative Young's modulus
    with pytest.raises(ValueError, match="Young's modulus must be positive"):
        validate_action_quantities("material_elastic", {"youngs_modulus": -50.0})

    # Valid step
    assert validate_action_quantities("static_step", {"time_period": 1.0}) is True

    # Invalid negative time period
    with pytest.raises(ValueError, match="time_period must be positive"):
        validate_action_quantities("static_step", {"time_period": 0.0})
