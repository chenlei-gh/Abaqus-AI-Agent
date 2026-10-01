"""Conservative geometry feature characterization contracts."""

from dataclasses import dataclass, field
from typing import Optional, Tuple

FEATURE_KINDS = (
    "hole_like", "fillet_like", "thin_region", "sharp_corner",
    "small_detail", "load_relevant", "contact_relevant", "unknown",
)


@dataclass(frozen=True)
class GeometryFeatureEvidence:
    source: str
    value: Optional[float] = None
    text: Optional[str] = None

    def __post_init__(self):
        if not self.source:
            raise ValueError("source is required")


@dataclass(frozen=True)
class GeometryFeature:
    feature_kind: str
    entity_type: str
    target: str
    size: Optional[float] = None
    relevance: str = "unknown"
    confidence: float = 0.0
    evidence: Tuple[GeometryFeatureEvidence, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.feature_kind not in FEATURE_KINDS:
            raise ValueError("unsupported feature_kind")
        if self.entity_type not in ("Face", "Edge", "Vertex", "Region"):
            raise ValueError("unsupported entity_type")
        if not self.target:
            raise ValueError("target is required")
        if self.size is not None and self.size <= 0:
            raise ValueError("size must be positive")
        if self.relevance not in ("unknown", "low", "normal", "high", "critical"):
            raise ValueError("invalid relevance")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


def characterize_geometry(geometry, critical_regions=(), small_feature_ratio=0.75):
    """Use only explicit geometry descriptors; do not invent topology."""
    if not 0 < small_feature_ratio <= 1:
        raise ValueError("small_feature_ratio must be in (0, 1]")
    critical = {}
    for item in critical_regions or ():
        target = item.get("target") or item.get("region_expression")
        if target:
            critical[str(target)] = item

    features = []
    geometry = geometry or {}
    for entity_type, key in (("Edge", "edges"), ("Face", "faces")):
        for item in geometry.get(key, ()):
            index = item.get("index")
            size = item.get("size")
            if index is None:
                continue
            target = "%s[%s]" % (entity_type, index)
            region = critical.get(target)
            relevance = region.get("priority", "normal") if region else "unknown"
            if relevance not in ("unknown", "low", "normal", "high", "critical"):
                relevance = "unknown"
            evidence = []
            if size is not None and size > 0:
                evidence.append(GeometryFeatureEvidence("geometry_size", float(size)))
            if region:
                evidence.append(
                    GeometryFeatureEvidence(
                        "engineering_region",
                        text=region.get("reason", "critical_region"),
                    )
                )
            kind = "unknown"
            confidence = 1.0 if region else 0.0
            features.append(
                GeometryFeature(
                    feature_kind=kind,
                    entity_type=entity_type,
                    target=target,
                    size=float(size) if size is not None and size > 0 else None,
                    relevance=relevance,
                    confidence=confidence,
                    evidence=tuple(evidence),
                )
            )
    return tuple(features)
