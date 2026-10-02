import math
from dataclasses import dataclass
from typing import Sequence, Optional
from ..contracts.geometry import resolve_region
from ..contracts.units import validate_action_quantities
from .actions import (
    VALID_CONNECTOR_ASSEMBLED_TYPES,
    VALID_CONNECTOR_TRANSLATIONAL_TYPES,
    VALID_CONNECTOR_ROTATIONAL_TYPES,
)


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    checks: tuple
    blockers: tuple = ()


@dataclass(frozen=True)
class PlanPreflightResult:
    passed: bool
    checks: tuple
    blockers: tuple = ()
    warnings: tuple = ()


def _is_finite_number(val):
    if val is None or not isinstance(val, (int, float)):
        return False
    return not (math.isnan(val) or math.isinf(val))


def preflight_action(action, snapshot=None):
    checks, blockers = [], []

    def check(name, ok, detail=None):
        item = {"name": name, "ok": bool(ok), "detail": detail}
        checks.append(item)
        if not ok:
            blockers.append(item)

    check("model_name", bool(action.model_name))
    if snapshot is not None:
        if isinstance(snapshot, dict):
            models = snapshot.get("models", ())
        else:
            models = getattr(snapshot, "models", ())
        check("model_exists", action.model_name in models, action.model_name)

    # Unit / dimensional consistency preflight
    unit_sys = None
    if snapshot is not None:
        unit_sys = snapshot.get("unit_system") if isinstance(snapshot, dict) else getattr(snapshot, "unit_system", None)
    if not unit_sys:
        unit_sys = action.parameters.get("unit_system")
    try:
        validate_action_quantities(action.action_type, action.parameters, unit_system=unit_sys)
        check("action_quantities_valid", True)
    except Exception as e:
        check("action_quantities_valid", False, str(e))

    if action.action_type in ("fixed_bc", "displacement_bc", "symmetry_bc",
                              "pressure_load", "concentrated_force",
                              "body_force", "section_assignment", "initial_temperature", "initial_stress"):
        raw_reg = action.parameters.get("region_expression")
        check("region_expression", bool(raw_reg))
        if raw_reg:
            try:
                reg_ref = resolve_region(raw_reg, fail_closed=False)
                check("region_valid", not reg_ref.is_empty, raw_reg)
            except Exception as e:
                check("region_valid", False, str(e))

    # Boundary conditions preflight
    if action.action_type in ("fixed_bc", "displacement_bc", "symmetry_bc", "temperature_bc"):
        step_name = action.parameters.get("step")
        if snapshot is not None and step_name:
            steps = snapshot.get("steps", ()) if isinstance(snapshot, dict) else getattr(snapshot, "steps", ())
            if steps:
                check("step_exists", step_name in steps or step_name == "Initial", step_name)

        if action.action_type == "fixed_bc":
            dofs = action.parameters.get("dofs")
            if dofs is not None:
                valid_dofs = all(isinstance(d, int) and 1 <= d <= 6 for d in dofs)
                check("valid_dofs", bool(valid_dofs and len(dofs) > 0), dofs)

        if action.action_type == "displacement_bc":
            comps = [action.parameters.get(k) for k in ("u1", "u2", "u3", "ur1", "ur2", "ur3")]
            specified = [c for c in comps if c is not None]
            numeric_comps = [c for c in specified if str(c).upper() != "UNSET"]
            check("displacement_components_specified", len(specified) > 0, action.parameters)
            check("displacement_components_finite", all(_is_finite_number(c) for c in numeric_comps), specified)

        if action.action_type == "temperature_bc":
            mag = action.parameters.get("magnitude")
            check("temperature_magnitude_finite", _is_finite_number(mag), mag)

    # Loads preflight
    if action.action_type in ("pressure_load", "concentrated_force", "body_force", "body_heat_flux", "surface_heat_flux"):
        step_name = action.parameters.get("step")
        if snapshot is not None and step_name:
            steps = snapshot.get("steps", ()) if isinstance(snapshot, dict) else getattr(snapshot, "steps", ())
            if steps:
                check("step_exists", step_name in steps, step_name)

        if action.action_type in ("pressure_load", "body_heat_flux", "surface_heat_flux"):
            mag = action.parameters.get("magnitude")
            check("load_magnitude_finite", _is_finite_number(mag), mag)

        if action.action_type == "concentrated_force":
            comps = [action.parameters.get(k) for k in ("cf1", "cf2", "cf3")]
            specified = [c for c in comps if c is not None]
            check("cf_components_specified", len(specified) > 0, action.parameters)
            check("cf_components_finite", all(_is_finite_number(c) for c in specified), specified)

        if action.action_type == "body_force":
            comps = [action.parameters.get(k) for k in ("comp1", "comp2", "comp3")]
            specified = [c for c in comps if c is not None]
            check("body_force_components_specified", len(specified) > 0, action.parameters)
            check("body_force_components_finite", all(_is_finite_number(c) for c in specified), specified)

    if action.action_type == "tie":
        check("name", bool(action.parameters.get("name")))
        check("master_expression", bool(action.parameters.get("master_expression")))
        check("slave_expression", bool(action.parameters.get("slave_expression")))

    if action.action_type == "contact":
        check("name", bool(action.parameters.get("name")))
        check("master_expression", bool(action.parameters.get("master_expression")))
        check("slave_expression", bool(action.parameters.get("slave_expression")))
        check("property", bool(action.parameters.get("property")))

    if action.action_type == "reference_point":
        check("name", bool(action.parameters.get("name")))
        coords = action.parameters.get("coordinates")
        check("coordinates", bool(coords and len(coords) == 3))

    if action.action_type == "rigid_body":
        check("name", bool(action.parameters.get("name")))
        check("ref_point_expression", bool(action.parameters.get("ref_point_expression")))

    if action.action_type == "connector_section":
        check("name", bool(action.parameters.get("name")))
        asmb = action.parameters.get("assembled_type")
        trans = action.parameters.get("translational_type")
        rot = action.parameters.get("rotational_type")
        check("section_type", bool(asmb or trans or rot))
        if asmb:
            check("assembled_type_valid", str(asmb).upper() in VALID_CONNECTOR_ASSEMBLED_TYPES, asmb)
        if trans:
            check("translational_type_valid", str(trans).upper() in VALID_CONNECTOR_TRANSLATIONAL_TYPES, trans)
        if rot:
            check("rotational_type_valid", str(rot).upper() in VALID_CONNECTOR_ROTATIONAL_TYPES, rot)

    if action.action_type == "wire_connector":
        check("name", bool(action.parameters.get("name")))
        check("section_name", bool(action.parameters.get("section_name")))
        has_p1 = bool(action.parameters.get("point1_name") or action.parameters.get("point1_expression"))
        has_p2 = bool(action.parameters.get("point2_name") or action.parameters.get("point2_expression"))
        check("endpoints", bool(has_p1 and has_p2))

    if action.action_type in ("instance_translate", "instance_rotate"):
        instances = getattr(snapshot, "instances", ()) if snapshot is not None and not isinstance(snapshot, dict) else ((snapshot or {}).get("instances", ()) if isinstance(snapshot, dict) else ())
        check("instance_exists", action.parameters.get("instance") in instances, action.parameters.get("instance"))
    if action.action_type == "instance_linear_pattern":
        instances = getattr(snapshot, "instances", ()) if snapshot is not None and not isinstance(snapshot, dict) else ((snapshot or {}).get("instances", ()) if isinstance(snapshot, dict) else ())
        requested = tuple(action.parameters.get("instances", ()))
        check("instances_exist", all(x in instances for x in requested), requested)
    if action.action_type == "export_inp":
        check("job_name", bool(action.parameters.get("job_name")))
    if action.action_type == "export_odb_csv":
        check("odb_path", bool(action.parameters.get("odb_path")))

    for rule in action.preconditions:
        path = rule.get("path")
        value = snapshot
        for part in str(path).split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = getattr(value, part, None)
        if "exists" in rule:
            ok = (value is not None) == bool(rule["exists"])
        elif "contains" in rule:
            try:
                ok = value is not None and rule["contains"] in value
            except TypeError:
                ok = False
        else:
            ok = value == rule.get("equals")
        check("precondition:%s" % path, ok, value)

    return PreflightResult(not blockers, tuple(checks), tuple(blockers))


