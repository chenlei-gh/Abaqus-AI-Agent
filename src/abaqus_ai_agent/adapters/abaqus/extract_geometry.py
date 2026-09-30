# Abaqus/CAE-side script. Keep this file compatible with legacy Abaqus Python.
# It emits plain Python data structures suitable for JSON serialization by the
# surrounding MCP bridge.


def _tuple3(value):
    if value is None:
        return None
    return tuple(float(x) for x in value[:3])


def _face_descriptor(face, index):
    point_on = None
    try:
        if face.pointOn:
            point_on = _tuple3(face.pointOn[0])
    except Exception:
        pass
    centroid = None
    try:
        centroid = _tuple3(face.getCentroid())
    except Exception:
        centroid = point_on
    normal = None
    try:
        normal = _tuple3(face.getNormal())
    except Exception:
        if point_on is not None:
            try:
                normal = _tuple3(face.getNormal(point_on))
            except Exception:
                pass
    area = None
    try:
        area = float(face.getSize())
    except Exception:
        pass
    return {
        'entity_type': 'Face', 'index': int(index),
        'point_on': point_on, 'centroid': centroid,
        'normal': normal, 'size': area,
    }


def _edge_descriptor(edge, index):
    point_on = None
    try:
        if edge.pointOn:
            point_on = _tuple3(edge.pointOn[0])
    except Exception:
        pass
    size = None
    try:
        size = float(edge.getSize())
    except Exception:
        pass
    return {
        'entity_type': 'Edge', 'index': int(index),
        'point_on': point_on, 'centroid': point_on,
        'normal': None, 'size': size,
    }


def extract_geometry(part_or_instance, include_edges=True, include_faces=True):
    """Extract stable, JSON-friendly descriptors without modifying the model."""
    result = {'faces': [], 'edges': []}
    if include_faces:
        for i, face in enumerate(part_or_instance.faces):
            result['faces'].append(_face_descriptor(face, i))
    if include_edges:
        for i, edge in enumerate(part_or_instance.edges):
            result['edges'].append(_edge_descriptor(edge, i))
    return result


def extract_viewport(viewport):
    """Capture the active View state needed by the agent-side projector."""
    view = viewport.view
    return {
        'viewport_id': viewport.name,
        'projection_type': str(view.projection),
        'camera_position': _tuple3(view.cameraPosition),
        'camera_target': _tuple3(view.cameraTarget),
        'up_vector': _tuple3(view.cameraUpVector),
        'width': float(view.width),
        'height': float(view.height),
        'view_offset_x': float(view.viewOffsetX),
        'view_offset_y': float(view.viewOffsetY),
        'displayed_object_screen_width': float(view.displayedObjectScreenWidth),
        'displayed_object_screen_height': float(view.displayedObjectScreenHeight),
    }
