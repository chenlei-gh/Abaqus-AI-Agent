import math
import pytest
from abaqus_ai_agent.contracts.geometry import (
    RegionReference,
    RegionBinding,
    GeometrySelection,
    resolve_region,
)
from abaqus_ai_agent.contracts.action import AbaqusAction
from abaqus_ai_agent.contracts.mesh_quality import (
    classify_mesh_quality_metrics,
    ABAQUS_NATIVE_SHAPE_METRICS,
)
from abaqus_ai_agent.validation.preflight import (
    preflight_action,
    preflight_plan,
)


def test_region_resolver_string_expressions():
    r1 = resolve_region("a.sets['RootSet']")
    assert r1.kind == "set"
    assert r1.name == "RootSet"
    assert r1.expression == "a.sets['RootSet']"

    r2 = resolve_region("a.surfaces['TopFace']")
    assert r2.kind == "surface"
    assert r2.name == "TopFace"

    r3 = resolve_region("a.instances['Beam-1'].faces[:1]")
    assert r3.kind == "native_expression"
    assert r3.expression == "a.instances['Beam-1'].faces[:1]"


def test_region_resolver_binding_and_selection():
    target = {"point": (0.0, 0.0, 0.0), "normal": (0.0, 1.0, 0.0)}
    binding = RegionBinding(
        region_kind="surface",
        name="LoadedFace",
        entity_type="Face",
        targets=(target,),
    )
    r = resolve_region(binding)
    assert r.kind == "surface"
    assert r.name == "LoadedFace"
    assert r.expression == "a.surfaces['LoadedFace']"

    selection = GeometrySelection(
        targets=(target,),
        entity_type="Face",
        region_kind="set",
        name="FixedSet",
    )
    r_sel = resolve_region(selection)
    assert r_sel.kind == "set"
    assert r_sel.name == "FixedSet"
    assert r_sel.expression == "a.sets['FixedSet']"


def test_region_resolver_dict_and_fail_closed():
    r_dict = resolve_region({"set": "NodeSetA"})
    assert r_dict.kind == "set"
    assert r_dict.expression == "a.sets['NodeSetA']"

    # Fail closed on empty/None
    with pytest.raises(ValueError, match="empty or missing"):
        resolve_region(None, fail_closed=True)

    with pytest.raises(ValueError, match="empty region expression"):
        resolve_region("   ", fail_closed=True)

    # Permissive mode
    empty_ref = resolve_region("", fail_closed=False)
    assert empty_ref.is_empty is True


def test_preflight_bc_dof_and_component_checks():
    # Valid fixed BC
    act_valid = AbaqusAction(
        action_type="fixed_bc",
        model_name="Model-1",
        target="FixRoot",
        parameters={"name": "FixRoot", "region_expression": "a.sets['Root']", "dofs": (1, 2, 3)},
    )
    res_valid = preflight_action(act_valid)
    assert res_valid.passed is True

    # Invalid dof (e.g. 7 or negative)
    act_invalid_dof = AbaqusAction(
        action_type="fixed_bc",
        model_name="Model-1",
        target="FixRoot",
        parameters={"name": "FixRoot", "region_expression": "a.sets['Root']", "dofs": (1, 9)},
    )
    res_dof = preflight_action(act_invalid_dof)
    assert res_dof.passed is False
    assert any(b["name"] == "valid_dofs" for b in res_dof.blockers)

    # Displacement BC with NaN
    act_nan = AbaqusAction(
        action_type="displacement_bc",
        model_name="Model-1",
        target="Disp",
        parameters={"name": "Disp", "region_expression": "a.sets['Tip']", "u2": float("nan")},
    )
    res_nan = preflight_action(act_nan)
    assert res_nan.passed is False
    assert any(b["name"] == "displacement_components_finite" for b in res_nan.blockers)


def test_preflight_plan_sequence_and_rigid_body_warning():
    # Plan with loads but zero BCs -> should trigger rigid_body_motion_risk warning
    plan_no_bc = [
        AbaqusAction(
            action_type="static_step",
            model_name="Model-1",
            target="Step-1",
            parameters={"name": "Step-1", "previous": "Initial"},
        ),
        AbaqusAction(
            action_type="pressure_load",
            model_name="Model-1",
            target="Press",
            parameters={"name": "Press", "step": "Step-1", "region_expression": "a.surfaces['Top']", "magnitude": 100.0},
        ),
    ]
    res_plan = preflight_plan(plan_no_bc)
    assert res_plan.passed is True
    assert any(w["name"] == "rigid_body_motion_risk" for w in res_plan.warnings)

    # Plan with undefined step reference -> blocker
    plan_bad_step = [
        AbaqusAction(
            action_type="pressure_load",
            model_name="Model-1",
            target="Press",
            parameters={"name": "Press", "step": "NonExistentStep", "region_expression": "a.surfaces['Top']", "magnitude": 50.0},
        )
    ]
    res_bad = preflight_plan(plan_bad_step)
    assert res_bad.passed is False
    assert any(b["name"] == "step_sequence_valid" for b in res_bad.blockers)


def test_classify_mesh_quality_metrics():
    metrics = {
        "max_aspect_ratio": 2.5,
        "min_jacobian": 0.85,
        "max_angular_deviation": 12.0,
        "transition_ratio": 1.2,
        "unsupported_metric_xyz": 42.0,
    }
    classification = classify_mesh_quality_metrics(metrics)
    assert "max_aspect_ratio" in classification["native"]
    assert "min_jacobian" in classification["native"]
    assert "max_angular_deviation" in classification["analysis"]
    assert "transition_ratio" in classification["derived"]
    assert "unsupported_metric_xyz" in classification["unsupported"]
