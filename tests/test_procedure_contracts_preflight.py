"""GA-2.6.0 Unit tests for Multi-Step Procedure contracts, lifecycle rules and AST preflight guards."""

import pytest
from abaqus_ai_agent.contracts.procedure import (
    BoltPretensionMethod,
    BoltPretensionLifecycleSpec,
    MomentTransferStrategy,
    MomentLoadSpec,
    SpatialLoadField,
    StepDependency,
    MultiStepProcedureSpec,
    validate_field_expression,
)
from abaqus_ai_agent.actions import builders
from abaqus_ai_agent.contracts.action import AbaqusAction
from abaqus_ai_agent.validation.preflight import preflight_action, preflight_plan


# ---------------------------------------------------------------------------
# 1. Multi-Step Procedure DAG & nlgeom Safety
# ---------------------------------------------------------------------------

def test_multi_step_procedure_dag_validation_success():
    spec = MultiStepProcedureSpec(
        steps=(
            StepDependency(name="Step-Preload", previous="Initial", procedure="static", nlgeom=True, time_period=0.5),
            StepDependency(name="Step-Service", previous="Step-Preload", procedure="static", nlgeom=True, time_period=1.0),
        )
    )
    ok, errors = spec.validate_dag()
    assert ok is True
    assert len(errors) == 0


def test_multi_step_procedure_dag_undefined_parent():
    spec = MultiStepProcedureSpec(
        steps=(
            StepDependency(name="Step-Service", previous="NonExistentStep", procedure="static"),
        )
    )
    ok, errors = spec.validate_dag()
    assert ok is False
    assert any("references previous step 'NonExistentStep'" in e for e in errors)


def test_multi_step_procedure_dag_duplicate_step():
    with pytest.raises(ValueError, match="duplicate step name"):
        MultiStepProcedureSpec(
            steps=(
                StepDependency(name="Step-1", previous="Initial"),
                StepDependency(name="Step-1", previous="Step-1"),
            )
        )


def test_multi_step_procedure_dag_nlgeom_conflict_safety():
    # Attempting to turn nlgeom=False after it was enabled in an earlier step triggers safety conflict
    spec = MultiStepProcedureSpec(
        steps=(
            StepDependency(name="Step-1", previous="Initial", nlgeom=True),
            StepDependency(name="Step-2", previous="Step-1", nlgeom=False),
        )
    )
    ok, errors = spec.validate_dag()
    assert ok is False
    assert any("Safety conflict" in e and "attempts to disable nlgeom" in e for e in errors)


# ---------------------------------------------------------------------------
# 2. SpatialLoadField AST Whitelist Safety
# ---------------------------------------------------------------------------

def test_spatial_load_field_ast_whitelist_success():
    valid_expressions = [
        "100.0",
        "100.0 + 5.0 * Y",
        "X + Y + Z",
        "2.5 * (X - 10.0) / 4.0",
        "X**2 + Y**2",
        "-1.5 * z + 3.0",
    ]
    for expr in valid_expressions:
        field = SpatialLoadField(name="PressureField", expression=expr)
        assert field.name == "PressureField"
        assert field.expression == expr

        ok, err = validate_field_expression(expr)
        assert ok is True
        assert err is None


def test_spatial_load_field_ast_whitelist_prohibitions():
    disallowed_expressions = [
        "",                                    # empty
        "   ",                                 # whitespace
        "os.system('calc')",                   # attribute and call
        "__import__('os').system('ls')",       # dangerous import
        "X.__class__.__bases__",               # dunder attribute escape
        "sin(X)",                              # arbitrary function call
        "A + B",                               # disallowed variable names
        "X[0] + Y",                            # subscripting
        "[x for x in (1, 2)]",                 # list comprehension
        "lambda x: x + 1",                     # lambda
        "1 + ",                                # syntax error
    ]
    for expr in disallowed_expressions:
        ok, err = validate_field_expression(expr)
        assert ok is False, f"Expression '{expr}' should be rejected"
        assert err is not None

        with pytest.raises(ValueError, match="Invalid field expression"):
            SpatialLoadField(name="BadField", expression=expr)


# ---------------------------------------------------------------------------
# 3. Bolt Pretension Lifecycle Contracts and Preflight
# ---------------------------------------------------------------------------

def test_bolt_pretension_lifecycle_contract_validations():
    valid_bolt = BoltPretensionLifecycleSpec(
        name="Bolt-1",
        region_expression="a.surfaces['BoltSurf']",
        preload_magnitude=5000.0,
        preload_step="Step-Preload",
        service_step="Step-Service",
        direction_vector=(0.0, 0.0, 1.0),
    )
    assert valid_bolt.preload_magnitude == 5000.0

    # Negative magnitude rejected
    with pytest.raises(ValueError, match="preload_magnitude must be positive"):
        BoltPretensionLifecycleSpec(
            name="Bolt-1",
            region_expression="a.surfaces['BoltSurf']",
            preload_magnitude=-100.0,
        )

    # Initial step as preload rejected
    with pytest.raises(ValueError, match="preload_step cannot be 'Initial'"):
        BoltPretensionLifecycleSpec(
            name="Bolt-1",
            region_expression="a.surfaces['BoltSurf']",
            preload_magnitude=100.0,
            preload_step="Initial",
        )


