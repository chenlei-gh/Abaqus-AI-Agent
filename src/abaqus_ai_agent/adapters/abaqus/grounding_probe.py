# Read-only Abaqus/CAE experiment for model-to-image grounding.
# Call run(session) from the Abaqus Python console.

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


def _project(point, view):
    if getattr(view, "projection", None) != PARALLEL:
        return None
    forward = _norm(tuple(t-p for p, t in zip(view.cameraPosition, view.cameraTarget)))
    up = _norm(tuple(view.cameraUpVector))
    right = _norm(_cross(forward, up))
    up = _norm(_cross(right, forward))
    delta = tuple(p-t for p, t in zip(point, view.cameraTarget))
    sx = 0.5 + _dot(delta, right) / float(view.width) + float(view.viewOffsetX)
    sy_model = 0.5 + _dot(delta, up) / float(view.height) + float(view.viewOffsetY)
    sy = 1.0 - sy_model
    if not (0.0 <= sx <= 1.0 and 0.0 <= sy <= 1.0):
        return None
    return (sx, sy)


def _project_vertices(face, owner, view):
    points = []
    try:
        vertex_indices = face.getVertices()
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


def _face_data(face, index, view=None, owner=None):
    centroid = None
    try:
        centroid = tuple(float(x) for x in face.getCentroid()[:3])
    except Exception:
        try:
            centroid = tuple(float(x) for x in face.pointOn[0][:3])
        except Exception:
            pass
    normal = None
    if centroid is not None:
        try:
            normal = tuple(float(x) for x in face.getNormal(centroid)[:3])
        except Exception:
            pass
    size = None
    try:
        size = float(face.getSize())
    except Exception:
        pass
    item = {"index": index, "centroid": centroid, "normal": normal, "size": size}
    item["screen_polygon"] = (_project_vertices(face, owner, view)
                              if view is not None and owner is not None else [])
    return item


def collect(session):
    viewport = session.viewports[session.currentViewportName]
    view = viewport.view
    displayed = viewport.displayedObject
    result = {
        "viewport": viewport.name,
        "projection": str(view.projection),
        "view": {
            "camera_position": tuple(view.cameraPosition),
            "camera_target": tuple(view.cameraTarget),
            "up_vector": tuple(view.cameraUpVector),
            "width": float(view.width), "height": float(view.height),
            "view_offset_x": float(view.viewOffsetX),
            "view_offset_y": float(view.viewOffsetY),
        }, "faces": []}
    if displayed is None:
        return result
    instances = getattr(displayed, "instances", None)
    if instances is not None:
        for name in instances.keys():
            instance = instances[name]
            for index, face in enumerate(instance.faces):
                item = _face_data(face, index, view, instance)
                item["instance"] = name
                item["screen"] = _project(item["centroid"], view) if item["centroid"] else None
                result["faces"].append(item)
    else:
        for index, face in enumerate(displayed.faces):
            item = _face_data(face, index, view, displayed)
            item["instance"] = None
            item["screen"] = _project(item["centroid"], view) if item["centroid"] else None
            result["faces"].append(item)
    return result


def run(session, output_png="abaqus_grounding_probe.png"):
    viewport = session.viewports[session.currentViewportName]
    data = collect(session)
    session.printToFile(fileName=output_png, format=PNG, canvasObjects=(viewport,))
    data["snapshot_file"] = output_png
    return data
