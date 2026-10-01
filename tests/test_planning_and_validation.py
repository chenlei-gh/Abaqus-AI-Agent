import pytest
from abaqus_ai_agent.actions import fixed_bc, gravity, tabular_amplitude, instance_translate, export_odb_csv
from abaqus_ai_agent.planning import plan_from_intents
from abaqus_ai_agent.validation import validate_action


def test_unvalidated_region_is_rejected():
    with pytest.raises(ValueError):
        validate_action(fixed_bc("M", "F", ""))


def test_plan_reports_missing_grounding():
    plan = plan_from_intents([], known_material=True, grounded_regions=False)
    assert "geometry_regions_not_grounded" in plan.blockers


def test_new_actions_validate():
    assert validate_action(gravity("M", "G", comp3=-9.81))
    assert validate_action(tabular_amplitude("M", "A", ((0.0, 0.0), (1.0, 1.0))))
    assert validate_action(instance_translate("M", "P-1", (1.0, 0.0, 0.0)))
    assert validate_action(export_odb_csv("M", "a.odb", "a.csv", variable="U"))


def test_invalid_new_actions_are_rejected():
    with pytest.raises(ValueError):
        validate_action(gravity("M", "G"))
    with pytest.raises(ValueError):
        validate_action(tabular_amplitude("M", "A", ()))
