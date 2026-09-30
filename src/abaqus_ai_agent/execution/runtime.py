import json
from .inspection import runtime_info
from ..contracts.version import AbaqusRuntimeInfo


def _mapping(raw):
    if isinstance(raw,dict):
        for k in ("data","result"):
            if isinstance(raw.get(k),dict): return raw[k]
        for k in ("stdout","output"):
            if isinstance(raw.get(k),str):
                try: return json.loads(raw[k])
                except ValueError: pass
        return raw
    try: return json.loads(raw)
    except (TypeError,ValueError): return {}


def detect_runtime(executor):
    data=_mapping(runtime_info(executor))
    return AbaqusRuntimeInfo(version=str(data.get("version","unknown")),
        python_version=str(data.get("python_version","unknown")),
        gui_available=bool(data.get("gui_available",False)),
        capabilities=tuple(sorted(str(x) for x in data.get("capabilities",()) )),
        metadata=dict(data.get("metadata",{}) or {}))
