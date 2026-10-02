"""Comprehensive Failure-Path Matrix Verification according to Section 14."""

import pytest
from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.geometry import RegionReference
from abaqus_ai_agent.validation.preflight import preflight_action
from abaqus_ai_agent.contracts.action import AbaqusAction


def test_failure_path_solver_failed():
    res = evaluate_result_acceptance(
        result_status="error",
        values={"stress": 100.0},
        criteria=[{"name": "s", "value_key": "stress", "operator": "<", "limit": 200.0}],
    )
    assert res.passed is False
    assert res.status == "BLOCKED"
    assert "solver_status:error" in res.failures


def test_failure_path_missing_required_metric():
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"other_val": 1.0},
        criteria=[{"name": "target", "value_key": "target", "operator": "<", "limit": 10.0, "required": True}],
    )
    assert res.passed is False
    assert res.status == "BLOCKED"
    assert any("missing_required_metric:target" in b for b in res.blocked)


def test_failure_path_criterion_exceeded():
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"tip_disp": 5.0},
        criteria=[{"name": "disp", "value_key": "tip_disp", "operator": "<=", "limit": 2.0}],
    )
    assert res.passed is False
    assert res.status == "FAIL"
    assert any("disp" in f for f in res.failures)


def test_failure_path_missing_evidence():
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"disp": 1.0},
        criteria=[{"name": "disp", "value_key": "disp", "operator": "<=", "limit": 2.0}],
        require_evidence=True,
        evidence=None,
    )
    assert res.passed is False
    assert res.status == "BLOCKED"
    assert "missing_required_evidence" in res.blocked


def test_failure_path_mesh_quality_failed():
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"disp": 1.0},
        mesh_quality={"status": "fail"},
    )
    assert res.passed is False
    assert res.status == "FAIL"
    assert "mesh_quality_failed" in res.failures


def test_failure_path_convergence_failed():
    class MockConv:
        converged = False

    res = evaluate_result_acceptance(
        result_status="completed",
        values={"disp": 1.0},
        convergence=MockConv(),
    )
    assert res.passed is False
    assert res.status == "FAIL"
    assert "mesh_convergence_failed" in res.failures


def test_failure_path_preflight_empty_region():
    # Empty RegionReference should be caught during preflight
    empty_region = RegionReference(name="Empty", expression="", is_empty=True, entity_type="CELL")
    action = AbaqusAction(
        action_type="concentrated_force",
        model_name="Model-1",
        target=None,
        parameters={"name": "Load-1", "region_ref": empty_region, "cf2": -100.0},
    )
    pre = preflight_action(action)
    assert pre.passed is False
    assert any("empty" in str(b).lower() or "missing" in str(b).lower() or "region" in str(b).lower() for b in pre.blockers)


def test_failure_path_preflight_nan_load():
    action = AbaqusAction(
        action_type="concentrated_force",
        model_name="Model-1",
        target=None,
        parameters={"name": "Load-1", "region_expression": "faces[0]", "cf2": float("nan")},
    )
    pre = preflight_action(action)
    assert pre.passed is False
    assert any("nan" in str(b).lower() or "finite" in str(b).lower() for b in pre.blockers)
