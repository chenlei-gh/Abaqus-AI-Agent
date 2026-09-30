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
