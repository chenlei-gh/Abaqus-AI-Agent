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


def _findat_hits(found):
    """Normalize a findAt result by length, not by Python container type.

    Abaqus returns a GeomSequence. An empty sequence is not a tuple or list, so
    wrapping every non-list result as ``(found,)`` turns a miss into one hit.
    A single Face has no length and stays one hit. None and a zero-length
    sequence stay empty.
    """
    if found is None:
        return ()
    try:
        count = len(found)
    except Exception:
        return (found,)
    hits = []
    for index in range(count):
        hits.append(found[index])
    return tuple(hits)


def locator_guard_script():
    """CAE-side guard inserted before a region is bound.

    The host cannot call findAt. The generated script must reject a shared
    boundary, a non-unique hit, an empty GeomSequence, and an integer id
    before creating the region. Abaqus/CAE may still be on Python 2, so the
    emitted script uses no f-strings or annotations.
    """
    return (
        "def _abqai_findat_hits(found):\n"
        "    if found is None:\n"
        "        return ()\n"
        "    try:\n"
        "        count = len(found)\n"
        "    except Exception:\n"
        "        return (found,)\n"
        "    hits = []\n"
        "    for index in range(count):\n"
        "        hits.append(found[index])\n"
        "    return tuple(hits)\n"
        "def _abqai_bind_region(repository, points, label):\n"
        "    if not points:\n"
        "        raise RuntimeError(label + ': empty locator')\n"
        "    hits = []\n"
        "    sequences = []\n"
        "    for point in points:\n"
        "        if isinstance(point, int):\n"
        "            raise RuntimeError(label + ': integer_id_or_bad_point')\n"
        "        if len(tuple(point)) == 1 and len(tuple(point[0])) == 3:\n"
        "            point = point[0]\n"
        "        if len(tuple(point)) != 3:\n"
        "            raise RuntimeError(label + ': integer_id_or_bad_point')\n"
        "        found = repository.findAt(((float(point[0]), float(point[1]), float(point[2])),))\n"
        "        found_items = _abqai_findat_hits(found)\n"
        "        if len(found_items) == 0 or found_items[0] is None:\n"
        "            raise RuntimeError(label + ': findAt_empty')\n"
        "        if len(found_items) != 1:\n"
        "            raise RuntimeError(label + ': findAt_not_unique')\n"
        "        hits.append(found_items[0])\n"
        "        sequences.append(found)\n"
        "    if len(hits) == 0:\n"
        "        raise RuntimeError(label + ': findAt_empty')\n"
        "    if len(set(id(item) for item in hits)) != len(hits):\n"
        "        raise RuntimeError(label + ': shared_boundary')\n"
        "    if len(sequences) == 1:\n"
        "        region = sequences[0]\n"
        "        try:\n"
        "            empty = len(region) == 0\n"
        "        except Exception:\n"
        "            region = tuple(hits)\n"
        "            empty = False\n"
        "        if empty:\n"
        "            raise RuntimeError(label + ': findAt_empty')\n"
        "    else:\n"
        "        region = tuple(hits)\n"
        "    return region\n"
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
    hits = _findat_hits(result)
    if len(hits) == 0 or hits[0] is None:
        return LocatorValidationResult(False, "findAt_empty")
    if len(hits) != 1:
        return LocatorValidationResult(False, "findAt_not_unique")
    entity = hits[0]
    if not any(item is entity for item in repository):
        return LocatorValidationResult(False, "entity_instance_mismatch")
    return LocatorValidationResult(True, "validated")
