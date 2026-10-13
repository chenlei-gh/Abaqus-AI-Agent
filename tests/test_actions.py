import pytest

from abaqus_ai_agent.actions import (
    fixed_bc, pressure_load, material_elastic, python_action, static_step,
    dynamic_explicit_step, implicit_dynamic_step, heat_transfer_step, coupled_temp_displacement_step,
    tabular_amplitude, smooth_step_amplitude, periodic_amplitude, equally_spaced_amplitude,
    initial_temperature, initial_stress, gravity,
    assembly_inspect, instance_translate, instance_rotate, instance_linear_pattern,
    export_inp, export_odb_csv, tie, contact, contact_property,
)
from abaqus_ai_agent.actions.runner import preview


def test_fixed_bc_script():
    action = fixed_bc("Model-1", "Fix", "a.Set(name='FIX')", step="Initial")
    code = preview(action)
    assert "EncastreBC" in code
    assert "FIX" in code


def test_pressure_script():
    action = pressure_load("Model-1", "P", "a.Surface(name='LOAD')", 100.0)
    assert "Pressure" in preview(action)
    assert "100.0" in preview(action)


def test_raw_python_is_unbounded_escape_hatch():
    action = python_action("Model-1", "print(list(mdb.models.keys()))")
    assert preview(action) == "print(list(mdb.models.keys()))"


def test_material_and_step_builders():
    assert "Elastic" in preview(material_elastic("M", "Steel", 210000.0, 0.3))
    assert "StaticStep" in preview(static_step("M"))


def test_amplitude_scripts():
    assert "TabularAmplitude" in preview(tabular_amplitude("M", "A", ((0.0, 0.0), (1.0, 1.0))))
    assert "SmoothStepAmplitude" in preview(smooth_step_amplitude("M", "A", ((0.0, 0.0), (1.0, 1.0))))
    assert "PeriodicAmplitude" in preview(periodic_amplitude("M", "A", 2.0, 0.0, 0.0, ((1.0, 0.5),)))
    assert "EquallySpacedAmplitude" in preview(equally_spaced_amplitude("M", "A", 0.1, (0.0, 1.0)))


def test_predefined_field_and_gravity_scripts():
    assert "Temperature(" in preview(initial_temperature("M", "T0", "a.Set(name='ALL')", 80.0))
    assert "createStepName='Initial'" in preview(initial_temperature("M", "T0", "a.Set(name='ALL')", 80.0))
    assert "Stress(" in preview(initial_stress("M", "S0", "a.Set(name='ALL')", sigma11=10.0))
    assert "Gravity(" in preview(gravity("M", "G", comp3=-9.81))


def test_implicit_dynamic_and_step_controls():
    code = preview(implicit_dynamic_step("M", time_period=2.0, max_num_inc=200, initial_inc=0.01))
    assert "ImplicitDynamicsStep" in code
    assert "maxNumInc=200" in code
    assert "initialInc=0.01" in code
    assert "stabilizationMethod" in preview(static_step("M", stabilization_method="DISSIPATED_ENERGY_FRACTION"))
    assert "amplitude=RAMP" in preview(static_step("M"))
    assert "amplitude=STEP" in preview(implicit_dynamic_step("M"))
    assert "amplitude=STEP" in preview(heat_transfer_step("M"))
    assert "amplitude=STEP" in preview(coupled_temp_displacement_step("M"))
    with pytest.raises(ValueError):
        preview(static_step("M", amplitude="LOAD_AMP"))


def test_assembly_and_export_scripts():
    assert "assembly" in preview(assembly_inspect("M")).lower()
    assert ".translate" in preview(instance_translate("M", "PART-1-1", (1, 2, 3)))
    assert ".rotateAboutAxis" in preview(instance_rotate("M", "PART-1-1", (0,0,0), (0,0,1), 90.0))
    assert "LinearInstancePattern" in preview(instance_linear_pattern("M", ("PART-1-1",), 2, 10.0))
    assert "writeInput" in preview(export_inp("M", "Job-1"))
    assert "openOdb" in preview(export_odb_csv("M", "Job-1.odb", "results.csv", variable="S"))


def test_tie_and_contact_scripts():
    tie_code = preview(tie("M", "Tie-1", "a.surfaces['M']", "a.surfaces['S']"))
    assert "Tie(" in tie_code
    assert "Tie-1" in tie_code
    assert "a.surfaces['M']" in tie_code
    assert "a.surfaces['S']" in tie_code

    prop_code = preview(contact_property("M", "FrictionProp", tangential_behavior={"formulation": "PENALTY", "friction": 0.2}))
    assert "ContactProperty" in prop_code
    assert "TangentialBehavior" in prop_code

    contact_code = preview(contact("M", "Cont-1", "a.surfaces['M']", "a.surfaces['S']", property="FrictionProp"))
    assert "SurfaceToSurfaceContactStd(" in contact_code
    assert "Cont-1" in contact_code
    assert "FrictionProp" in contact_code


