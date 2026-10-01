import hashlib
import json


def stable_hash(value):
    """Return a deterministic SHA-256 hash for JSON-compatible values."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_text(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()
