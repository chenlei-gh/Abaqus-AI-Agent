import json

from ..contracts.results import (
    ResultExtraction,
    ResultRequirement,
    requirements_from_criteria,
)
from ..evidence.model import Evidence


def _payload(raw):
    if isinstance(raw, dict):
        if "values" in raw or "frame_value" in raw:
            return raw
        for key in ("result", "stdout", "output"):
            value = raw.get(key)
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                try:
                    return json.loads(value.strip().splitlines()[-1])
                except Exception:
                    pass
        return raw
    text = str(raw).strip()
    try:
        return json.loads(text.splitlines()[-1])
    except Exception:
        return {"values": [], "raw": raw}


def _scalar(item):
    if not isinstance(item, dict):
        return None
    data = item.get("data")
    if isinstance(data, (int, float)):
        return float(data)
    for key in ("magnitude", "mises", "maxPrincipal", "value"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    if isinstance(data, (list, tuple)) and len(data) == 1:
        try:
            return float(data[0])
        except Exception:
            pass
    return None


def _frame_value(executor, path, step, frame):
    code = """import json
from odbAccess import openOdb
odb=openOdb(path=%r, readOnly=True)
step_name=%r
if not step_name:
    names=list(odb.steps.keys())
    if not names:
        raise ValueError('ODB contains no analysis steps')
    step_name=names[-1]
st=odb.steps[step_name]
fr=st.frames[%r]
print(json.dumps({'step':step_name,'frame_index':%r,'frame_value':getattr(fr,'frameValue',None),
       'description':getattr(fr,'description',None)}))
odb.close()
""" % (path, step, frame, frame)
    return _payload(executor.execute(code))


def _history_output(executor, path, step, region, variable, aggregation):
    code = """import json
from odbAccess import openOdb
odb=openOdb(path=%r, readOnly=True)
regions=odb.steps[%r].historyRegions
region_name=%r
if region_name:
    hr=regions[region_name]
else:
    matches=[(_name,_value) for _name,_value in regions.items()
             if %r in _value.historyOutputs]
    if len(matches) != 1:
        raise KeyError('history output is ambiguous; specify history_region: %s' %% %r)
    region_name, hr=matches[0]
if hr is None or %r not in hr.historyOutputs:
    raise KeyError('history output not found: %s' %% %r)
data=list(hr.historyOutputs[%r].data)
values=[float(x[1]) for x in data]
if not values:
    raise ValueError('history output has no values')
if %r == 'max':
    value=max(values)
elif %r == 'min':
    value=min(values)
elif %r == 'average':
    value=sum(values)/float(len(values))
else:
    value=values[-1]
print(json.dumps({'region':region_name,'variable':%r,'aggregation':%r,'value':value,'count':len(values)}))
odb.close()
""" % (path, step, region, variable, variable, variable, aggregation,
       aggregation, aggregation, variable, aggregation)
    return _payload(executor.execute(code))


def _resolve_step_requirement(executor, path, step):
    """Resolve an omitted result step to the last analysis step in the ODB."""
    if step:
        return step
    code = """from odbAccess import openOdb
odb=openOdb(path=%r, readOnly=True)
names=list(odb.steps.keys())
if not names:
    raise ValueError('ODB contains no analysis steps')
print(names[-1])
odb.close()
""" % path
    raw = executor.execute(code)
    if isinstance(raw, str) and raw.strip():
        return raw.strip().splitlines()[-1].strip()
    if isinstance(raw, dict):
        for key in ("step", "stdout", "output"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().splitlines()[-1].strip()
        payload = _payload(raw)
        if isinstance(payload, dict):
            value = payload.get("step")
            if isinstance(value, str) and value.strip():
                return value.strip().splitlines()[-1].strip()
    raise ValueError("unable to resolve result step")


def extract_requirement(executor, path, requirement):
    from .odb import extract_field

    step = _resolve_step_requirement(executor, path, requirement.step)

    if requirement.output_kind == "history":
        payload = _history_output(
            executor, path, step, requirement.history_region,
            requirement.history_variable, requirement.aggregation)
        value = payload.get("value")
        if not isinstance(value, (int, float)):
            raise ValueError("history value unavailable for %s" % requirement.value_key)
        locator = {
            "step": step,
            "history_region": payload.get("region"),
            "history_region_expression": requirement.history_region_expression,
            "history_variable": requirement.history_variable,
        }
        return ResultExtraction(
            requirement, float(value), locator,
            (Evidence(kind="odb_history_result", source="odb",
              locator=str(locator), value=float(value), unit=requirement.unit,
              metadata={"value_key": requirement.value_key,
                        "aggregation": requirement.aggregation}),))

    if requirement.output_kind == "frame_value":
        payload = _frame_value(
            executor, path, step, requirement.frame)
        value = payload.get("frame_value")
        if not isinstance(value, (int, float)):
            raise ValueError("frame value unavailable for %s" % requirement.value_key)
        return ResultExtraction(
            requirement, float(value),
            locator={"step": payload.get("step", step), "frame": requirement.frame},
            evidence=(Evidence(kind="odb_frame_value", source="odb",
                        locator=str({"step": payload.get("step", step), "frame": requirement.frame}),
                        value=float(value), metadata={"payload": payload}),))

    payload = _payload(extract_field(
        executor, path, step, requirement.field,
        component=requirement.component, invariant=requirement.invariant,
        position=requirement.position, region=requirement.region,
        frame=requirement.frame))
    values = payload.get("values", [])
    scalar_values = []
    scalar_items = []
    for item in values:
        value = _scalar(item)
        if value is not None:
            scalar_values.append(value)
            scalar_items.append(item)
    if not scalar_values:
        raise ValueError("no numeric values extracted for %s" % requirement.value_key)

    if requirement.aggregation == "max":
        index = max(range(len(scalar_values)), key=scalar_values.__getitem__)
    elif requirement.aggregation == "min":
        index = min(range(len(scalar_values)), key=scalar_values.__getitem__)
    elif requirement.aggregation == "average":
        index = -1
    else:
        index = len(scalar_values) - 1

    if requirement.aggregation == "average":
        value = sum(scalar_values) / float(len(scalar_values))
        locator = {"step": step, "frame": requirement.frame}
    else:
        value = scalar_values[index]
        item = scalar_items[index]
        locator = {
            "step": step,
            "frame": requirement.frame,
            "instance": item.get("instance"),
            "node_label": item.get("node_label"),
            "element_label": item.get("element_label"),
            "coordinates": item.get("coordinates"),
            "position": item.get("position"),
        }

    evidence = Evidence(
        kind="odb_result",
        source="odb",
        locator=str(locator),
        value=float(value),
        unit=requirement.unit,
        metadata={
            "value_key": requirement.value_key,
            "field": requirement.field,
            "component": requirement.component,
            "invariant": requirement.invariant,
            "aggregation": requirement.aggregation,
        },
    )
    return ResultExtraction(requirement, float(value), locator, (evidence,))


def extract_criteria(executor, path, criteria):
    requirements = requirements_from_criteria(criteria)
    results = {}
    evidence = []
    for requirement in requirements:
        result = extract_requirement(executor, path, requirement)
        results[requirement.value_key] = result.value
        evidence.extend(result.evidence)
    return results, tuple(evidence)


def extract_requirements(executor, path, criteria):
    """Extract typed ResultExtraction objects without collapsing them to values."""
    requirements = requirements_from_criteria(criteria)
    extractions = []
    evidence = []
    for requirement in requirements:
        result = extract_requirement(executor, path, requirement)
        extractions.append(result)
        evidence.extend(result.evidence)
    return tuple(extractions), tuple(evidence)
