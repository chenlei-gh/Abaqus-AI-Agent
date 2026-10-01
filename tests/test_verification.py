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


def test_expected_state_verification_accepts_model_snapshot():
    from abaqus_ai_agent.contracts.model_snapshot import ModelSnapshot

    snapshot = ModelSnapshot(models=("Model-1",), parts=("P",))
    result = verify_expected_state(
        snapshot,
        ({"path": "models", "contains": "Model-1"},),
    )
    assert result.passed


def test_verification_failure_is_not_overwritten_in_journal():
    from abaqus_ai_agent.actions.runner import execute_verified
    from abaqus_ai_agent.execution.client import InProcessExecutor

    action = AbaqusAction(
        "material_elastic", "Model-1", None, {"name": "Steel", "youngs_modulus": 210000.0, "poisson": 0.3},
        expected_state=({"path": "materials", "contains": "Missing"},),
    )
    executor = InProcessExecutor(lambda code: {"ok": True})
    try:
        execute_verified(executor, action, snapshot_after={"materials": ()})
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected verification failure")