def test_bolt_pretension_lifecycle_preflight_plan_success():
    plan = [
        builders.fixed_bc("Model-1", "FixRoot", "a.sets['Root']", step="Initial"),
        builders.static_step("Model-1", name="Step-Preload", previous="Initial", nlgeom=True),
        builders.bolt_load(
            "Model-1",
            name="Bolt-1",
            region_expression="a.surfaces['BoltSurf']",
            magnitude=8000.0,
            step="Step-Preload",
            bolt_method=BoltPretensionMethod.APPLY_FORCE.value,
        ),
        builders.static_step("Model-1", name="Step-Service", previous="Step-Preload", nlgeom=True),
        builders.bolt_load_set_values(
            "Model-1",
            name="Bolt-1",
            step="Step-Service",
            bolt_method=BoltPretensionMethod.FIX_LENGTH.value,
        ),
        builders.pressure_load("Model-1", "ExtPressure", "a.surfaces['Top']", magnitude=50.0, step="Step-Service"),
    ]
    res = preflight_plan(plan)
    assert res.passed is True
    assert len(res.blockers) == 0


def test_bolt_pretension_lifecycle_preflight_fail_closed():
    # 1. Calling FIX_LENGTH without prior APPLY_FORCE
    plan_no_prior_apply = [
        builders.fixed_bc("Model-1", "FixRoot", "a.sets['Root']", step="Initial"),
        builders.static_step("Model-1", name="Step-Service", previous="Initial"),
        builders.bolt_load_set_values(
            "Model-1",
            name="Bolt-1",
            step="Step-Service",
            bolt_method="FIX_LENGTH",
        ),
    ]
    res1 = preflight_plan(plan_no_prior_apply)
    assert res1.passed is False
    assert any("has not been defined in prior steps" in str(b) for b in res1.blockers)

    # 2. bolt_load with negative magnitude
    bad_bolt_action = builders.bolt_load(
        "Model-1",
        name="Bolt-1",
        region_expression="a.surfaces['BoltSurf']",
        magnitude=-500.0,
        step="Step-Preload",
    )
    res2 = preflight_action(bad_bolt_action)
    assert res2.passed is False
    assert any(b["name"] == "bolt_preload_magnitude_positive" for b in res2.blockers)

    # 3. bolt_load assigned to 'Initial' step
    bad_step_bolt = builders.bolt_load(
        "Model-1",
        name="Bolt-1",
        region_expression="a.surfaces['BoltSurf']",
        magnitude=500.0,
        step="Initial",
    )
    res3 = preflight_action(bad_step_bolt)
    assert res3.passed is False
    assert any(b["name"] == "step_not_initial" for b in res3.blockers)


# ---------------------------------------------------------------------------
# 4. Concentrated Moment and Strategy Contracts
# ---------------------------------------------------------------------------

def test_concentrated_moment_contract_and_preflight():
    spec = MomentLoadSpec(
        name="TipTorque",
        region_expression="a.surfaces['TipFace']",
        magnitude=2500.0,
        axis="CM3",
        strategy=MomentTransferStrategy.RP_COUPLING,
    )
    assert spec.name == "TipTorque"
    assert spec.strategy == MomentTransferStrategy.RP_COUPLING

    # Invalid axis
    with pytest.raises(ValueError, match="invalid moment axis"):
        MomentLoadSpec(name="Bad", region_expression="a.surfaces['Tip']", magnitude=10.0, axis="FX")

    # Preflight action valid
    act_ok = builders.concentrated_moment(
        "Model-1",
        name="Torque-1",
        region_expression="a.sets['RP_Set']",
        cm3=1500.0,
        step="Step-1",
        strategy="RP_COUPLING",
    )
    res_ok = preflight_action(act_ok)
    assert res_ok.passed is True

    # Preflight action invalid strategy
    act_bad_strat = builders.concentrated_moment(
        "Model-1",
        name="Torque-1",
        region_expression="a.sets['RP_Set']",
        cm3=1500.0,
        step="Step-1",
        strategy="UNKNOWN_STRATEGY",
    )
    res_bad = preflight_action(act_bad_strat)
    assert res_bad.passed is False
    assert any(b["name"] == "moment_strategy_valid" for b in res_bad.blockers)


# ---------------------------------------------------------------------------
# 5. ExpressionField Action Preflight AST Guard
# ---------------------------------------------------------------------------

def test_expression_field_action_preflight_ast_guard():
    # Valid safe field action
    safe_field = builders.expression_field("Model-1", name="P_Linear", expression="100.0 + 2.0 * Y")
    res_safe = preflight_action(safe_field)
    assert res_safe.passed is True

    # Unsafe field action containing system call attempt
    unsafe_field = builders.expression_field("Model-1", name="P_Injected", expression="__import__('os').system('ls')")
    res_unsafe = preflight_action(unsafe_field)
    assert res_unsafe.passed is False
    assert any(b["name"] == "expression_field_safe_ast" for b in res_unsafe.blockers)


# ---------------------------------------------------------------------------
# 6. Plan-level DAG Sequence & nlgeom Safety Blockers
# ---------------------------------------------------------------------------

def test_preflight_plan_dag_and_nlgeom_safety_blocker():
    # 1. Step defined referencing a step that has not been defined yet
    plan_out_of_order = [
        builders.static_step("Model-1", name="Step-2", previous="Step-1"),
        builders.static_step("Model-1", name="Step-1", previous="Initial"),
    ]
    res_order = preflight_plan(plan_out_of_order)
    assert res_order.passed is False
    assert any(
        "references previous step 'Step-1' before it is defined" in str(b["detail"])
        for b in res_order.blockers
    )

    # 2. Plan attempting to turn nlgeom from True to False across steps
    plan_nlgeom_downgrade = [
        builders.static_step("Model-1", name="Step-1", previous="Initial", nlgeom=True),
        builders.static_step("Model-1", name="Step-2", previous="Step-1", nlgeom=False),
    ]
    res_nlgeom = preflight_plan(plan_nlgeom_downgrade)
    assert res_nlgeom.passed is False
    assert any(
        b["name"] == "nlgeom_conflict_safety" and "attempts to disable nlgeom" in str(b["detail"])
        for b in res_nlgeom.blockers
    )
