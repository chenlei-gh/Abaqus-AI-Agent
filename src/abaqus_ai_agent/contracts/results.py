from dataclasses import dataclass, field as dataclass_field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class ResultRequirement:
    """Deterministic description of one engineering result needed for acceptance."""
    name: str
    value_key: str
    field: Optional[str] = None
    component: Optional[str] = None
    invariant: Optional[str] = None
    aggregation: str = "max"
    step: Optional[str] = None
    frame: int = -1
    position: Optional[str] = None
    region: Optional[str] = None
    history_region: Optional[str] = None
    history_variable: Optional[str] = None
    unit: str = ""
    output_kind: str = "field"
    metadata: Dict[str, Any] = dataclass_field(default_factory=dict)

    def __post_init__(self):
        if self.aggregation not in ("max", "min", "average", "last"):
            raise ValueError("unsupported aggregation: %s" % self.aggregation)
        if self.output_kind not in ("field", "history", "frame_value"):
            raise ValueError("unsupported output_kind: %s" % self.output_kind)
        if self.output_kind == "field" and not self.field:
            raise ValueError("field is required for field output requirements")
        if self.output_kind == "history" and not self.history_variable:
            raise ValueError("history_variable is required for history output requirements")


@dataclass(frozen=True)
class ResultExtraction:
    requirement: ResultRequirement
    value: float
    locator: Dict[str, Any] = dataclass_field(default_factory=dict)
    evidence: Tuple[Dict[str, Any], ...] = ()


_FIELD_ALIASES = {
    "max_stress": ("S", "MISES"),
    "max_mises": ("S", "MISES"),
    "max_displacement": ("U", "MAGNITUDE"),
    "max_u": ("U", "MAGNITUDE"),
    "min_displacement": ("U", "MAGNITUDE"),
    "max_temperature": ("NT11", None),
    "max_strain": ("E", "MISES"),
    "max_reaction_force": ("RF", "MAGNITUDE"),
    "max_rf": ("RF", "MAGNITUDE"),
}


def requirement_from_criterion(criterion):
    key = criterion.get("value_key")
    if not key:
        raise ValueError("criterion requires value_key")
    explicit = criterion.get("result")
    if explicit:
        data = dict(explicit)
        data.setdefault("name", criterion.get("name", key))
        data.setdefault("value_key", key)
        data.setdefault("unit", criterion.get("unit", ""))
        return ResultRequirement(**data)

    if key == "frequency":
        return ResultRequirement(
            name=criterion.get("name", key), value_key=key,
            aggregation="last", output_kind="frame_value",
            step=criterion.get("step"), unit=criterion.get("unit", "Hz"))

    alias = _FIELD_ALIASES.get(key)
    if not alias:
        raise ValueError(
            "no deterministic ODB mapping for result '%s'; "
            "provide criterion.result" % key)

    field, invariant = alias
    aggregation = "min" if key == "min_displacement" else "max"
    return ResultRequirement(
        name=criterion.get("name", key), value_key=key,
        field=field, invariant=invariant, aggregation=aggregation,
        step=criterion.get("step"), frame=criterion.get("frame", -1),
        position=criterion.get("position"), region=criterion.get("region"),
        unit=criterion.get("unit", ""))


def requirements_from_criteria(criteria):
    return tuple(requirement_from_criterion(c) for c in criteria or ())


def required_field_variables(requirements):
    return tuple(sorted(set(
        r.field for r in requirements
        if r.output_kind == "field" and r.field)))
