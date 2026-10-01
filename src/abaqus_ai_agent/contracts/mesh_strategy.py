"""Geometry-aware mesh strategy contracts."""

from dataclasses import dataclass, field
from typing import Tuple

@dataclass(frozen=True)
class MeshRefinementRequest:
    target: str
    entity_type: str
    target_size: float
    reason: str
    priority: str = "normal"
    source: str = "user"
    method: str = "local_seed"
    transition: str = "smooth"
    requires_partition: bool = False
    evidence: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if not self.target or self.target_size <= 0:
            raise ValueError("target and positive target_size are required")
        if self.entity_type not in ("Edge", "Face", "Cell", "Vertex", "Region"):
            raise ValueError("unsupported entity_type")
        if self.priority not in ("low", "normal", "high", "critical"):
            raise ValueError("unsupported priority")
        if self.method not in ("local_seed", "partition_then_seed", "preserve", "virtual_topology_review"):
            raise ValueError("unsupported refinement method")
        if self.transition not in ("smooth", "controlled", "none"):
            raise ValueError("unsupported transition")

@dataclass(frozen=True)
class GeometryMeshPlan:
    global_size: float
    refinements: Tuple[MeshRefinementRequest, ...] = field(default_factory=tuple)
    feature_reviews: Tuple[MeshRefinementRequest, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    evidence: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.global_size <= 0:
            raise ValueError("global_size must be positive")

    @property
    def requires_partition(self):
        return any(x.requires_partition for x in self.refinements)

    @property
    def has_local_refinement(self):
        return bool(self.refinements)