def test_validate_action_rejects_bool_nan_inf():
    """Verify that validate_action strictly rejects bool-as-number, NaN, and Inf in quantity fields."""
    import math
    from abaqus_ai_agent.contracts.action import AbaqusAction
    from abaqus_ai_agent.validation.actions import validate_action

    # 1. local_seed_size with bool or NaN or Inf
    for invalid_size in (True, False, float("nan"), float("inf"), -1.0, 0.0):
        action = AbaqusAction(
            action_type="local_seed_size",
            model_name="Model-1",
            target="Part-1",
            parameters={"part": "Part-1", "region_expression": "e[0]", "size": invalid_size},
        )
        with pytest.raises(ValueError, match="size must be positive"):
            validate_action(action)

    # 2. temperature_bc magnitude with bool or NaN
    for invalid_mag in (True, False, float("nan"), float("inf")):
        action = AbaqusAction(
            action_type="temperature_bc",
            model_name="Model-1",
            target="Model-1",
            parameters={"name": "T1", "region_expression": "n[0]", "magnitude": invalid_mag},
        )
        with pytest.raises(ValueError, match="magnitude"):
            validate_action(action)

    # 3. inspect_geometry with bool or NaN
    for invalid_val in (True, float("nan"), float("-inf")):
        action = AbaqusAction(
            action_type="inspect_geometry",
            model_name="Model-1",
            target="Part-1",
            parameters={"part": "Part-1", "min_edge_length": invalid_val},
        )
        with pytest.raises(ValueError, match="min_edge_length must be positive"):
            validate_action(action)


def test_validate_action_spatial_and_amplitude_numeric_hardening():
    """Verify that validate_action strictly rejects bool, NaN, Inf, and zero rotation vectors."""
    from abaqus_ai_agent.contracts.action import AbaqusAction
    from abaqus_ai_agent.validation.actions import validate_action

    # 1. instance_translate rejects non-finite / bool in vector
    for bad_vec in ([1.0, 2.0, float("nan")], [float("inf"), 0.0, 0.0], [True, 0.0, 0.0], [1.0, "str", 3.0]):
        action = AbaqusAction(
            action_type="instance_translate",
            model_name="Model-1",
            target="Assembly",
            parameters={"instance": "Part-1-1", "vector": bad_vec},
        )
        with pytest.raises(ValueError, match="vector component must be a finite number"):
            validate_action(action)

    # 2. instance_rotate rejects non-finite / bool in axis_point and axis_direction
    for bad_pt in ([1.0, float("nan"), 0.0], [True, 0.0, 0.0]):
        action = AbaqusAction(
            action_type="instance_rotate",
            model_name="Model-1",
            target="Assembly",
            parameters={"instance": "Part-1-1", "axis_point": bad_pt, "axis_direction": [0.0, 0.0, 1.0]},
        )
        with pytest.raises(ValueError, match="axis_point component must be a finite number"):
            validate_action(action)

    for bad_dir in ([0.0, 0.0, float("inf")], [0.0, False, 1.0]):
        action = AbaqusAction(
            action_type="instance_rotate",
            model_name="Model-1",
            target="Assembly",
            parameters={"instance": "Part-1-1", "axis_point": [0.0, 0.0, 0.0], "axis_direction": bad_dir},
        )
        with pytest.raises(ValueError, match="axis_direction component must be a finite number"):
            validate_action(action)

    # 3. instance_rotate rejects zero-vector for axis_direction
    action = AbaqusAction(
        action_type="instance_rotate",
        model_name="Model-1",
        target="Assembly",
        parameters={"instance": "Part-1-1", "axis_point": [0.0, 0.0, 0.0], "axis_direction": [0.0, 0.0, 0.0]},
    )
    with pytest.raises(ValueError, match="axis_direction cannot be a zero vector"):
        validate_action(action)

    # 4. reference_point rejects non-finite / bool in coordinates
    for bad_coord in ([float("nan"), 0.0, 0.0], [0.0, True, 0.0], [0.0, 0.0, float("-inf")]):
        action = AbaqusAction(
            action_type="reference_point",
            model_name="Model-1",
            target="Assembly",
            parameters={"name": "RP-1", "coordinates": bad_coord},
        )
        with pytest.raises(ValueError, match="coordinates component must be a finite number"):
            validate_action(action)

    # 5. amplitudes reject non-finite / bool in data pairs
    for bad_pair in (((0.0, 0.0), (1.0, float("nan"))), ((0.0, True), (1.0, 1.0))):
        action = AbaqusAction(
            action_type="tabular_amplitude",
            model_name="Model-1",
            target="Model-1",
            parameters={"name": "Amp1", "data": bad_pair},
        )
        with pytest.raises(ValueError, match="amplitude data component must be a finite number"):
            validate_action(action)

    action_eq = AbaqusAction(
        action_type="equally_spaced_amplitude",
        model_name="Model-1",
        target="Model-1",
        parameters={"name": "AmpEq", "fixed_interval": 0.1, "data": [0.0, float("inf")]},
    )
    with pytest.raises(ValueError, match="amplitude data component must be a finite number"):
        validate_action(action_eq)


def test_validate_action_quantities_rejects_bool_nan_inf():
    """Verify that validate_action_quantities in units.py rejects bool, NaN, Inf, and non-positive values."""
    from abaqus_ai_agent.contracts.units import validate_action_quantities

    # 1. material_elastic: youngs_modulus
    for bad_ym in (True, False, float("nan"), float("inf"), float("-inf"), 0.0, -100.0):
        with pytest.raises(ValueError, match="Young's modulus must be positive"):
            validate_action_quantities("material_elastic", {"youngs_modulus": bad_ym})

    # Valid youngs_modulus passes
    assert validate_action_quantities("material_elastic", {"youngs_modulus": 210000.0}) is True

    # 2. material_density: density
    for bad_rho in (True, False, float("nan"), float("inf"), 0.0, -7.85e-9):
        with pytest.raises(ValueError, match="density must be positive"):
            validate_action_quantities("material_density", {"density": bad_rho})

    assert validate_action_quantities("material_density", {"density": 7.85e-9}) is True

    # 3. static_step: time_period
    for bad_tp in (True, False, float("nan"), float("inf"), 0.0, -1.0):
        with pytest.raises(ValueError, match="time_period must be positive"):
            validate_action_quantities("static_step", {"time_period": bad_tp})

    assert validate_action_quantities("static_step", {"time_period": 1.0}) is True
