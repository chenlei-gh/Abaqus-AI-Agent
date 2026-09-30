from abaqus_ai_agent.actions import fixed_bc, pressure_load, material_elastic, python_action, static_step
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
