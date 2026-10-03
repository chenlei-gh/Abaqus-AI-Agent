"""Tests for R2: Mesh Engineering Gate."""

import pytest
from abaqus_ai_agent.mesh_gate import (
    classify_element_type,
    evaluate_mesh_quality_gate,
    evaluate_mesh_convergence_gate,
)
from abaqus_ai_agent.contracts.mesh_quality import MeshQualityPolicy


def test_classify_element_families():
    c3d8r = classify_element_type("C3D8R")
    assert c3d8r.is_valid is True
    assert c3d8r.family == "CONTINUUM_3D"
    assert c3d8r.is_reduced_integration is True

    c3d10 = classify_element_type("C3D10")
    assert c3d10.family == "CONTINUUM_3D"
    assert c3d10.is_second_order is True

    s4r = classify_element_type("S4R")
    assert s4r.family == "SHELL"

    b31 = classify_element_type("B31")
    assert b31.family == "BEAM_TRUSS"

    unknown = classify_element_type("NONEXISTENT_ELEM")
    assert unknown.is_valid is False
    assert unknown.family == "UNKNOWN"


def test_evaluate_mesh_quality_gate_clean():
    metrics = {
        "max_aspect_ratio": 2.5,
        "min_jacobian": 0.85,
        "min_angle": 35.0,
        "max_angle": 130.0,
    }
    eval_res = evaluate_mesh_quality_gate(metrics)
    assert eval_res.status == "PASS"
    assert eval_res.passed is True
    assert len(eval_res.violations) == 0


def test_evaluate_mesh_quality_gate_negative_jacobian_blocked():
    # Inverted element with negative Jacobian
    metrics = {
        "max_aspect_ratio": 3.0,
        "min_jacobian": -0.05,
        "min_angle": 25.0,
        "max_angle": 140.0,
    }
    eval_res = evaluate_mesh_quality_gate(metrics)
    assert eval_res.status == "BLOCKED"
    assert eval_res.passed is False
    assert any("min_jacobian" in v for v in eval_res.violations)
    assert any("Inverted element" in v for v in eval_res.violations)


def test_evaluate_mesh_quality_gate_extreme_distortion_blocked():
    metrics = {
        "max_aspect_ratio": 65.0,  # Extreme elongation > 50.0
        "min_jacobian": 0.4,
        "min_angle": 3.0,          # Extreme corner pin < 5.0 deg
        "max_angle": 178.0,        # Extreme corner flatness > 175.0 deg
    }
    eval_res = evaluate_mesh_quality_gate(metrics)
    assert eval_res.status == "BLOCKED"
    assert eval_res.passed is False
    assert len(eval_res.violations) >= 2


def test_evaluate_mesh_quality_gate_moderate_warning():
    metrics = {
        "max_aspect_ratio": 25.0,  # > policy 20.0 but < 50.0
        "min_jacobian": 0.05,      # < policy 0.1 but > 0.0
        "min_angle": 8.0,          # < policy 10.0 but > 5.0
        "max_angle": 160.0,
    }
    eval_res = evaluate_mesh_quality_gate(metrics)
    assert eval_res.status == "WARNING"
    assert eval_res.passed is True
    assert len(eval_res.warnings) >= 1
    assert len(eval_res.violations) == 0


def test_evaluate_mesh_convergence_gate():
    sizes = [10.0, 5.0, 2.5]
    # Responses converging asymptotically: 2.00, 2.05, 2.0625
    responses = [2.000, 2.050, 2.0625]
    res = evaluate_mesh_convergence_gate(sizes, responses, tolerance=0.01)
    assert res.passed is True
    assert res.status in ("CONVERGED", "MONOTONIC_CONVERGENT")
    assert res.relative_change < 0.01
