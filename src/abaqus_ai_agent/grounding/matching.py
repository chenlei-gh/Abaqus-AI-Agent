import math
from ..contracts.geometry import GeometryCandidate, ImagePoint


def screen_distance_score(target, candidate, radius=0.15):
    if candidate is None:
        return 0.0
    if radius <= 0.0:
        raise ValueError("radius must be positive")
    dx, dy = candidate[0] - target.x, candidate[1] - target.y
    return max(0.0, min(1.0, 1.0 - math.sqrt(dx*dx + dy*dy) / radius))


def _point_segment_distance(point, a, b):
    px, py = point.x, point.y
    ax, ay = a
    bx, by = b
    dx, dy = bx-ax, by-ay
    length2 = dx*dx + dy*dy
    if length2 <= 1.0e-30:
        return math.hypot(px-ax, py-ay)
    t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / length2))
    return math.hypot(px-(ax+t*dx), py-(ay+t*dy))


def path_distance_score(target, path, radius=0.15):
    if not path:
        return 0.0
    if len(path) == 1:
        return screen_distance_score(target, path[0], radius)
    distance = min(_point_segment_distance(target, path[i], path[i+1])
                   for i in range(len(path)-1))
    return max(0.0, min(1.0, 1.0-distance/radius))


def point_in_polygon(point, polygon):
    if not polygon or len(polygon) < 3:
        return False
    x, y = point.x, point.y
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y) and
                      x < (xj-xi) * (y-yi) / ((yj-yi) or 1e-30) + xi)
        if intersects:
            inside = not inside
        j = i
    return inside


def polygon_distance_score(target, polygon, radius=0.15):
    if not polygon:
        return 0.0
    if point_in_polygon(target, polygon):
        return 1.0
    return screen_distance_score(target, polygon_centroid(polygon), radius)


def polygon_centroid(polygon):
    return (sum(p[0] for p in polygon) / float(len(polygon)),
            sum(p[1] for p in polygon) / float(len(polygon)))


def _candidate(face, target, radius, visual_scores, topology_scores):
    entity_type = face.get("entity_type", "Face")
    key = (face.get("instance"), entity_type, face.get("index"))
    center = face.get("screen")
    polygon = tuple(tuple(p) for p in (face.get("screen_polygon") or ()))
    path = tuple(tuple(p) for p in (face.get("screen_path") or ()))
    centroid_score = screen_distance_score(target, center, radius)
    if entity_type == "Edge":
        region_score = path_distance_score(target, path, radius)
    elif entity_type == "Vertex":
        region_score = centroid_score
    else:
        region_score = polygon_distance_score(target, polygon, radius)
    distance = max(centroid_score, region_score)
    return GeometryCandidate(
        entity_type=entity_type, name=face.get("instance"),
        index=face.get("index"),
        centroid=tuple(face["centroid"]) if face.get("centroid") else None,
        normal=tuple(face["normal"]) if face.get("normal") else None,
        area=face.get("size"), distance_score=distance,
        visual_score=float(visual_scores.get(key, visual_scores.get((face.get("instance"), face.get("index")), 0.0))),
        topology_score=float(topology_scores.get(key, topology_scores.get((face.get("instance"), face.get("index")), 0.0))),
        screen_polygon=polygon or None,
        screen_path=path or None,
        entity_key=face.get("entity_key"),
        camera_depth=(float(face["camera_depth"])
                      if face.get("camera_depth") is not None else None),
        facing_score=(float(face["facing_score"])
                      if face.get("facing_score") is not None else None))


def candidates_from_projected_faces(target, faces, radius=0.15,
                                    visual_scores=None, topology_scores=None):
    visual_scores, topology_scores = visual_scores or {}, topology_scores or {}
    return [_candidate(face, target, radius, visual_scores, topology_scores)
            for face in faces]
