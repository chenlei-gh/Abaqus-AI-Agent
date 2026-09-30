import math
from typing import Iterable, Optional, Tuple

from ..contracts.geometry import GeometryCandidate, ImagePoint


def screen_distance_score(
    target: ImagePoint,
    candidate: Optional[Tuple[float, float]],
    radius: float = 0.15,
) -> float:
    """Convert normalized screen distance into a [0, 1] evidence score."""
    if candidate is None:
        return 0.0
    if radius <= 0.0:
        raise ValueError("radius must be positive")
    dx = candidate[0] - target.x
    dy = candidate[1] - target.y
    distance = math.sqrt(dx * dx + dy * dy)
    return max(0.0, min(1.0, 1.0 - distance / radius))


def candidates_from_projected_faces(
    target: ImagePoint,
    faces: Iterable[dict],
    radius: float = 0.15,
    visual_scores: Optional[dict] = None,
    topology_scores: Optional[dict] = None,
):
    """Build Face candidates from read-only Abaqus probe output.

    visual_scores and topology_scores are optional external evidence.
    Missing values intentionally default to zero; the resolver must not invent
    evidence that has not been measured.
    """
    visual_scores = visual_scores or {}
    topology_scores = topology_scores or {}
    result = []

    for face in faces:
        key = (face.get("instance"), face.get("index"))
        distance = screen_distance_score(target, face.get("screen"), radius)
        result.append(
            GeometryCandidate(
                entity_type="Face",
                name=face.get("instance"),
                index=face.get("index"),
                centroid=tuple(face["centroid"]) if face.get("centroid") else None,
                normal=tuple(face["normal"]) if face.get("normal") else None,
                area=face.get("size"),
                distance_score=distance,
                visual_score=float(visual_scores.get(key, 0.0)),
                topology_score=float(topology_scores.get(key, 0.0)),
            )
        )
    return result
