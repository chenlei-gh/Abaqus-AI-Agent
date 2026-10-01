from dataclasses import dataclass
from typing import Tuple

from ..contracts.results import required_field_variables, requirements_from_criteria


@dataclass(frozen=True)
class OutputPlan:
    field_variables: Tuple[str, ...] = ()
    history_variables: Tuple[str, ...] = ()
    history_step: str = "Step-1"
    history_region_expression: object = None
    requirements: Tuple[object, ...] = ()
    history_requests: Tuple[Tuple[str, object, Tuple[str, ...]], ...] = ()


def criteria_from_postprocess_profile(profile):
    """Convert deterministic post-processing requirements into ODB output criteria."""
    criteria = []
    for key in getattr(profile, "required_results", ()):
        criteria.append({"name": key, "value_key": key})
    for variable in getattr(profile, "history_variables", ()):
        criteria.append({
            "name": variable,
            "value_key": "history_%s" % variable,
            "result": {
                "output_kind": "history",
                "history_variable": variable,
                "step": getattr(profile, "history_step", None),
                "aggregation": "last",
            },
            "step": getattr(profile, "history_step", None),
        })
    return tuple(criteria)


def plan_outputs(criteria=(), outputs=(), postprocess_profile=None):
    """Derive the minimum deterministic output-variable plan.

    Explicit user outputs are preserved; criterion-driven variables are added
    rather than silently replacing them.

    History outputs are grouped by step and region expression so requirements
    from different analysis steps cannot be silently emitted into one request.
    """
    if postprocess_profile is not None:
        profile_criteria = criteria_from_postprocess_profile(postprocess_profile)
        existing_keys = {c.get("value_key") for c in criteria or () if isinstance(c, dict)}
        criteria = tuple(criteria or ()) + tuple(c for c in profile_criteria if c.get("value_key") not in existing_keys)
    requirements = requirements_from_criteria(criteria)
    fields = set(required_field_variables(requirements))
    history_requirements = tuple(
        r for r in requirements
        if getattr(r, "output_kind", None) == "history" and r.history_variable
    )
    histories = set(r.history_variable for r in history_requirements)

    groups = {}
    for r in history_requirements:
        key = (
            r.step or "Step-1",
            r.history_region_expression,
            r.history_region,
        )
        groups.setdefault(key, set()).add(r.history_variable)
    history_requests = tuple(
        (step, region_expression, tuple(sorted(variables)))
        for (step, region_expression, _region), variables in sorted(
            groups.items(), key=lambda item: (item[0][0], repr(item[0][1]), repr(item[0][2]))
        )
    )

    history_step = history_requests[0][0] if history_requests else "Step-1"
    history_region_expression = (
        history_requests[0][1] if history_requests else None
    )

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

    return OutputPlan(
        tuple(sorted(fields)), tuple(sorted(histories)), history_step,
        history_region_expression, requirements, history_requests
    )


def actions_from_output_plan(
    model_name, plan, field_request="AI-F-Output-1", history_request="AI-H-Output-1"
):
    """Materialize an OutputPlan into explicit Abaqus output-request actions."""
    from ..actions.builders import field_output, history_output

    actions = []
    if plan.field_variables:
        actions.append(
            field_output(
                model_name,
                variables=plan.field_variables,
                request=field_request,
                step="Initial",
            )
        )

    if plan.history_requests:
        for index, (step, region_expression, variables) in enumerate(plan.history_requests):
            request = history_request if index == 0 else "%s-%d" % (history_request, index + 1)
            actions.append(
                history_output(
                    model_name,
                    variables=variables,
                    request=request,
                    region_expression=region_expression,
                    step=step,
                )
            )
    elif plan.history_variables:
        actions.append(
            history_output(
                model_name,
                variables=plan.history_variables,
                request=history_request,
                region_expression=plan.history_region_expression,
                step=plan.history_step,
            )
        )
    return tuple(actions)