def preflight_plan(actions: Sequence, snapshot=None) -> PlanPreflightResult:
    """Deterministic structural and consistency preflight for an entire Action plan."""
    all_checks = []
    all_blockers = []
    warnings = []

    defined_steps = set()
    if snapshot is not None:
        steps = snapshot.get("steps", ()) if isinstance(snapshot, dict) else getattr(snapshot, "steps", ())
        defined_steps.update(steps)
    defined_steps.add("Initial")

    bc_count = 0
    load_count = 0
    constrained_regions = set()

    for idx, action in enumerate(actions):
        res = preflight_action(action, snapshot=snapshot)
        for c in res.checks:
            item = dict(c)
            item["action_index"] = idx
            item["action_type"] = action.action_type
            all_checks.append(item)
        for b in res.blockers:
            item = dict(b)
            item["action_index"] = idx
            item["action_type"] = action.action_type
            all_blockers.append(item)

        # Track steps defined in this plan
        if action.action_type.endswith("_step"):
            step_name = action.parameters.get("name")
            if step_name:
                defined_steps.add(step_name)

        # Track BCs and Loads
        if action.action_type in ("fixed_bc", "displacement_bc", "symmetry_bc"):
            bc_count += 1
            reg = action.parameters.get("region_expression")
            if reg:
                constrained_regions.add(str(reg))
            step = action.parameters.get("step")
            if step and step not in defined_steps:
                item = {
                    "name": "step_sequence_valid",
                    "ok": False,
                    "detail": f"BC references step '{step}' before it is defined in plan",
                    "action_index": idx,
                    "action_type": action.action_type,
                }
                all_checks.append(item)
                all_blockers.append(item)

        if action.action_type in ("pressure_load", "concentrated_force", "body_force"):
            load_count += 1
            step = action.parameters.get("step")
            if step and step not in defined_steps:
                item = {
                    "name": "step_sequence_valid",
                    "ok": False,
                    "detail": f"Load references step '{step}' before it is defined in plan",
                    "action_index": idx,
                    "action_type": action.action_type,
                }
                all_checks.append(item)
                all_blockers.append(item)

    # Obvious rigid-body-motion risk check
    if load_count > 0 and bc_count == 0:
        warning_item = {
            "name": "rigid_body_motion_risk",
            "ok": False,
            "detail": f"Plan contains {load_count} loads but 0 boundary conditions or kinematic constraints",
        }
        warnings.append(warning_item)

    # Structural conflict detection: duplicate or mutually-exclusive BCs on same (region, step)
    bc_registry = {}
    for idx, action in enumerate(actions):
        if action.action_type in ("fixed_bc", "displacement_bc"):
            reg = action.parameters.get("region_expression")
            step = action.parameters.get("step", "Initial")
            if reg:
                key = (str(reg), str(step))
                if key not in bc_registry:
                    bc_registry[key] = []
                bc_registry[key].append((idx, action))

    for (reg, step), bc_list in bc_registry.items():
        if len(bc_list) > 1:
            has_fixed = any(act.action_type == "fixed_bc" for _, act in bc_list)
            for idx, act in bc_list:
                if act.action_type == "displacement_bc" and has_fixed:
                    non_zero = any(
                        isinstance(act.parameters.get(k), (int, float)) and act.parameters.get(k) != 0.0
                        for k in ("u1", "u2", "u3", "ur1", "ur2", "ur3")
                    )
                    if non_zero:
                        item = {
                            "name": "bc_structural_conflict",
                            "ok": False,
                            "detail": f"Conflicting BCs on region '{reg}' at step '{step}': fixed_bc conflicts with non-zero displacement_bc",
                            "action_index": idx,
                            "action_type": act.action_type,
                        }
                        all_checks.append(item)
                        all_blockers.append(item)

    return PlanPreflightResult(
        passed=len(all_blockers) == 0,
        checks=tuple(all_checks),
        blockers=tuple(all_blockers),
        warnings=tuple(warnings),
    )
