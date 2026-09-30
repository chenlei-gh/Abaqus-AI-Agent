import pytest
from abaqus_ai_agent.actions import fixed_bc
from abaqus_ai_agent.planning import plan_from_intents
from abaqus_ai_agent.validation import validate_action


def test_unvalidated_region_is_rejected():
    with pytest.raises(ValueError):
        validate_action(fixed_bc("M", "F", ""))


def test_plan_reports_missing_grounding():
    plan = plan_from_intents([], known_material=True, grounded_regions=False)
    assert "geometry_regions_not_grounded" in plan.blockers
