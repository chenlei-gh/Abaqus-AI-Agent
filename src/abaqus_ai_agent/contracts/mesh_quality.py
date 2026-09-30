"""Executor-neutral mesh inspection and quality result contracts."""

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class MeshSummary:
    part: str
    node_count: int
    element_count: int
    element_types: Tuple[str, ...] = field(default_factory=tuple)
    quality_status: str = "unknown"
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.node_count < 0 or self.element_count < 0:
            raise ValueError("mesh counts cannot be negative")
        if self.quality_status not in ("unknown", "pass", "warning", "fail"):
            raise ValueError("invalid quality_status")
