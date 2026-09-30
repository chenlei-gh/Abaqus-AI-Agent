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
