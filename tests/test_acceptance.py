from abaqus_ai_agent.acceptance import evaluate_criteria


def test_acceptance_passes():
    result = evaluate_criteria(
        {"max_stress": 180.0},
        [{"name": "stress", "value_key": "max_stress",
          "operator": "<", "limit": 250.0, "unit": "MPa"}],
    )
    assert result.passed
    assert not result.failures


def test_acceptance_fails():
    result = evaluate_criteria(
        {"max_stress": 280.0},
        [{"name": "stress", "value_key": "max_stress",
          "operator": "<", "limit": 250.0, "unit": "MPa"}],
    )
    assert not result.passed
    assert len(result.failures) == 1


def test_acceptance_relative_tolerance_and_warning():
    result = evaluate_criteria(
        {"stress": 101.0},
        [{"name": "stress", "value_key": "stress", "operator": "<", "limit": 100.0,
          "relative_tolerance": 0.02, "unit": "MPa"}],
    )
    assert result.passed
    assert result.criteria[0].relative_error == 0.01


def test_acceptance_warns_when_tolerance_has_no_order_semantics():
    result = evaluate_criteria(
        {"stress": 100.1},
        [{"value_key": "stress", "operator": "==", "limit": 100.0,
          "relative_tolerance": 0.01}],
    )
    assert not result.passed
    assert result.warnings == ("relative_tolerance_ignored_for_==",)
