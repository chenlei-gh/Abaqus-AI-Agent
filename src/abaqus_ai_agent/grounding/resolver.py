from ..contracts.geometry import ImagePoint, GroundingResult
from .matching import candidates_from_projected_faces
from .policy import resolve


def resolve_image_point(intent_id, image_point, probe, radius=0.12, visual_scores=None, topology_scores=None):
    """Resolve an annotated viewport point against a live Abaqus probe.

    This function is deterministic and evidence-only. It does not call a
    vision model and it never fabricates a candidate when no geometry projects
    near the annotation.
    """
    target = image_point if isinstance(image_point, ImagePoint) else ImagePoint(*image_point)
    candidates = candidates_from_projected_faces(
        target, probe.get("faces", []), radius=radius,
        visual_scores=visual_scores, topology_scores=topology_scores,
    )
    return resolve(intent_id, candidates)
