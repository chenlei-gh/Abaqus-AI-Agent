from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class ModelSnapshot:
    """Read-only normalized inventory used for planning and state-diffing."""
    models: Tuple[str, ...] = ()
    parts: Tuple[str, ...] = ()
    instances: Tuple[str, ...] = ()
    materials: Tuple[str, ...] = ()
    sections: Tuple[str, ...] = ()
    steps: Tuple[str, ...] = ()
    boundary_conditions: Tuple[str, ...] = ()
    loads: Tuple[str, ...] = ()
    interactions: Tuple[str, ...] = ()
    output_requests: Tuple[str, ...] = ()
    jobs: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data):
        data = data or {}
        def names(key):
            value = data.get(key, ())
            if isinstance(value, dict):
                value = value.keys()
            return tuple(sorted(str(x) for x in value))
        return cls(
            models=names("models"), parts=names("parts"), instances=names("instances"),
            materials=names("materials"), sections=names("sections"), steps=names("steps"),
            boundary_conditions=names("boundary_conditions"), loads=names("loads"),
            interactions=names("interactions"), output_requests=names("output_requests"),
            jobs=names("jobs"), metadata=dict(data.get("metadata", {}) or {}))


@dataclass(frozen=True)
class SnapshotDelta:
    added: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    removed: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    changed_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def changed(self):
        return bool(self.added or self.removed or self.changed_metadata)
