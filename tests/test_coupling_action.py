import pytest

from abaqus_ai_agent.actions.builders import coupling_constraint
from abaqus_ai_agent.actions.script import action_to_script
from abaqus_ai_agent.validation.actions import validate_action


def test_coupling_constraint_builder_nominal():
    act = coupling_constraint(
        model="Model-1",
        name="Coupling-1",
        control_point_name="RP-Hinge",
        surface_name="BeamEndFace",
        coupling_type="KINEMATIC",
        u1=True,
        u2=True,
        u3=True,
        ur1=True,
        ur2=False,
        ur3=True,
    )
    assert act.action_type == "coupling_constraint"
    assert act.parameters["name"] == "Coupling-1"
    assert act.parameters["control_point_name"] == "RP-Hinge"
    assert act.parameters["surface_name"] == "BeamEndFace"
    assert act.parameters["coupling_type"] == "KINEMATIC"
    assert act.parameters["ur2"] is False
    assert validate_action(act) is True


def test_coupling_constraint_distributing_continuum():
    act = coupling_constraint(
        model="Model-1",
        name="Coupling-Dist",
        control_point_expression="a.sets['RP-Dist']",
        surface_expression="a.surfaces['HoleInner']",
        coupling_type="DISTRIBUTING",
        influence_radius=15.0,
    )
    assert validate_action(act) is True
    script = action_to_script(act)
    assert "model.Coupling" in script
    assert "couplingType=CONTINUUM" in script
    assert "influenceRadius=15.0" in script


def test_coupling_constraint_validation_failures():
    # Missing name
    with pytest.raises(ValueError, match="name is required"):
        act = coupling_constraint("Model-1", name="", control_point_name="RP-1", surface_name="Face-1")
        validate_action(act)

    # Missing control point
    with pytest.raises(ValueError, match="control_point_name or control_point_expression is required"):
        act = coupling_constraint("Model-1", name="C1", surface_name="Face-1")
        validate_action(act)

    # Missing surface
    with pytest.raises(ValueError, match="surface_name or surface_expression is required"):
        act = coupling_constraint("Model-1", name="C1", control_point_name="RP-1")
        validate_action(act)

    # Unsupported coupling type
    with pytest.raises(ValueError, match="unsupported coupling_type"):
        act = coupling_constraint("Model-1", name="C1", control_point_name="RP-1", surface_name="F1", coupling_type="INVALID")
        validate_action(act)

    # Negative influence radius
    with pytest.raises(ValueError, match="influence_radius must be positive"):
        act = coupling_constraint("Model-1", name="C1", control_point_name="RP-1", surface_name="F1", influence_radius=-5.0)
        validate_action(act)


def test_coupling_constraint_script_generation():
    act = coupling_constraint(
        model="Model-1",
        name="C-Pin",
        control_point_name="RP-Joint",
        surface_name="PinSurface",
        coupling_type="KINEMATIC",
        u1=True, u2=True, u3=True, ur1=False, ur2=False, ur3=False
    )
    code = action_to_script(act)
    assert "model = mdb.models['Model-1']" in code
    assert "model.Coupling(name='C-Pin'" in code
    assert "couplingType=KINEMATIC" in code
    assert "u1=ON" in code
    assert "ur1=OFF" in code
    assert "_resolve_pt_region" in code
    assert "_resolve_surf_region" in code
