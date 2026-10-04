"""Deterministic fatigue post-processing for scalar Abaqus stress histories."""

import json
import os
from math import exp, isfinite, log
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .contracts.fatigue import FatigueResult, IntentFatigueSpec


def stress_range_and_amplitude(stress_a: float, stress_b: float) -> Tuple[float, float]:
    a, b = float(stress_a), float(stress_b)
    if not isfinite(a) or not isfinite(b):
        raise ValueError("stress values must be finite")
    r = abs(b - a)
    return r, r / 2.0


def turning_points(points: Sequence[float]) -> Tuple[float, ...]:
    values = tuple(float(x) for x in points)
    if any(not isfinite(x) for x in values):
        raise ValueError("stress history values must be finite")
    if not values:
        return ()
    out = [values[0]]
    for value in values[1:]:
        if value != out[-1]:
            out.append(value)
    if len(out) < 3:
        return tuple(out)
    turning = [out[0]]
    for i in range(1, len(out) - 1):
        if (out[i] - out[i - 1]) * (out[i + 1] - out[i]) < 0:
            turning.append(out[i])
    turning.append(out[-1])
    return tuple(turning)


def rainflow_count(stress_history: Sequence[float]) -> Tuple[Tuple[float, float, float], ...]:
    """Return (range, mean, count); count is 1.0 full or 0.5 half cycle."""
    points = turning_points(stress_history)
    if len(points) < 2:
        return ()
    stack: List[float] = []
    cycles = []
    for point in points:
        stack.append(point)
        while len(stack) >= 3:
            x, y, z = stack[-3:]
            r1, r2 = abs(y - x), abs(z - y)
            if r2 < r1:
                break
            cycles.append((r1, (x + y) / 2.0, 0.5 if len(stack) == 3 else 1.0))
            del stack[-3:-1]
    for i in range(len(stack) - 1):
        r, _ = stress_range_and_amplitude(stack[i], stack[i + 1])
        if r > 0:
            cycles.append((r, (stack[i] + stack[i + 1]) / 2.0, 0.5))
    return tuple(cycles)


def goodman_corrected_amplitude(amplitude: float, mean_stress: float, ultimate_strength: float) -> float:
    """Goodman correction for tensile mean stress; non-positive mean is unchanged."""
    sa, sm, sut = map(float, (amplitude, mean_stress, ultimate_strength))
    if not all(isfinite(x) for x in (sa, sm, sut)) or sa < 0 or sut <= 0:
        raise ValueError("amplitude must be non-negative and ultimate strength positive")
    if sm <= 0:
        return sa
    if sm >= sut:
        raise ValueError("positive mean stress must be below ultimate strength")
    return sa / (1.0 - sm / sut)


def reduce_multiaxial_history(history: Iterable[dict], measure: str = "von_mises") -> Tuple[float, ...]:
    """Reduce explicit stress records to a declared scalar fatigue measure."""
    measure = str(measure).lower()
    result = []
    for item in history:
        if not isinstance(item, dict):
            raise ValueError("multiaxial history entries must be mappings")
        key = "mises" if measure == "von_mises" else "normal" if measure == "normal" else None
        if key is None:
            raise ValueError("unsupported multiaxial fatigue measure: %s" % measure)
        if key not in item:
            raise ValueError("%s measure requires '%s'" % (measure, key))
        value = float(item[key])
        if not isfinite(value):
            raise ValueError("stress history values must be finite")
        result.append(value)
    return tuple(result)


def miner_damage(cycles: Sequence[Tuple[float, float, float]], material_curve: Sequence[Tuple[float, float]], ultimate_strength: float = None) -> float:
    """Accumulate Palmgren-Miner damage from counted stress cycles."""
    damage = 0.0
    for stress_range, mean, count in cycles:
        if count < 0:
            raise ValueError("cycle count cannot be negative")
        amplitude = float(stress_range) / 2.0
        corrected = (
            goodman_corrected_amplitude(amplitude, mean, ultimate_strength)
            if ultimate_strength is not None else amplitude
        )
        if corrected <= 0:
            continue
        damage += float(count) / sn_life(corrected, material_curve)
    return damage


