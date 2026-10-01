from dataclasses import dataclass
from typing import Tuple

from ..contracts.results import required_field_variables, requirements_from_criteria


@dataclass(frozen=True)
class OutputPlan:
    field_variables: Tuple[str, ...] = ()
    history_variables: Tuple[str, ...] = ()
    requirements: Tuple[object, ...] = ()


def plan_outputs(criteria=(), outputs=()):
    """Derive the minimum deterministic output-variable plan.

    Explicit user outputs are preserved; criterion-driven variables are added
    rather than silently replacing them.
    """
    requirements = requirements_from_criteria(criteria)
    fields = set(required_field_variables(requirements))
    histories = set()
    for item in outputs or ():
        if isinstance(item, str):
            fields.add(item)
        elif isinstance(item, dict):
            kind = item.get("kind", "field")
            variables = item.get("variables", ())
            if kind == "history":
                histories.update(variables)
            else:
                fields.update(variables)
    return OutputPlan(tuple(sorted(fields)), tuple(sorted(histories)), requirements)


def actions_from_output_plan(model_name, plan, field_request="AI-F-Output-1", history_request="AI-H-Output-1"):
    """Materialize an OutputPlan into explicit Abaqus output-request actions."""
    from ..actions.builders import field_output, history_output
    actions = []
    if plan.field_variables:
        actions.append(field_output(model_name, variables=plan.field_variables, request=field_request, step="Initial"))
    if plan.history_variables:
        actions.append(history_output(model_name, variables=plan.history_variables, request=history_request, step="Step-1"))
    return tuple(actions)
