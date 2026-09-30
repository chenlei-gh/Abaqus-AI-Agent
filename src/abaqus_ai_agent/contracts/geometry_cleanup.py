"""Contracts for conservative geometry preparation before meshing."""

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class GeometryIssue:
    entity_type: str
    index: Optional[int]
    issue_type: str
    severity: str
    metric: Optional[float] = None
    threshold: Optional[float] = None
    locator: Optional[Tuple[float, float, float]] = None
    recommendation: Optional[str] = None

    def __post_init__(self):
        if self.entity_type not in ("Face", "Edge", "Vertex", "Part"):
            raise ValueError("unsupported entity_type")
        if self.severity not in ("info", "warning", "error"):
            raise ValueError("invalid severity")
        if not self.issue_type:
            raise ValueError("issue_type is required")


@dataclass(frozen=True)
class GeometryInspection:
    part: str
    issues: Tuple[GeometryIssue, ...] = field(default_factory=tuple)
    valid_geometry: Optional[bool] = None
    entity_counts: Tuple[Tuple[str, int], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GeometryCleanupPolicy:
    part: str
    min_edge_length: Optional[float] = None
    min_face_size: Optional[float] = None
    inspect_geometry: bool = True
    allow_virtual_topology: bool = False
    allow_repair: bool = False

    def __post_init__(self):
        if not self.part:
            raise ValueError("part is required")
        for name in ("min_edge_length", "min_face_size"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError("%s must be positive" % name)


@dataclass(frozen=True)
class GeometryCleanupAction:
    operation: str
    part: str
    region_expression: Optional[str] = None
    parameters: dict = field(default_factory=dict)
    requires_confirmation: bool = True

    def __post_init__(self):
        if self.operation not in (
            "inspect_geometry", "ignore_entity", "restore_entity",
            "repair_geometry", "remove_redundant_entities"
        ):
            raise ValueError("unsupported geometry cleanup operation")
        if not self.part:
            raise ValueError("part is required")
        if self.operation in ("ignore_entity", "restore_entity") and not self.region_expression:
            raise ValueError("region_expression is required")
