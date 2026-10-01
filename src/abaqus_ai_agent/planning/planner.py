from dataclasses import dataclass, field

from ..contracts.units import validate_quantity_unit


@dataclass(frozen=True)
class EngineeringPlan:
    intents: tuple = field(default_factory=tuple)
    assumptions: tuple = field(default_factory=tuple)
    blockers: tuple = field(default_factory=tuple)


_INTENT_QUANTITIES = {
    "force": "force",
    "pressure": "pressure",
    "temperature": "temperature",
    "displacement": "displacement",
    "length": "length",
    "stress": "stress",
    "time": "time",
    "energy": "energy",
    "frequency": "frequency",
}


def _validate_intent_units(intent):
    magnitude = getattr(intent, "magnitude", None)
    unit = getattr(intent, "unit", None)
    if magnitude is None or unit in (None, ""):
        return
    kind = str(getattr(intent, "kind", "")).lower()
    quantity = _INTENT_QUANTITIES.get(kind)
    if quantity is None:
        raise ValueError(
            "cannot validate unit for unknown intent kind: %s" % kind
        )
    validate_quantity_unit(
        quantity,
        unit,
        getattr(intent, "unit_system", None),
    )


def plan_from_intents(intents, *, known_material=False, grounded_regions=False):
    blockers = []
    assumptions = []
    if not known_material:
        blockers.append("material_not_confirmed")
    if not grounded_regions:
        blockers.append("geometry_regions_not_grounded")
    for intent in intents:
        _validate_intent_units(intent)
        if getattr(intent, "magnitude", None) is None and getattr(intent, "kind", "") in ("force", "pressure", "temperature"):
            blockers.append("missing_magnitude:%s" % getattr(intent, "id", "unknown"))
    if grounded_regions:
        assumptions.append("all action regions have explicit Abaqus entity evidence")
    return EngineeringPlan(tuple(intents), tuple(assumptions), tuple(blockers))
