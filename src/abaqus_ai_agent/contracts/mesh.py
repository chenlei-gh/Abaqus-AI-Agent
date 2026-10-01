"""Executor-neutral mesh contracts and normalization."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class LocalSeed:
    region_expression: str
    size: Optional[float] = None
    number: Optional[int] = None
    constraint: Optional[str] = None

    def __post_init__(self):
        if not self.region_expression:
            raise ValueError("region_expression is required")
        if (self.size is None) == (self.number is None):
            raise ValueError("exactly one of size or number is required")
        if self.size is not None and self.size <= 0:
            raise ValueError("seed size must be positive")
        if self.number is not None and self.number < 1:
            raise ValueError("seed number must be positive")


@dataclass(frozen=True)
class MeshSpecification:
    part: str
    global_size: float
    deviation_factor: float = 0.1
    min_size_factor: float = 0.1
    local_seeds: Tuple[LocalSeed, ...] = field(default_factory=tuple)
    bias_seeds: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    sweep_paths: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    controls: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    element_types: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    generate: bool = True

    def __post_init__(self):
        if not self.part:
            raise ValueError("part is required")
        if self.global_size <= 0:
            raise ValueError("global_size must be positive")
        if not 0 <= self.deviation_factor <= 1:
            raise ValueError("deviation_factor must be between 0 and 1")
        if not 0 < self.min_size_factor <= 1:
            raise ValueError("min_size_factor must be in (0, 1]")