def fatigue_life_blocks(cycles: Sequence[Tuple[float, float, float]], material_curve: Sequence[Tuple[float, float]], ultimate_strength: float = None) -> float:
    """Return repeated-spectrum blocks to Miner failure (unit damage)."""
    damage = miner_damage(cycles, material_curve, ultimate_strength)
    if damage <= 0:
        raise ValueError("cycle spectrum has zero damage")
    return 1.0 / damage


def sn_life(alternating_stress: float, material_curve: Sequence[Tuple[float, float]]) -> float:
    """Log-log interpolate cycles to failure within a declared S-N curve."""
    target = float(alternating_stress)
    if not isfinite(target) or target <= 0 or len(material_curve) < 2:
        raise ValueError("positive stress and at least two S-N points are required")
    curve = sorted((float(s), float(n)) for s, n in material_curve)
    if any(s <= 0 or n <= 0 for s, n in curve):
        raise ValueError("S-N curve values must be positive")
    if target < curve[0][0] or target > curve[-1][0]:
        raise ValueError("stress is outside the supplied S-N curve")
    for (s1, n1), (s2, n2) in zip(curve, curve[1:]):
        if s1 <= target <= s2:
            if s1 == s2:
                return n1
            ratio = (target - s1) / (s2 - s1)
            return exp(log(n1) + ratio * (log(n2) - log(n1)))
    return curve[-1][1]


def compute_scalar_stress(stress_record: dict, measure: str = "signed_mises") -> float:
    """Compute scalar equivalent stress from multiaxial stress dictionary.

    Supported measures:
    - 'signed_mises': Signed von Mises based on trace(S) hydrostatic sign or maxPrincipal sign.
    - 'von_mises' / 'mises': Standard unsigned von Mises stress.
    - 'max_principal': Maximum principal stress (S1).
    - 'tresca': Maximum shear stress (Tresca).
    - 's11', 's22', 's33', 's12', 's13', 's23': Direct tensor component.
    """
    if not isinstance(stress_record, dict):
        raise ValueError("stress_record must be a dictionary")
    m = measure.lower()

    if m in ("von_mises", "mises"):
        if "mises" not in stress_record:
            raise ValueError("von_mises measure requires 'mises' field")
        val = float(stress_record["mises"])
        if not isfinite(val):
            raise ValueError("stress values must be finite")
        return abs(val)

    if m == "signed_mises":
        if "mises" not in stress_record:
            raise ValueError("signed_mises measure requires 'mises' field")
        mises_val = abs(float(stress_record["mises"]))
        sign = 1.0
        if "data" in stress_record and hasattr(stress_record["data"], "__iter__") and len(stress_record["data"]) >= 3:
            tr = float(stress_record["data"][0]) + float(stress_record["data"][1]) + float(stress_record["data"][2])
            sign = 1.0 if tr >= 0.0 else -1.0
        elif "maxPrincipal" in stress_record and stress_record["maxPrincipal"] is not None:
            sign = 1.0 if float(stress_record["maxPrincipal"]) >= 0.0 else -1.0
        elif "s11" in stress_record and stress_record["s11"] is not None:
            sign = 1.0 if float(stress_record["s11"]) >= 0.0 else -1.0
        return sign * mises_val

    if m == "max_principal":
        if "maxPrincipal" not in stress_record or stress_record["maxPrincipal"] is None:
            raise ValueError("max_principal measure requires 'maxPrincipal' field")
        val = float(stress_record["maxPrincipal"])
        if not isfinite(val):
            raise ValueError("stress values must be finite")
        return val

    if m == "tresca":
        if "tresca" not in stress_record or stress_record["tresca"] is None:
            raise ValueError("tresca measure requires 'tresca' field")
        val = float(stress_record["tresca"])
        if not isfinite(val):
            raise ValueError("stress values must be finite")
        return abs(val)

    # Tensor component check (e.g. s11, s22)
    comp_map = {"s11": 0, "s22": 1, "s33": 2, "s12": 3, "s13": 4, "s23": 5}
    if m in comp_map:
        if m in stress_record and stress_record[m] is not None:
            return float(stress_record[m])
        if "data" in stress_record and hasattr(stress_record["data"], "__iter__"):
            idx = comp_map[m]
            if len(stress_record["data"]) > idx:
                return float(stress_record["data"][idx])
        raise ValueError(f"component '{measure}' not found in stress record")

    raise ValueError(f"unsupported multiaxial fatigue measure: {measure}")


