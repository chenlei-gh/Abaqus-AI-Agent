from ..contracts.action import AbaqusAction


def python_action(model_name, code, *, requires_confirmation=True):
    """Escape hatch for the complete native Abaqus Python API.

    This is the compatibility mechanism for Abaqus features not represented by
    a typed builder yet. The code remains visible in the action contract.
    """
    return AbaqusAction("python", model_name, None, {"code": code}, requires_confirmation)
