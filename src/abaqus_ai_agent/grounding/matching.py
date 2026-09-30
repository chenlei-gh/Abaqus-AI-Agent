import math
from typing import Iterable, Optional, Tuple

from ..contracts.geometry import GeometryCandidate, ImagePoint


def screen_distance_score(target, candidate, radius=0.15):
    if candidate is None:
        return 0.0
    if radius <= 0.0:
        raise ValueError("radius must be positive")
    dx, dy = candidate[0] - target.x, candidate[1] - target.y
    return max(0.0, min(1.0, 1.0 - math.sqrt(dx*dx + dy*dy) / radius))


def point_in_polygon(point, polygon):
    """Ray-casting test for normalized projected face boundary."""
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


def candidates_from_projected_faces(target, faces, radius=0.15,
                                    visual_scores=None, topology_scores=None):
    visual_scores, topology_scores = visual_scores or {}, topology_scores or {}
    result = []
    for face in faces:
        key = (face.get("instance"), face.get("index"))
        center = face.get("screen")
        polygon = tuple(tuple(p) for p in (face.get("screen_polygon") or ()))
        centroid_score = screen_distance_score(target, center, radius)
        region_score = polygon_distance_score(target, polygon, radius)
        # Prefer actual projected-face containment over centroid proximity.
        distance = max(centroid_score, region_score)
        result.append(GeometryCandidate(
            entity_type="Face", name=face.get("instance"),
            index=face.get("index"),
            centroid=tuple(face["centroid"]) if face.get("centroid") else None,
            normal=tuple(face["normal"]) if face.get("normal") else None,
            area=face.get("size"), distance_score=distance,
            visual_score=float(visual_scores.get(key, 0.0)),
            topology_score=float(topology_scores.get(key, 0.0)),
            screen_polygon=polygon or None))
    return result
