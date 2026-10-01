import pytest

from abaqus_ai_agent.actions import (
    fixed_bc, pressure_load, material_elastic, python_action, static_step,
    dynamic_explicit_step, implicit_dynamic_step, heat_transfer_step, coupled_temp_displacement_step,
    tabular_amplitude, smooth_step_amplitude, periodic_amplitude, equally_spaced_amplitude,
    initial_temperature, initial_stress, gravity,
    assembly_inspect, instance_translate, instance_rotate, instance_linear_pattern,
    export_inp, export_odb_csv, bias_seed_size, bias_seed_number, sweep_path, verify_mesh_quality,
)
from abaqus_ai_agent.actions.runner import preview
from abaqus_ai_agent.validation.actions import validate_action


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


def test_mesh_strategy_scripts():
    assert "seedEdgeByBias" in preview(bias_seed_size("M", "P", "p.edges", 0.5, 2.0))
    assert "minSize=0.5" in preview(bias_seed_size("M", "P", "p.edges", 0.5, 2.0))
    assert "number=12" in preview(bias_seed_number("M", "P", "p.edges", 12, 4.0, end="END2"))
    assert "end2Edges" in preview(bias_seed_number("M", "P", "p.edges", 12, 4.0, end="END2"))
    assert "setSweepPath" in preview(sweep_path("M", "P", "p.cells", "p.edges[0]"))
    assert "verifyMeshQuality" in preview(verify_mesh_quality("M", "P"))
    assert "criterion=ANALYSIS_CHECKS" in preview(verify_mesh_quality("M", "P"))
    assert "threshold=5.0" in preview(verify_mesh_quality("M", "P", criterion="ASPECT_RATIO", threshold=5.0))
    with pytest.raises(ValueError):
        preview(verify_mesh_quality("M", "P", criterion="ASPECT_RATIO"))


def test_mesh_actions_validate():
    assert validate_action(bias_seed_size("M", "P", "p.edges", 0.5, 2.0))
    assert validate_action(bias_seed_number("M", "P", "p.edges", 12, 4.0, end="END2"))
    assert validate_action(sweep_path("M", "P", "p.cells", "p.edges[0]"))
    assert validate_action(verify_mesh_quality("M", "P"))
    with pytest.raises(ValueError):
        validate_action(verify_mesh_quality("M", "P", criterion="ASPECT_RATIO"))
