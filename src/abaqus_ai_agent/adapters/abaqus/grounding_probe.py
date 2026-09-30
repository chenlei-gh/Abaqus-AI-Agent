# Read-only Abaqus/CAE experiment for model-to-image grounding.
# Call run(session) from the Abaqus Python console.
#
# Important coordinate rule:
#   Geometry read from a PartInstance (instance.faces / instance.vertices) is
#   treated as assembly-space geometry. We deliberately do not reconstruct the
#   instance transform from getRotation()/getTranslation(): Abaqus exposes
#   those operations, but getPosition() only prints state and the documented
#   API does not expose a single ready-made 4x4 transform. Using the actual
#   instance-owned geometry avoids inventing transform semantics.
#
# The probe also records a lightweight part-vs-instance coordinate diagnostic
# so a real Abaqus session can verify this assumption on the target release.

try:
    from abaqusConstants import PNG, PARALLEL
except ImportError:
    PNG, PARALLEL = "PNG", "PARALLEL"


def _norm(v):
    from math import sqrt
    n = sqrt(sum(x * x for x in v))
    if n == 0.0:
        raise ValueError("zero-length vector")
    return tuple(x / n for x in v)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
            a[0]*b[1]-a[1]*b[0])


def _camera_basis(view):
    forward = _norm(tuple(t-p for p, t in zip(view.cameraPosition, view.cameraTarget)))
    up = _norm(tuple(view.cameraUpVector))
    right = _norm(_cross(forward, up))
    up = _norm(_cross(right, forward))
    return forward, right, up


def _project(point, view):
    if getattr(view, "projection", None) != PARALLEL:
        return None
    forward, right, up = _camera_basis(view)
    delta = tuple(p-t for p, t in zip(point, view.cameraTarget))
    sx = 0.5 + _dot(delta, right) / float(view.width) + float(view.viewOffsetX)
    sy_model = 0.5 + _dot(delta, up) / float(view.height) + float(view.viewOffsetY)
    # Keep projected points even when outside the viewport. A partially visible
    # face must not lose its polygon just because a vertex is off-screen.
    sy = 1.0 - sy_model
    return (sx, sy)


def _project_vertices(entity, owner, view):
    points = []
    try:
        vertex_indices = entity.getVertices()
    except Exception:
        return points
    try:
        vertices = owner.vertices
    except Exception:
        return points
    for vertex_index in vertex_indices:
        try:
            vertex_point = tuple(float(x) for x in vertices[vertex_index].pointOn[0][:3])
        except Exception:
            continue
        projected = _project(vertex_point, view)
        if projected is not None:
            points.append(projected)
    return points


def _entity_data(entity, index, view=None, owner=None, entity_type="Face"):
    centroid = None
    try:
        centroid = tuple(float(x) for x in entity.getCentroid()[:3])
    except Exception:
        try:
            centroid = tuple(float(x) for x in entity.pointOn[0][:3])
        except Exception:
            pass
    normal = None
    if centroid is not None:
        try:
            normal = tuple(float(x) for x in entity.getNormal(centroid)[:3])
        except Exception:
            pass
    size = None
    try:
        size = float(entity.getSize())
    except Exception:
        pass
    item = {"index": index, "entity_type": entity_type, "centroid": centroid, "normal": normal, "size": size}
    if centroid is not None:
        try:
            forward, _, _ = _camera_basis(view)
            camera_delta = tuple(p-c for p, c in zip(centroid, view.cameraPosition))
            item["camera_depth"] = _dot(camera_delta, forward)
            item["facing_score"] = (max(0.0, min(1.0, _dot(_norm(normal),
                                      tuple(-x for x in forward))))
                                    if normal is not None else None)
        except Exception:
            item["camera_depth"] = None
            item["facing_score"] = None
    projected = (_project_vertices(entity, owner, view)
                  if view is not None and owner is not None else [])
    item["screen_polygon"] = projected if entity_type == "Face" else []
    item["screen_path"] = projected if entity_type == "Edge" else []
    return item


