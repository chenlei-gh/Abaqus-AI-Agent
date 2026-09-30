from dataclasses import dataclass, field


@dataclass(frozen=True)
class EngineeringPlan:
    intents: tuple = field(default_factory=tuple)
    assumptions: tuple = field(default_factory=tuple)
    blockers: tuple = field(default_factory=tuple)


def plan_from_intents(intents, *, known_material=False, grounded_regions=False):
    blockers = []
    assumptions = []
    if not known_material:
        blockers.append("material_not_confirmed")
    if not grounded_regions:
        blockers.append("geometry_regions_not_grounded")
    for intent in intents:
        if getattr(intent, "magnitude", None) is None and getattr(intent, "kind", "") in ("force", "pressure", "temperature"):
            blockers.append("missing_magnitude:%s" % getattr(intent, "id", "unknown"))
    if grounded_regions:
        assumptions.append("all action regions have explicit Abaqus entity evidence")
    return EngineeringPlan(tuple(intents), tuple(assumptions), tuple(blockers))
