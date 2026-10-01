"""Executor-neutral mesh contracts and normalization."""

from dataclasses import dataclass, field
from math import isfinite
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
        if self.size is not None and (not isfinite(self.size) or self.size <= 0):
            raise ValueError("seed size must be positive and finite")
        if self.number is not None and int(self.number) != self.number:
            raise ValueError("seed number must be an integer")
        if self.number is not None and self.number < 1:
            raise ValueError("seed number must be positive")


def _require_mapping_entries(entries, name):
    if not isinstance(entries, (tuple, list)):
        raise ValueError("%s must be a sequence" % name)
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("%s entries must be dictionaries" % name)


def _validate_bias_seed(entry):
    for key in ("region_expression", "min_size", "max_size"):
        if entry.get(key) in (None, ""):
            raise ValueError("bias seed requires %s" % key)
    min_size = entry["min_size"]
    max_size = entry["max_size"]
    if not isinstance(min_size, (int, float)) or not isfinite(min_size) or min_size <= 0:
        raise ValueError("bias seed min_size must be positive and finite")
    if not isinstance(max_size, (int, float)) or not isfinite(max_size) or max_size <= 0:
        raise ValueError("bias seed max_size must be positive and finite")
    if max_size < min_size:
        raise ValueError("bias seed max_size must be >= min_size")
    if str(entry.get("end", "END1")).upper() not in ("END1", "END2"):
        raise ValueError("bias seed end must be END1 or END2")
    if str(entry.get("constraint", "FREE")).upper() not in ("FREE", "FINER", "FIXED"):
        raise ValueError("bias seed constraint must be FREE, FINER or FIXED")


def _validate_sweep_path(entry):
    for key in ("region_expression", "edge_expression"):
        if entry.get(key) in (None, ""):
            raise ValueError("sweep path requires %s" % key)
    if str(entry.get("sense", "FORWARD")).upper() not in ("FORWARD", "REVERSE"):
        raise ValueError("sweep path sense must be FORWARD or REVERSE")


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
        if not isinstance(self.global_size, (int, float)) or not isfinite(self.global_size) or self.global_size <= 0:
            raise ValueError("global_size must be positive and finite")
        if not isinstance(self.deviation_factor, (int, float)) or not isfinite(self.deviation_factor) or not 0 <= self.deviation_factor <= 1:
            raise ValueError("deviation_factor must be between 0 and 1")
        if not isinstance(self.min_size_factor, (int, float)) or not isfinite(self.min_size_factor) or not 0 < self.min_size_factor <= 1:
            raise ValueError("min_size_factor must be in (0, 1]")
        _require_mapping_entries(self.bias_seeds, "bias_seeds")
        for entry in self.bias_seeds:
            _validate_bias_seed(entry)
        _require_mapping_entries(self.sweep_paths, "sweep_paths")
        for entry in self.sweep_paths:
            _validate_sweep_path(entry)
        _require_mapping_entries(self.controls, "controls")
        _require_mapping_entries(self.element_types, "element_types")
