"""Lifecycle checks for named Abaqus assembly regions.

Policy is conservative: an existing name is never overwritten implicitly.
Reuse is allowed only after validating entity type and membership.
"""


def _repository(assembly, kind):
    return assembly.sets if kind == "set" else assembly.surfaces


def _members(obj, entity_type):
    attr = {
        "Face": "faces",
        "Edge": "edges",
        "Vertex": "vertices",
    }[entity_type]
    return tuple(getattr(obj, attr, ()))


def _contains_all(existing, resolved):
    members = _members(existing, resolved[0][0] if resolved else "Face")
    return all(any(item is member for member in members) for item in resolved)


def inspect_existing(assembly, selection):
    """Return existing named region, or None if it does not exist."""
    if selection.region_kind == "temporary":
        return None
    return _repository(assembly, selection.region_kind).get(selection.name)


def validate_existing(assembly, selection):
    """Validate an existing named region against grounded targets.

    Returns (True, 'exact membership') on success. This is intentionally
    conservative; absence of a reliable sidedness/member API is treated as
    non-equivalent rather than guessed.
    """
    existing = inspect_existing(assembly, selection)
    if existing is None:
        return False, "not_found"

    resolved = []
    for target in selection.targets:
        instance = assembly.instances[target["instance"]]
        entity_type = selection.entity_type
        repo = getattr(instance, {
            "Face": "faces", "Edge": "edges", "Vertex": "vertices"
        }[entity_type])
        resolved.append((entity_type, repo.findAt((tuple(target["point"]),))))

    if not resolved:
        return False, "empty_selection"

    members = _members(existing, selection.entity_type)
    if len(members) != len(resolved):
        return False, "member_count_mismatch"

    if not all(any(item is member for member in members) for _, item in resolved):
        return False, "membership_mismatch"

    if selection.region_kind == "surface":
        side_attr = selection.surface_side + selection.entity_type + "s"
        if not hasattr(existing, side_attr):
            return False, "sidedness_not_verifiable"
        side_members = tuple(getattr(existing, side_attr))
        if len(side_members) != len(resolved):
            return False, "side_membership_mismatch"
        if not all(any(item is member for member in side_members) for _, item in resolved):
            return False, "side_membership_mismatch"

    return True, "exact_membership"


def ensure_named_region(assembly, selection, replace=False):
    """Reuse an exact match or create a missing region.

    Existing mismatches fail closed unless replace=True. Replacement is
    deliberately explicit because deleting a region can invalidate loads,
    BCs, interactions, or sections that reference it.
    """
    if selection.region_kind == "temporary":
        raise ValueError("temporary selections have no lifecycle")

    existing = inspect_existing(assembly, selection)
    if existing is not None:
        ok, reason = validate_existing(assembly, selection)
        if ok:
            return existing, "reused"
        if not replace:
            raise ValueError("existing region mismatch: " + reason)

        if selection.region_kind == "set":
            assembly.deleteSets((selection.name,))
        else:
            assembly.deleteSurfaces((selection.name,))

    from .region_binding import create_set, create_surface
    if selection.region_kind == "set":
        return create_set(assembly, selection), "created"
    return create_surface(assembly, selection), "created"
