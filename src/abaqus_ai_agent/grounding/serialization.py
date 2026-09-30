import json
from dataclasses import asdict, is_dataclass


def to_plain_data(value):
    """Convert contracts and nested containers into JSON-safe plain data."""
    if is_dataclass(value):
        return {key: to_plain_data(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_plain_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain_data(item) for item in value]
    return value


def dumps(value, **kwargs):
    """Serialize a grounding result or probe payload to JSON."""
    options = {"sort_keys": True}
    options.update(kwargs)
    return json.dumps(to_plain_data(value), **options)
