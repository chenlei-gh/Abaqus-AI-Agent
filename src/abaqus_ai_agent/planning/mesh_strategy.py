"""Deterministic geometry-to-mesh strategy planning."""
from ..contracts.mesh_strategy import GeometryMeshPlan, MeshRefinementRequest

def plan_geometry_mesh(geometry, global_size, critical_regions=(), refinement_factor=0.5, small_feature_ratio=0.75):
    if global_size <= 0:
        raise ValueError("global_size must be positive")
    if not 0 < refinement_factor <= 1:
        raise ValueError("refinement_factor must be in (0, 1]")
    if not 0 < small_feature_ratio <= 1:
        raise ValueError("small_feature_ratio must be in (0, 1]")
    refinements, reviews, warnings = [], [], []
    evidence = ["geometry_read_only"]
    for item in critical_regions or ():
        target = item.get("target") or item.get("region_expression")
        if not target:
            warnings.append("critical_region_missing_target")
            continue
        entity_type = item.get("entity_type", "Region")
        size = item.get("target_size", global_size * refinement_factor)
        needs_partition = entity_type not in ("Edge", "Region")
        method = "local_seed" if entity_type in ("Edge", "Region") else "partition_then_seed"
        refinements.append(MeshRefinementRequest(
            str(target), entity_type, float(size),
            item.get("reason", "engineering_critical_region"),
            item.get("priority", "high"), item.get("source", "engineering_intent"),
            method, item.get("transition", "smooth"), needs_partition,
            tuple(item.get("evidence", ())),
        ))
    for entity_type in ("Edge", "Face"):
        for item in (geometry or {}).get(entity_type.lower() + "s", ()):
            size, index = item.get("size"), item.get("index")
            if size is None or index is None or size <= 0 or size >= global_size * small_feature_ratio:
                continue
            reviews.append(MeshRefinementRequest(
                "%s[%s]" % (entity_type, index), entity_type,
                max(min(size / 2.0, global_size), global_size * 0.05),
                "small_geometric_feature", "normal", "geometry_inspection",
                "virtual_topology_review", "controlled", False,
                ("feature_size:%g" % size, "global_size:%g" % global_size),
            ))
    if reviews:
        warnings.append("small_geometry_requires_feature_classification_before_mutation")
        evidence.append("small_feature_screening")
    if refinements:
        evidence.append("engineering_region_local_refinement")
    if any(x.requires_partition for x in refinements):
        evidence.append("partition_may_be_required_for_region_refinement")
    return GeometryMeshPlan(float(global_size), tuple(refinements), tuple(reviews), tuple(warnings), tuple(evidence))