def _coordinate_diagnostic(instance):
    """Compare one instance face point with its source-part face point.

    This is diagnostic only. It does not infer a transform or alter coordinates.
    """
    result = {"checked": False, "delta": None, "same_coordinates": None}
    try:
        if len(instance.faces) == 0 or len(instance.part.faces) == 0:
            return result
        a = tuple(float(x) for x in instance.faces[0].pointOn[0][:3])
        p = tuple(float(x) for x in instance.part.faces[0].pointOn[0][:3])
        delta = tuple(a[i] - p[i] for i in range(3))
        result["checked"] = True
        result["delta"] = delta
        result["same_coordinates"] = max(abs(x) for x in delta) <= 1.0e-9
    except Exception:
        return result
    return result


def _instance_state(instance):
    result = {"translation": None, "rotation": None, "position_available": False}
    try:
        result["translation"] = tuple(float(x) for x in instance.getTranslation())
    except Exception:
        pass
    try:
        result["rotation"] = tuple(instance.getRotation())
    except Exception:
        pass
    # getPosition() is documented as printing rather than returning the state,
    # so it is intentionally not called from this read-only data path.
    result["position_available"] = (
        result["translation"] is not None or result["rotation"] is not None
    )
    return result


def collect(session):
    viewport = session.viewports[session.currentViewportName]
    view = viewport.view
    displayed = viewport.displayedObject
    result = {
        "viewport": viewport.name,
        "projection": str(view.projection),
        "coordinate_space": "assembly" if getattr(displayed, "instances", None) is not None else "part",
        "edges": [], "vertices": [],
        "view": {
            "camera_position": tuple(view.cameraPosition),
            "camera_target": tuple(view.cameraTarget),
            "up_vector": tuple(view.cameraUpVector),
            "width": float(view.width), "height": float(view.height),
            "view_offset_x": float(view.viewOffsetX),
            "view_offset_y": float(view.viewOffsetY),
        }, "faces": [], "instances": {}}
    if displayed is None:
        return result
    instances = getattr(displayed, "instances", None)
    if instances is not None:
        for name in instances.keys():
            instance = instances[name]
            result["instances"][name] = {
                "coordinate_diagnostic": _coordinate_diagnostic(instance),
                "state": _instance_state(instance),
            }
            for index, face in enumerate(instance.faces):
                item = _entity_data(face, index, view, instance, "Face")
                item["instance"] = name
                item["entity_key"] = "%s:Face:%d" % (name, index)
                item["screen"] = _project(item["centroid"], view) if item["centroid"] else None
                result["faces"].append(item)
            for index, edge in enumerate(instance.edges):
                item = _entity_data(edge, index, view, instance, "Edge")
                item["instance"] = name
                item["entity_key"] = "%s:Edge:%d" % (name, index)
                item["screen"] = _project(item["centroid"], view) if item["centroid"] else None
                result.setdefault("edges", []).append(item)
            for index, vertex in enumerate(instance.vertices):
                item = _entity_data(vertex, index, view, instance, "Vertex")
                item["instance"] = name
                item["entity_key"] = "%s:Vertex:%d" % (name, index)
                point = item["centroid"]
                item["screen"] = _project(point, view) if point else None
                result.setdefault("vertices", []).append(item)
    else:
        for index, face in enumerate(displayed.faces):
            item = _entity_data(face, index, view, displayed, "Face")
            item["instance"] = None
            item["entity_key"] = "Part:Face:%d" % index
            item["screen"] = _project(item["centroid"], view) if item["centroid"] else None
            result["faces"].append(item)
    return result


def run(session, output_png="abaqus_grounding_probe.png"):
    viewport = session.viewports[session.currentViewportName]
    data = collect(session)
    session.printToFile(fileName=output_png, format=PNG, canvasObjects=(viewport,))
    data["snapshot_file"] = output_png
    return data
