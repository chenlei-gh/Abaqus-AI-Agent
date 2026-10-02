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
    with pytest.raises(ValueError, match="invalid or unsupported unit_system"):
        MaterialDefinition(name="BadUnitMat", unit_system="NON_EXISTENT_UNIT_SYSTEM")

    # Action parameters preserve unit_system semantics
    assert actions[0].parameters.get("unit_system") == "MM_N_MPA"


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

    # Explicit step lossless max_inc mapping and Heat transfer steady_state
    step_explicit = AnalysisStep(
        name="ExpStep",
        procedure="explicit_dynamic",
        time_period=0.01,
        max_inc=1e-5,
    )
    act_exp = step_explicit.to_action("Model-1")
    assert act_exp.action_type == "dynamic_explicit_step"
    assert act_exp.parameters["max_increment"] == 1e-5

    step_heat = AnalysisStep(
        name="HeatStep",
        procedure="heat_transfer",
        time_period=10.0,
        steady_state=True,
        amplitude="RAMP",
        metadata={"author": "engineer"},
    )
    act_heat = step_heat.to_action("Model-1")
    assert act_heat.action_type == "heat_transfer_step"
    assert act_heat.parameters["response"] == "STEADY_STATE"
    assert act_heat.parameters["amplitude"] == "RAMP"
    assert act_heat.parameters["metadata"]["author"] == "engineer"

    step_coupled = AnalysisStep(
        name="CoupledStep",
        procedure="coupled_temp_displacement",
        time_period=5.0,
        steady_state=False,
    )
    act_coupled = step_coupled.to_action("Model-1")
    assert act_coupled.action_type == "coupled_temp_displacement_step"
    assert act_coupled.parameters["response"] == "TRANSIENT"


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


def test_action_builders_normalize_regions_and_preflight():
    from abaqus_ai_agent.actions.builders import fixed_bc, displacement_bc
    from abaqus_ai_agent.contracts.geometry import RegionReference
    from abaqus_ai_agent.validation.preflight import preflight_action, preflight_plan

    # Builder accepts RegionReference object
    reg_ref = RegionReference(expression="a.sets['FixSet']", kind="set", name="FixSet")
    act_bc = fixed_bc("Model-1", "BC-Fix", reg_ref)
    assert act_bc.parameters["region_expression"] == "a.sets['FixSet']"

    # Builder accepts dict region
    act_dict = displacement_bc("Model-1", "BC-Disp", {"set": "DispSet"}, u1=5.0)
    assert act_dict.parameters["region_expression"] == "a.sets['DispSet']"

    # Preflight validates action quantities and region
    res = preflight_action(act_bc)
    assert res.passed is True
    check_names = {c["name"] for c in res.checks}
    assert "region_valid" in check_names
    assert "action_quantities_valid" in check_names

    # Preflight structural conflict in plan: fixed + non-zero displacement on same region & step
    act_fixed = fixed_bc("Model-1", "BC-1", "a.sets['Root']", step="Step-1")
    act_disp = displacement_bc("Model-1", "BC-2", "a.sets['Root']", step="Step-1", u1=10.0)
    plan_res = preflight_plan([act_fixed, act_disp])
    assert plan_res.passed is False
    assert any(b["name"] == "bc_structural_conflict" for b in plan_res.blockers)
