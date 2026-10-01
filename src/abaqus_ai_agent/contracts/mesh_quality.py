"""Executor-neutral mesh inspection and quality result contracts."""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


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


@dataclass(frozen=True)
class MeshQualityPolicy:
    max_aspect_ratio: Optional[float] = None
    max_skew: Optional[float] = None
    min_jacobian: Optional[float] = None
    min_angle: Optional[float] = None
    max_angle: Optional[float] = None
    max_angular_deviation: Optional[float] = None
    max_geometric_deviation_factor: Optional[float] = None
    analysis_checks: bool = True

    def __post_init__(self):
        if self.max_aspect_ratio is not None and self.max_aspect_ratio <= 0:
            raise ValueError("max_aspect_ratio must be positive")
        for name in (
            "max_skew",
            "min_jacobian",
            "min_angle",
            "max_angle",
            "max_angular_deviation",
            "max_geometric_deviation_factor",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError("%s cannot be negative" % name)
        if self.max_geometric_deviation_factor is not None and self.max_geometric_deviation_factor == 0:
            raise ValueError("max_geometric_deviation_factor must be positive")


@dataclass(frozen=True)
class MeshQualityResult:
    status: str
    metrics: Dict[str, float] = field(default_factory=dict)
    violations: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    evidence: Tuple[str, ...] = field(default_factory=tuple)
    source: str = "unsupported"
    failed_element_count: int = 0
    warning_element_count: int = 0
    quality_scope: Optional[str] = None

    def __post_init__(self):
        if self.status not in ("unknown", "pass", "warning", "fail"):
            raise ValueError("invalid status")
        if any(not isinstance(k, str) or not isinstance(v, (int, float)) for k, v in self.metrics.items()):
            raise ValueError("metrics must map strings to numeric values")
        if self.failed_element_count < 0 or self.warning_element_count < 0:
            raise ValueError("element counts cannot be negative")

    @property
    def passed(self):
        return self.status == "pass"
