from ..contracts.geometry import ImagePoint, GroundingResult
from .matching import candidates_from_projected_faces
from .policy import resolve


def resolve_image_point(intent_id, image_point, probe, radius=0.12,
                       visual_scores=None, topology_scores=None):
    """Resolve an annotated viewport point against live Abaqus geometry.

    The probe may contain faces, edges, and vertices. Resolution is deterministic
    and returns evidence for a human/agent confirmation gate; it is not proof.
    """
    target = image_point if isinstance(image_point, ImagePoint) else ImagePoint(*image_point)
    geometry = list(probe.get("faces", []))
    geometry.extend(probe.get("edges", []))
    geometry.extend(probe.get("vertices", []))
    candidates = candidates_from_projected_faces(
        target, geometry, radius=radius,
        visual_scores=visual_scores, topology_scores=topology_scores,
    )
    return resolve(intent_id, candidates)
