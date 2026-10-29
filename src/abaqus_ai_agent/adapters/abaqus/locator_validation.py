from dataclasses import dataclass

@dataclass(frozen=True)
class LocatorValidationResult:
    valid: bool
    reason: str

def reject_locator_identity(candidate):
    """Reject identities that findAt cannot safely resolve.

    Abaqus findAt uses a 1E-6 tolerance and returns the first object at a shared
    point. Integer ids are not stable locators. Part and instance coordinates
    must not be mixed.
    """
    point = getattr(candidate, "locator_point", None)
    if point is None:
        point = getattr(candidate, "centroid", None)
    # GeometryCandidate.index is catalog metadata, not a locator. Reject only an
    # identity that is actually being used in place of a finite 3D point.
    entity_id = getattr(candidate, "entity_id", None)
    if isinstance(point, int) and not isinstance(point, bool):
        return "integer_id_not_a_locator"
    if isinstance(entity_id, int) and not isinstance(entity_id, bool) and not _finite_point(point):
        return "integer_id_not_a_locator"
    frame = getattr(candidate, "coordinate_frame", None) or getattr(candidate, "space", None)
    if frame in ("part", "instance") and getattr(candidate, "bound_space", None) not in (None, frame):
        return "part_instance_coordinate_confusion"
    if point is not None and not _finite_point(point):
        return "locator_not_finite"
    return None


def _finite_point(point):
    try:
        values = tuple(float(item) for item in point)
    except (TypeError, ValueError):
        return False
    return len(values) == 3 and all(value == value and abs(value) != float("inf") for value in values)


def locator_guard_script():
    """CAE-side guard inserted before a region is bound.

    The host cannot call findAt. The generated script must reject a shared
    boundary, a non-unique hit, and an integer id before creating the region.
    """
    return (
        "def _abqai_bind_region(repository, points, label):\n"
        "    if not points:\n"
        "        raise RuntimeError(label + ': empty locator')\n"
        "    hits = []\n"
        "    for point in points:\n"
        "        if isinstance(point, int):\n"
        "            raise RuntimeError(label + ': integer_id_or_bad_point')\n"
        "        if len(tuple(point)) == 1 and len(tuple(point[0])) == 3:\n"
        "            point = point[0]\n"
        "        if len(tuple(point)) != 3:\n"
        "            raise RuntimeError(label + ': integer_id_or_bad_point')\n"
        "        found = repository.findAt(((float(point[0]), float(point[1]), float(point[2])),))\n"
        "        found_items = found if isinstance(found, (tuple, list)) else (found,)\n"
        "        if len(found_items) != 1 or found_items[0] is None:\n"
        "            raise RuntimeError(label + ': findAt_not_unique')\n"
        "        hits.append(found_items[0])\n"
        "    if len(set(id(item) for item in hits)) != len(hits):\n"
        "        raise RuntimeError(label + ': shared_boundary')\n"
        "    return hits[0] if len(hits) == 1 else hits\n"
    )


def validate_locator(instance, candidate):
    identity = reject_locator_identity(candidate)
    if identity:
        return LocatorValidationResult(False, identity)
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
