"""P1.3 Spatial Hotspot Identification & Continuum Location Extraction.

Extracts Top-K localized peak stress or displacement concentrations across 3D FE
continuum instances, recording spatial coordinates, element labels, and node labels.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple

from ..contracts.result_intelligence import SpatialHotspot


def generate_spatial_hotspots_script(
    odb_path: str,
    field_name: str = "S",
    component: str = "mises",
    step_name: Optional[str] = None,
    frame_index: int = -1,
    top_k: int = 5,
) -> str:
    """Generate Abaqus Python script to extract Top-K spatial field peaks with coordinates."""
    return """import json
from odbAccess import openOdb

odb = openOdb(path=%r, readOnly=True)
step_name = %r
if not step_name:
    step_names = list(odb.steps.keys())
    if not step_names:
        raise ValueError("ODB contains no steps")
    step_name = step_names[-1]

step = odb.steps[step_name]
frame = step.frames[%r]
field_key = %r
if field_key not in frame.fieldOutputs:
    raise KeyError("Field output %%r not found in frame" %% field_key)
field = frame.fieldOutputs[field_key]

comp_name = %r.lower()
is_scalar = len(field.values) > 0 and hasattr(field.values[0], 'data') and isinstance(field.values[0].data, (int, float))

items = []
for val in field.values:
    num_val = None
    if comp_name == 'mises' and hasattr(val, 'mises'):
        num_val = float(val.mises)
    elif comp_name in ('maxprincipal', 'max_principal') and hasattr(val, 'maxPrincipal'):
        num_val = float(val.maxPrincipal)
    elif comp_name in ('magnitude', 'mag') and hasattr(val, 'magnitude'):
        num_val = float(val.magnitude)
    elif hasattr(val, 'data'):
        if isinstance(val.data, (int, float)):
            num_val = float(val.data)
        elif isinstance(val.data, (list, tuple)) and len(val.data) > 0:
            num_val = float(val.data[0])
    
    if num_val is not None:
        items.append((num_val, val))

# Sort descending by value magnitude
items.sort(key=lambda x: x[0], reverse=True)

# Collect top_k unique elements/nodes to avoid duplicate integration point spam
top_k_limit = %r
seen_elements = set()
hotspots = []

# Map node coordinates if available on rootAssembly / instances
instance_nodes = {}
for inst_name, inst in odb.rootAssembly.instances.items():
    coords = {}
    for node in inst.nodes:
        coords[node.label] = [float(c) for c in node.coordinates]
    instance_nodes[inst_name] = coords

for rank_idx, (s_val, val) in enumerate(items):
    elem_lbl = getattr(val, 'elementLabel', None)
    node_lbl = getattr(val, 'nodeLabel', None)
    inst_name = getattr(val.instance, 'name', 'PART-1-1') if getattr(val, 'instance', None) else 'PART-1-1'
    
    if elem_lbl is not None and elem_lbl in seen_elements:
        continue
    if elem_lbl is not None:
        seen_elements.add(elem_lbl)

    xyz = [0.0, 0.0, 0.0]
    if node_lbl is not None and inst_name in instance_nodes and node_lbl in instance_nodes[inst_name]:
        xyz = instance_nodes[inst_name][node_lbl]
    elif elem_lbl is not None and hasattr(val, 'integrationPoint'):
        # Approximate by element position or fallback
        xyz = [0.0, 0.0, 0.0]

    hotspots.append({
        "rank": len(hotspots) + 1,
        "value": s_val,
        "field_name": %r,
        "component": %r,
        "coordinates": xyz,
        "instance": inst_name,
        "element_label": elem_lbl,
        "node_label": node_lbl,
    })
    if len(hotspots) >= top_k_limit:
        break

print(json.dumps({"hotspots": hotspots}))
odb.close()
""" % (
    odb_path,
    step_name,
    frame_index,
    field_name,
    component,
    top_k,
    field_name,
    component,
)


def extract_spatial_hotspots(
    executor: Any,
    odb_path: str,
    field_name: str = "S",
    component: str = "Mises",
    step_name: Optional[str] = None,
    frame_index: int = -1,
    top_k: int = 5,
    unit: str = "MPa",
) -> Tuple[SpatialHotspot, ...]:
    """Extract Top-K spatial peak hotspots from ODB using executor."""
    script = generate_spatial_hotspots_script(
        odb_path=odb_path,
        field_name=field_name,
        component=component,
        step_name=step_name,
        frame_index=frame_index,
        top_k=top_k,
    )
    raw = executor.execute(script)
    payload = _parse_hotspots_payload(raw)

    results: List[SpatialHotspot] = []
    for h in payload.get("hotspots", []):
        coords = tuple(float(c) for c in h.get("coordinates", [0.0, 0.0, 0.0]))
        if len(coords) < 3:
            coords = coords + (0.0,) * (3 - len(coords))
        coords = (coords[0], coords[1], coords[2])

        results.append(
            SpatialHotspot(
                rank=int(h.get("rank", len(results) + 1)),
                value=float(h.get("value", 0.0)),
                field_name=field_name,
                component=component,
                unit=unit,
                coordinates=coords,
                instance=str(h.get("instance", "PART-1-1")),
                element_label=h.get("element_label"),
                node_label=h.get("node_label"),
                description=f"Peak {field_name} {component} concentration #{h.get('rank', len(results) + 1)}",
            )
        )
    return tuple(results)


def _parse_hotspots_payload(raw: Any) -> dict:
    if isinstance(raw, dict):
        if "hotspots" in raw:
            return raw
        for k in ("stdout", "output", "result"):
            v = raw.get(k)
            if isinstance(v, str):
                for line in reversed(v.strip().splitlines()):
                    try:
                        parsed = json.loads(line)
                        if isinstance(parsed, dict) and "hotspots" in parsed:
                            return parsed
                    except Exception:
                        pass
        return raw

    text = str(raw).strip()
    for line in reversed(text.splitlines()):
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict) and "hotspots" in parsed:
                return parsed
        except Exception:
            pass
    return {"hotspots": []}
