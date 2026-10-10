"""Executor-neutral mesh contracts and normalization."""

import math
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
        if self.size is not None:
            if isinstance(self.size, bool) or not isinstance(self.size, (int, float)) or self.size <= 0 or not math.isfinite(self.size):
                raise ValueError(f"seed size must be a positive finite number, got {self.size!r}")
        if self.number is not None:
            if isinstance(self.number, bool) or not isinstance(self.number, int) or self.number < 1:
                raise ValueError(f"seed number must be an integer >= 1, got {self.number!r}")
        if self.constraint is not None:
            c_str = str(self.constraint).upper()
            if c_str not in ("FREE", "FIXED", "FINISH", "SMOOTH", "CONTROLLED", "NONE"):
                raise ValueError(f"seed constraint must be FREE, FIXED, FINISH, SMOOTH, CONTROLLED, or NONE, got {self.constraint!r}")


@dataclass(frozen=True)
class MeshSpecification:
    part: str
    global_size: float
    deviation_factor: float = 0.1
    min_size_factor: float = 0.1
    local_seeds: Tuple[LocalSeed, ...] = field(default_factory=tuple)
    controls: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    element_types: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    generate: bool = True

    def __post_init__(self):
        if not self.part:
            raise ValueError("part is required")
        if self.global_size is None or isinstance(self.global_size, bool) or not isinstance(self.global_size, (int, float)) or self.global_size <= 0 or not math.isfinite(self.global_size):
            raise ValueError(f"global_size must be a positive finite number, got {self.global_size!r}")
        if not 0 <= self.deviation_factor <= 1:
            raise ValueError("deviation_factor must be between 0 and 1")
        if not 0 < self.min_size_factor <= 1:
            raise ValueError("min_size_factor must be in (0, 1]")
