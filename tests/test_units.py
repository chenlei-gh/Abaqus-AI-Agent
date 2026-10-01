from abaqus_ai_agent.contracts.units import (
    UnitSystem,
    unit_dimension,
    validate_quantity_unit,
    validate_same_dimension,
)
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.planning.planner import plan_from_intents
from abaqus_ai_agent.contracts.results import requirements_from_criteria


def test_unit_dimension_and_compatibility():
    assert UnitSystem.named("MM_N_MPA").unit("stress") == "MPa"
    assert unit_dimension("MPa") == "stress"
    assert UnitSystem.named("MM_N_MPA").unit("energy") == "N*mm"
    assert validate_same_dimension(("MPa", "Pa")) == "stress"


def test_quantity_unit_validation():
    assert validate_quantity_unit("force", "N", "MM_N_MPA")
    assert validate_quantity_unit("displacement", "mm", "MM_N_MPA")
    assert validate_quantity_unit("stress", "Pa")
    try:
        validate_quantity_unit("force", "MPa")
    except ValueError:
        pass
    else:
        raise AssertionError("force/stress dimension mismatch was accepted")


def test_planning_validates_declared_intent_units():
    intent = EngineeringIntent(
        id="load",
        kind="force",
        description="tip load",
        magnitude=100.0,
        unit="N",
        unit_system="MM_N_MPA",
    )
    plan = plan_from_intents((intent,), known_material=True, grounded_regions=True)
    assert not plan.blockers


def test_planning_rejects_inconsistent_intent_units():
    intent = EngineeringIntent(
        id="load",
        kind="force",
        description="tip load",
        magnitude=100.0,
        unit="MPa",
        unit_system="MM_N_MPA",
    )
    try:
        plan_from_intents((intent,), known_material=True, grounded_regions=True)
    except ValueError:
        pass
    else:
        raise AssertionError("inconsistent force unit was accepted")


def test_result_requirement_validates_units():
    requirements = requirements_from_criteria((
        {"value_key": "max_stress", "operator": "<=", "limit": 200.0, "unit": "MPa"},
        {"value_key": "max_displacement", "operator": "<=", "limit": 1.0, "unit": "mm"},
        {"value_key": "frequency", "operator": ">=", "limit": 10.0, "unit": "Hz"},
    ))
    assert [item.quantity for item in requirements] == [
        "stress", "displacement", "frequency"
    ]


def test_result_requirement_rejects_inconsistent_units():
    try:
        requirements_from_criteria((
            {"value_key": "max_stress", "operator": "<=", "limit": 200.0, "unit": "mm"},
        ))
    except ValueError:
        pass
    else:
        raise AssertionError("inconsistent result unit was accepted")
