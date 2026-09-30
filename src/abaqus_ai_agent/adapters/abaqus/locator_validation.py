from dataclasses import dataclass

@dataclass(frozen=True)
class LocatorValidationResult:
    valid: bool
    reason: str

def validate_locator(instance, candidate):
    if candidate.entity_type not in ("Face", "Edge", "Vertex"):
        return LocatorValidationResult(False, "unsupported_entity_type")
    point = candidate.locator_point or candidate.centroid
    if point is None:
        return LocatorValidationResult(False, "missing_locator")
    repository = getattr(instance, {"Face":"faces","Edge":"edges","Vertex":"vertices"}[candidate.entity_type])
    try:
        result = repository.findAt((tuple(point),))
    except Exception as exc:
        return LocatorValidationResult(False, "findAt_failed:" + exc.__class__.__name__)
    if isinstance(result, (tuple, list)) and len(result) != 1:
        return LocatorValidationResult(False, "findAt_not_unique")
    entity = result[0] if isinstance(result, (tuple, list)) else result
    if not any(item is entity for item in repository):
        return LocatorValidationResult(False, "entity_instance_mismatch")
    return LocatorValidationResult(True, "validated")
