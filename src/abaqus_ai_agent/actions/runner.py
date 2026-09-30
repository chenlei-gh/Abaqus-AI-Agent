from ..execution.client import AbaqusExecutor
from .script import action_to_script


def preview(action):
    return action_to_script(action)


def execute(executor, action):
    if not isinstance(executor, AbaqusExecutor):
        raise TypeError("executor must implement AbaqusExecutor")
    return executor.execute(action_to_script(action))
