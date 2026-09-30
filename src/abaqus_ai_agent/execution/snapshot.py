import json
from .inspection import snapshot_model
from ..contracts.model_snapshot import ModelSnapshot


def _mapping(raw):
    if isinstance(raw, dict):
        for key in ("data", "result"):
            if isinstance(raw.get(key), dict): return raw[key]
        for key in ("stdout", "output"):
            value=raw.get(key)
            if isinstance(value,str):
                try: return json.loads(value)
                except ValueError: pass
        return raw
    if isinstance(raw,str):
        try: return json.loads(raw)
        except ValueError: return {}
    return {}


def read_model_snapshot(executor):
    return ModelSnapshot.from_mapping(_mapping(snapshot_model(executor)))
