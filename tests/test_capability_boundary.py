from abaqus_ai_agent.actions import python_action, static_step
from abaqus_ai_agent.capability_boundary import CapabilityStatus, classify_action


def test_typed_action_is_formally_supported():
    boundary = classify_action(static_step("Model-1"))
    assert boundary.status == CapabilityStatus.SUPPORTED
    assert boundary.formally_supported
    assert boundary.executable
    assert not boundary.engineering_verified


def test_native_python_is_executable_but_not_formally_supported():
    boundary = classify_action(
        python_action("Model-1", "print(list(mdb.models.keys()))")
    )
    assert boundary.status == CapabilityStatus.EXECUTABLE
    assert boundary.executable
    assert not boundary.formally_supported
    assert not boundary.engineering_verified
    assert "escape hatch" in boundary.reason


def test_capability_boundary_does_not_promote_engineering_correctness():
    boundary = classify_action(static_step("Model-1"))
    assert boundary.status == CapabilityStatus.SUPPORTED
    assert boundary.engineering_verified is False
