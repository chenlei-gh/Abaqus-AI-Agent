from abaqus_ai_agent.contracts.units import UnitSystem, unit_dimension, validate_same_dimension


def test_unit_dimension_and_compatibility():
    assert UnitSystem.named("MM_N_MPA").unit("stress") == "MPa"
    assert unit_dimension("MPa") == "stress"
    assert validate_same_dimension(("MPa", "Pa")) == "stress"


def test_unit_dimension_rejects_mixed_quantities():
    try:
        validate_same_dimension(("MPa", "mm"))
    except ValueError:
        pass
    else:
        raise AssertionError("mixed dimensions must be rejected")
