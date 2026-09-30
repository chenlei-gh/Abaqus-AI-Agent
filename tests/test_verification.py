from abaqus_ai_agent.contracts.action import AbaqusAction
from abaqus_ai_agent.verification import verify_expected_state
from abaqus_ai_agent.validation.preflight import preflight_action


def test_expected_state_verification():
    snapshot = {"models": {"Model-1": {"parts": ["P"]}}}
    result = verify_expected_state(
        snapshot,
        ({"path": "models.Model-1.parts", "contains": "P"},),
    )
    assert result.passed


def test_preflight_model_exists():
    action = AbaqusAction("material_elastic", "Model-1", None, {"name": "Steel"})
    result = preflight_action(action, {"models": {"Model-1": {}}})
    assert result.passed