def evaluate_cycle_life(
    alternating_stress: float,
    material_curve: Sequence[Tuple[float, float]],
    endurance_limit_infinite: bool = True,
) -> float:
    """Evaluate fatigue life cycles with engineering endurance limit handling."""
    target = float(alternating_stress)
    if not isfinite(target) or target <= 0.0:
        return float("inf")
    if len(material_curve) < 2:
        raise ValueError("at least two S-N curve points are required")
    curve = sorted((float(s), float(n)) for s, n in material_curve)
    if any(s <= 0 or n <= 0 for s, n in curve):
        raise ValueError("S-N curve values must be positive")

    s_min, n_at_s_min = curve[0]
    s_max, n_at_s_max = curve[-1]

    # Exact point shortcut to avoid log/exp floating point round-off
    for s_pt, n_pt in curve:
        if abs(target - s_pt) <= 1e-9 * max(1.0, abs(s_pt)):
            return n_pt

    if target < s_min:
        if endurance_limit_infinite:
            return float("inf")
        # Log-log extrapolation below lowest curve point
        s1, n1 = curve[0]
        s2, n2 = curve[1]
        b = (log(s1) - log(s2)) / (log(n1) - log(n2)) if n1 != n2 else 1.0
        return n1 * ((s1 / target) ** (1.0 / abs(b)))

    if target > s_max:
        return n_at_s_max

    return sn_life(target, curve)


