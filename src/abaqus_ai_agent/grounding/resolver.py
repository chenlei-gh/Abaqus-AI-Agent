from ..contracts.geometry import ImagePoint, GroundingResult
from .matching import candidates_from_projected_faces
from .policy import resolve


def target_reference(candidate):
    """Convert a selected candidate into an executor-neutral locator.

    Abaqus warns that integer geometry ids are not stable. The geometric point
    is therefore the primary locator; index/entity_key are diagnostics only.
    """
    if candidate is None or candidate.centroid is None:
        raise ValueError("candidate with geometric locator is required")
    return {
        "instance": candidate.name,
        "entity_type": candidate.entity_type,
        "entity_key": candidate.entity_key,
        "index": candidate.index,
        "point": tuple(candidate.centroid),
        "grounding_score": candidate.total_score,
        "grounding_evidence": {
            "distance": candidate.distance_score,
            "visual": candidate.visual_score,
            "topology": candidate.topology_score,
            "camera_depth": candidate.camera_depth,
            "facing": candidate.facing_score,
        },
    }


def region_expression(target, variable="instance"):
    """Build an Abaqus findAt expression from a grounded geometric point."""
    entity_type = target.get("entity_type")
    point = target.get("point")
    if not target.get("instance") or not point or entity_type not in ("Face", "Edge", "Vertex"):
        raise ValueError("invalid geometric target")
    point_expr = repr((tuple(point),))
    repository = {"Face": "faces", "Edge": "edges", "Vertex": "vertices"}[entity_type]
    return "%s.%s.findAt(%s)" % (variable, repository, point_expr)


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
