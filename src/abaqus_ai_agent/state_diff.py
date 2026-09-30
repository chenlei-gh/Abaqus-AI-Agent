from .contracts.model_snapshot import ModelSnapshot, SnapshotDelta

_FIELDS = (
    "models", "parts", "instances", "materials", "sections", "steps",
    "boundary_conditions", "loads", "interactions", "output_requests", "jobs",
)


def diff_snapshots(before, after):
    """Return deterministic added/removed model-state inventory."""
    if not isinstance(before, ModelSnapshot) or not isinstance(after, ModelSnapshot):
        raise TypeError("before and after must be ModelSnapshot")
    added, removed = {}, {}
    for field in _FIELDS:
        old = set(getattr(before, field)); new = set(getattr(after, field))
        if new - old: added[field] = tuple(sorted(new - old))
        if old - new: removed[field] = tuple(sorted(old - new))
    changed = {}
    keys = set(before.metadata) | set(after.metadata)
    for key in sorted(keys):
        if before.metadata.get(key) != after.metadata.get(key):
            changed[key] = {"before": before.metadata.get(key), "after": after.metadata.get(key)}
    return SnapshotDelta(added=added, removed=removed, changed_metadata=changed)
