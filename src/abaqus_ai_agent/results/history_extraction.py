"""P1.3 History Output & XY Curve Extraction.

Extracts complete time-history and parametric data sequences from Abaqus ODB files,
supporting energy histories (ALLIE, ALLKE, ALLSE, ETOTAL), displacement histories,
and reaction force histories.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple

from ..contracts.result_intelligence import XYCurveData, XYPoint


def generate_history_curve_script(
    odb_path: str,
    step_name: Optional[str] = None,
    region_name: Optional[str] = None,
    variable_name: str = "ALLSE",
) -> str:
    """Generate Abaqus Python script to extract complete XY history data sequence."""
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
regions = step.historyRegions
region_name = %r

if region_name and region_name in regions:
    hr = regions[region_name]
else:
    # Match first region containing variable
    matches = [(_k, _v) for _k, _v in regions.items() if %r in _v.historyOutputs]
    if not matches:
        raise KeyError("History variable %%r not found in any history region" %% %r)
    region_name, hr = matches[0]

if %r not in hr.historyOutputs:
    raise KeyError("History variable %%r not found in region %%r" %% (%r, region_name))

raw_data = list(hr.historyOutputs[%r].data)
points = [[float(pt[0]), float(pt[1])] for pt in raw_data]

res = {
    "step": step_name,
    "region": region_name,
    "variable": %r,
    "point_count": len(points),
    "points": points,
}
print(json.dumps(res))
odb.close()
""" % (
        odb_path,
        step_name,
        region_name,
        variable_name,
        variable_name,
        variable_name,
        variable_name,
        variable_name,
        variable_name,
    )


def extract_history_curve(
    executor: Any,
    odb_path: str,
    variable_name: str,
    step_name: Optional[str] = None,
    region_name: Optional[str] = None,
    curve_name: Optional[str] = None,
    x_label: str = "Time",
    y_label: Optional[str] = None,
    x_unit: str = "s",
    y_unit: str = "",
) -> XYCurveData:
    """Extract complete XY history curve from ODB via executor."""
    script = generate_history_curve_script(
        odb_path=odb_path,
        step_name=step_name,
        region_name=region_name,
        variable_name=variable_name,
    )
    raw = executor.execute(script)
    payload = _parse_payload(raw)

    pts = tuple(XYPoint(x=float(p[0]), y=float(p[1])) for p in payload.get("points", []))
    cname = curve_name or f"{variable_name}_History"
    ylabel = y_label or variable_name

    return XYCurveData(
        curve_name=cname,
        x_label=x_label,
        y_label=ylabel,
        x_unit=x_unit,
        y_unit=y_unit,
        points=pts,
        metadata={
            "step": payload.get("step"),
            "region": payload.get("region"),
            "variable": variable_name,
            "odb_path": odb_path,
        },
    )


def _parse_payload(raw: Any) -> dict:
    if isinstance(raw, dict):
        if "points" in raw:
            return raw
        for k in ("stdout", "output", "result"):
            v = raw.get(k)
            if isinstance(v, str):
                for line in reversed(v.strip().splitlines()):
                    try:
                        parsed = json.loads(line)
                        if isinstance(parsed, dict) and "points" in parsed:
                            return parsed
                    except Exception:
                        pass
        return raw

    text = str(raw).strip()
    for line in reversed(text.splitlines()):
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict) and "points" in parsed:
                return parsed
        except Exception:
            pass
    return {"points": []}