def accumulate_palmgren_miner_damage(
    cycles: Sequence[Tuple[float, float, float]],
    material_curve: Sequence[Tuple[float, float]],
    ultimate_strength: Optional[float] = None,
    endurance_limit_infinite: bool = True,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Calculate Palmgren-Miner cumulative damage and per-cycle details."""
    total_damage = 0.0
    detailed_cycles = []

    for stress_range, mean_stress, count in cycles:
        if count < 0:
            raise ValueError("cycle count cannot be negative")
        amplitude = float(stress_range) / 2.0
        corrected_amp = (
            goodman_corrected_amplitude(amplitude, mean_stress, ultimate_strength)
            if ultimate_strength is not None
            else amplitude
        )

        if corrected_amp <= 0.0:
            n_fail = float("inf")
            cycle_damage = 0.0
        else:
            n_fail = evaluate_cycle_life(
                corrected_amp,
                material_curve,
                endurance_limit_infinite=endurance_limit_infinite,
            )
            cycle_damage = float(count) / n_fail if isfinite(n_fail) and n_fail > 0 else 0.0

        total_damage += cycle_damage
        detailed_cycles.append({
            "stress_range": float(stress_range),
            "amplitude": float(amplitude),
            "mean_stress": float(mean_stress),
            "cycle_count": float(count),
            "corrected_amplitude": float(corrected_amp),
            "life_cycles": n_fail,
            "damage": float(cycle_damage),
        })

    return total_damage, detailed_cycles


def extract_stress_history_from_odb(
    odb_or_path: Any,
    step_name: Optional[str] = None,
    element_label: Optional[int] = None,
    integration_point: Optional[int] = None,
    measure: str = "signed_mises",
    region_instance: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract stress time history and detect global hotspot from an open ODB object or path."""
    opened_here = False
    odb = odb_or_path
    if isinstance(odb_or_path, (str, bytes, os.PathLike)):
        from odbAccess import openOdb
        odb = openOdb(path=str(odb_or_path), readOnly=True)
        opened_here = True

    try:
        steps = odb.steps
        if not steps:
            raise ValueError("ODB has no analysis steps")
        if step_name and step_name != "ALL":
            if step_name not in steps:
                raise ValueError(f"Step '{step_name}' not found in ODB steps: {list(steps.keys())}")
            target_steps = [(step_name, steps[step_name])]
            st_name = step_name
        else:
            target_steps = list(steps.items())
            st_name = "ALL" if len(target_steps) > 1 else target_steps[0][0]

        # 1. Hotspot identification if element_label is omitted
        hot_elem = element_label
        hot_ip = integration_point
        hot_inst = region_instance
        max_mises = -1.0

        if hot_elem is None:
            for _, step in target_steps:
                for frame in step.frames:
                    if "S" not in frame.fieldOutputs:
                        continue
                    s_field = frame.fieldOutputs["S"]
                    for val in s_field.values:
                        vm = getattr(val, "mises", None)
                        if vm is not None and float(vm) > max_mises:
                            max_mises = float(vm)
                            hot_elem = getattr(val, "elementLabel", None)
                            hot_ip = getattr(val, "integrationPoint", 1)
                            inst = getattr(val, "instance", None)
                            hot_inst = getattr(inst, "name", None) if inst else None

        if hot_elem is None:
            raise ValueError(f"No stress field 'S' found in step(s) to establish hotspot")

        # 2. Extract multi-frame history for this hotspot
        history_points = []
        raw_stresses = []
        times = []
        cumulative_time = 0.0

        for _, step in target_steps:
            for frame in step.frames:
                t = cumulative_time + float(getattr(frame, "frameValue", 0.0))
                if "S" not in frame.fieldOutputs:
                    continue
                s_field = frame.fieldOutputs["S"]
                matched_val = None
                for val in s_field.values:
                    el = getattr(val, "elementLabel", None)
                    ip = getattr(val, "integrationPoint", 1)
                    inst = getattr(val, "instance", None)
                    inst_name = getattr(inst, "name", None) if inst else None
                    if el == hot_elem:
                        if hot_ip is not None and ip != hot_ip:
                            continue
                        if hot_inst is not None and inst_name != hot_inst:
                            continue
                        matched_val = val
                        break

                if matched_val is not None:
                    record = {
                        "mises": getattr(matched_val, "mises", None),
                        "maxPrincipal": getattr(matched_val, "maxPrincipal", None),
                        "tresca": getattr(matched_val, "tresca", None),
                        "data": list(matched_val.data) if hasattr(matched_val.data, "__iter__") else [matched_val.data],
                    }
                    scalar_val = compute_scalar_stress(record, measure=measure)
                    times.append(t)
                    raw_stresses.append(scalar_val)
                    history_points.append({
                        "time": t,
                        "scalar_stress": scalar_val,
                        "mises": float(record["mises"]) if record["mises"] is not None else None,
                        "data": [float(x) for x in record["data"]],
                    })
            if step.frames:
                cumulative_time += float(getattr(step.frames[-1], "frameValue", 0.0))

        return {
            "step_name": st_name,
            "hotspot": {
                "element_label": hot_elem,
                "integration_point": hot_ip,
                "instance_name": hot_inst,
                "peak_mises_detected": max_mises if max_mises >= 0 else None,
            },
            "measure": measure,
            "frame_count": len(history_points),
            "times": times,
            "stresses": raw_stresses,
            "history": history_points,
        }
    finally:
        if opened_here:
            odb.close()


def evaluate_fatigue_from_stress_history(
    times: Sequence[float],
    stresses: Sequence[float],
    material_curve: Sequence[Tuple[float, float]],
    ultimate_strength: Optional[float] = None,
    mean_stress_correction: Optional[str] = "GOODMAN",
    damage_allowable: float = 1.0,
    hotspot_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Perform deterministic rainflow counting and fatigue damage accumulation on a stress history."""
    if len(stresses) < 2:
        raise ValueError("stress history must contain at least 2 points")

    turning = turning_points(stresses)
    counted_raw = rainflow_count(stresses)

    # Accumulate Miner damage
    sut = ultimate_strength if (mean_stress_correction and mean_stress_correction.upper() == "GOODMAN") else None
    total_damage, detailed_cycles = accumulate_palmgren_miner_damage(
        counted_raw,
        material_curve=material_curve,
        ultimate_strength=sut,
        endurance_limit_infinite=True,
    )

    life_blocks = (1.0 / total_damage) if total_damage > 0.0 else float("inf")
    stress_ranges = [c["stress_range"] for c in detailed_cycles]
    mean_stresses = [c["mean_stress"] for c in detailed_cycles]

    summary = {
        "total_cycles_count": sum(c["cycle_count"] for c in detailed_cycles),
        "full_cycles_count": sum(1 for c in detailed_cycles if c["cycle_count"] == 1.0),
        "half_cycles_count": sum(1 for c in detailed_cycles if c["cycle_count"] == 0.5),
        "max_stress_range": max(stress_ranges) if stress_ranges else 0.0,
        "max_stress_amplitude": max(stress_ranges) / 2.0 if stress_ranges else 0.0,
        "mean_stress_average": sum(mean_stresses) / len(mean_stresses) if mean_stresses else 0.0,
        "cumulative_damage": total_damage,
        "life_blocks": life_blocks,
        "damage_allowable": damage_allowable,
    }

    # Standard engineering acceptance criteria
    criteria = {
        "has_stress_history": len(stresses) >= 2,
        "rainflow_cycles_counted": len(detailed_cycles) > 0,
        "damage_within_allowable": total_damage <= damage_allowable,
        "finite_or_safe_damage": isfinite(total_damage) and total_damage >= 0.0,
    }
    passed = all(criteria.values())

    # Strict negative gate for verification: artificially strict damage limit (1e-15)
    strict_criteria = {
        **criteria,
        "strict_damage_threshold": total_damage <= 1.0e-15,
    }
    strict_passed = all(strict_criteria.values())

    return {
        "status": "pass" if passed else "fail",
        "passed": passed,
        "hotspot": hotspot_info or {},
        "cycle_summary": summary,
        "cycles": detailed_cycles,
        "acceptance": {
            "passed": passed,
            "criteria": criteria,
        },
        "strict_gate": {
            "passed": strict_passed,
            "expected_fail": not strict_passed,
            "criteria": strict_criteria,
        },
    }


def build_odb_fatigue_postprocess_script(
    odb_path: str,
    output_json: str,
    material_curve: Sequence[Tuple[float, float]],
    ultimate_strength: Optional[float] = 800.0,
    mean_stress_correction: str = "GOODMAN",
    measure: str = "signed_mises",
    step_name: Optional[str] = None,
    element_label: Optional[int] = None,
    src_dir: Optional[str] = None,
) -> str:
    """Generate self-contained Abaqus Python script for ODB fatigue postprocessing."""
    src = os.path.abspath(src_dir or os.path.join(os.path.dirname(__file__), ".."))
    return f'''# Auto-generated by Abaqus AI Agent for ODB Fatigue Postprocessing
import sys
import os
import json

if r"{src}" not in sys.path:
    sys.path.insert(0, r"{src}")

from abaqus_ai_agent.fatigue import (
    extract_stress_history_from_odb,
    evaluate_fatigue_from_stress_history,
)

odb_path = r"{os.path.abspath(odb_path)}"
output_json = r"{os.path.abspath(output_json)}"
material_curve = {list(material_curve)}
ultimate_strength = {ultimate_strength if ultimate_strength is not None else "None"}
mean_stress_correction = {repr(mean_stress_correction)}
measure = {repr(measure)}
step_name = {repr(step_name)}
element_label = {repr(element_label)}

# 1. Extract stress history from live ODB
extracted = extract_stress_history_from_odb(
    odb_path,
    step_name=step_name,
    element_label=element_label,
    measure=measure,
)

# 2. Evaluate fatigue damage
eval_result = evaluate_fatigue_from_stress_history(
    times=extracted["times"],
    stresses=extracted["stresses"],
    material_curve=material_curve,
    ultimate_strength=ultimate_strength,
    mean_stress_correction=mean_stress_correction,
    hotspot_info=extracted["hotspot"],
)

# 3. Assemble full evidence envelope
evidence = {{
    "case_id": "fatigue_real_odb",
    "status": eval_result["status"],
    "odb_path": odb_path,
    "step_name": extracted["step_name"],
    "measure": measure,
    "hotspot": extracted["hotspot"],
    "stress_history": {{
        "frame_count": extracted["frame_count"],
        "times": extracted["times"],
        "stresses": extracted["stresses"],
    }},
    "cycle_summary": eval_result["cycle_summary"],
    "cycles": eval_result["cycles"],
    "acceptance": eval_result["acceptance"],
    "strict_gate": eval_result["strict_gate"],
}}

with open(output_json, "w") as f:
    json.dump(evidence, f, indent=2)

print("AIAgent_FATIGUE_EVALUATION_COMPLETED")
print("Hotspot: Element %s IP %s Peak Mises: %s MPa" % (
    extracted["hotspot"].get("element_label"),
    extracted["hotspot"].get("integration_point"),
    extracted["hotspot"].get("peak_mises_detected"),
))
print("Rainflow Cycles: %d (Full: %d, Half: %d)" % (
    eval_result["cycle_summary"]["total_cycles_count"],
    eval_result["cycle_summary"]["full_cycles_count"],
    eval_result["cycle_summary"]["half_cycles_count"],
))
print("Max Stress Range: %.2f MPa | Avg Mean Stress: %.2f MPa" % (
    eval_result["cycle_summary"]["max_stress_range"],
    eval_result["cycle_summary"]["mean_stress_average"],
))
print("Cumulative Miner Damage D: %.6e" % eval_result["cycle_summary"]["cumulative_damage"])
print("Life Blocks to Failure: %.2f" % eval_result["cycle_summary"]["life_blocks"])
print("Acceptance Passed: %s | Strict Gate Failed (as designed): %s" % (
    eval_result["acceptance"]["passed"],
    not eval_result["strict_gate"]["passed"],
))
'''


def run_fatigue_postprocess(
    odb_or_path: Any,
    spec: IntentFatigueSpec,
    output_json_path: Optional[str] = None,
) -> Tuple[FatigueResult, Dict[str, Any]]:
    """Execute fatigue postprocessing on an open ODB or ODB path given an IntentFatigueSpec.

    Returns:
        (FatigueResult, metrics_dict)
    """
    if not isinstance(spec, IntentFatigueSpec):
        raise TypeError("spec must be an IntentFatigueSpec")

    extracted = extract_stress_history_from_odb(
        odb_or_path=odb_or_path,
        step_name=spec.step_name,
        element_label=spec.element_label,
        measure=spec.measure,
    )

    eval_result = evaluate_fatigue_from_stress_history(
        times=extracted["times"],
        stresses=extracted["stresses"],
        material_curve=spec.material_curve,
        ultimate_strength=spec.ultimate_strength,
        mean_stress_correction=spec.mean_stress_correction,
        damage_allowable=spec.allowable_damage,
        hotspot_info=extracted.get("hotspot"),
    )

    cycle_sum = eval_result["cycle_summary"]
    life_blocks = cycle_sum.get("life_blocks", 0.0)
    damage = cycle_sum.get("cumulative_damage", 0.0)

    # Convert repeated blocks into total equivalent life cycles based on counted cycles
    total_counted_cycles = max(cycle_sum.get("total_cycles_count", 1.0), 1.0)
    if isfinite(life_blocks) and life_blocks > 0:
        life_cycles = min(life_blocks * total_counted_cycles, 1.0e8)
    else:
        life_cycles = 1.0e8

    # Determine status against IntentFatigueSpec
    warnings: List[str] = []
    if damage > spec.allowable_damage:
        status = "fail"
        warnings.append(f"cumulative_damage_{damage:.4e}_exceeds_allowable_{spec.allowable_damage}")
    elif life_cycles < spec.target_cycles:
        status = "fail"
        warnings.append(f"life_cycles_{life_cycles:.1f}_below_target_{spec.target_cycles:.1f}")
    elif not eval_result["passed"]:
        status = "fail"
    else:
        status = "pass"

    evidence_ids = ["fatigue_postprocess_direct"]
    if output_json_path:
        evidence_payload = {
            "case_id": "fatigue_l4_evaluation",
            "status": status,
            "hotspot": extracted.get("hotspot"),
            "cycle_summary": cycle_sum,
            "acceptance": eval_result.get("acceptance"),
            "target_cycles": spec.target_cycles,
            "allowable_damage": spec.allowable_damage,
            "life_cycles": life_cycles,
        }
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(evidence_payload, f, indent=2)
        evidence_ids.append(os.path.basename(output_json_path))

    fatigue_res = FatigueResult(
        status=status,
        life_cycles=life_cycles,
        damage=damage,
        warnings=tuple(warnings),
        evidence=tuple(evidence_ids),
    )

    metrics = {
        "fatigue_life": life_cycles,
        "damage": damage,
        "max_stress_range": cycle_sum.get("max_stress_range", 0.0),
        "mean_stress_average": cycle_sum.get("mean_stress_average", 0.0),
        "total_cycles_count": cycle_sum.get("total_cycles_count", 0.0),
        "hotspot_element": extracted.get("hotspot", {}).get("element_label"),
    }

    return fatigue_res, metrics
