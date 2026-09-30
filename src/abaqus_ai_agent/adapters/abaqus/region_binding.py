"""Abaqus/CAE materialization of grounded geometry selections.

This module is deliberately thin: policy and contracts live outside the
Abaqus adapter; this file only turns validated geometric locators into native
Set/Surface objects.
"""


def _find(instance, entity_type, point):
    repositories = {
        "Face": instance.faces,
        "Edge": instance.edges,
        "Vertex": instance.vertices,
    }
    try:
        repository = repositories[entity_type]
    except KeyError:
        raise ValueError("unsupported geometry entity type")
    return repository.findAt((tuple(point),))


def _targets(selection):
    for target in selection.targets:
        instance_name = target.get("instance")
        point = target.get("point")
        if not instance_name or not point:
            raise ValueError("selection target requires instance and point")
        yield instance_name, point


def validate_selection(assembly, selection):
    """Resolve every target once and fail closed on any locator failure."""
    resolved = []
    for instance_name, point in _targets(selection):
        instance = assembly.instances[instance_name]
        entity = _find(instance, selection.entity_type, point)
        resolved.append((instance_name, entity))
    if not resolved:
        raise ValueError("empty geometry selection")
    return tuple(resolved)


def materialize_selection(assembly, selection):
    """Materialize a GeometrySelection as a temporary native Abaqus region.

    A temporary region is returned as a tuple of native geometry objects.
    Named Set/Surface creation is handled separately to make mutation explicit.
    """
    grouped = {}
    for instance_name, point in _targets(selection):
        instance = assembly.instances[instance_name]
        grouped.setdefault(instance_name, []).append(_find(
            instance, selection.entity_type, point))
    return tuple(entity for entities in grouped.values() for entity in entities)


def create_set(assembly, selection):
    """Create an assembly-level geometry Set from a grounded selection."""
    if selection.region_kind != "set":
        raise ValueError("selection region_kind must be 'set'")
    entities = materialize_selection(assembly, selection)
    kwargs = {selection.entity_type.lower() + "s": entities}
    return assembly.Set(name=selection.name, **kwargs)


def create_surface(assembly, selection):
    """Create an assembly Surface from grounded Face/Edge targets."""
    if selection.region_kind != "surface":
        raise ValueError("selection region_kind must be 'surface'")
    if selection.surface_side not in ("side1", "side2"):
        raise ValueError("surface_side is required for surfaces")
    entities = materialize_selection(assembly, selection)
    if selection.entity_type == "Face":
        key = selection.surface_side + "Faces"
    elif selection.entity_type == "Edge":
        key = selection.surface_side + "Edges"
    else:
        raise ValueError("surfaces require Face or Edge targets")
    return assembly.Surface(name=selection.name, **{key: entities})
