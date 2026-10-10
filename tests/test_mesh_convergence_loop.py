"""Tests for multi-level mesh convergence mathematics and adaptive refinement controller."""

import pytest

from abaqus_ai_agent.contracts.convergence import (
    MultiLevelConvergenceResult,
    evaluate_multi_level_mesh_convergence,
)
from abaqus_ai_agent.contracts.mesh import LocalSeed
from abaqus_ai_agent.planning.compiler import IntentMeshSpec
from abaqus_ai_agent.execution.convergence_loop import (
    AdaptiveConvergenceRun,
    AdaptiveMeshConvergenceController,
)


def test_multi_level_convergence_strictly_converged():
    # Asymptotic converging series (Peterson hole plate simulation)
    # L1: 10mm -> 25.5 MPa
    # L2: 5mm  -> 28.5 MPa (delta = 10.5%)
    # L3: 2.5mm -> 30.2 MPa (delta = 5.6%)
    # L4: 1.25mm -> 31.1 MPa (delta = 2.9% < 5.0%)
    probes = [
        {"peak_s11": 25.5, "max_u1": 0.0520, "rf_error_pct": 0.0000},
        {"peak_s11": 28.5, "max_u1": 0.0528, "rf_error_pct": 0.0000},
        {"peak_s11": 30.2, "max_u1": 0.0531, "rf_error_pct": 0.0000},
        {"peak_s11": 31.1, "max_u1": 0.0533, "rf_error_pct": 0.0000},
    ]

    res = evaluate_multi_level_mesh_convergence(
        probes=probes,
        theory_peak=31.331,
        tolerance=0.05,
    )

    assert res.converged is True
    assert res.status == "CONVERGED"
    assert res.is_monotonic is True
    assert res.diminishing_increment is True
    assert res.final_delta_pct == pytest.approx(2.89, abs=0.1)
    assert res.displacement_converged is True
    assert res.reaction_force_equilibrium_ok is True
    assert res.theory_error_pct is not None
    assert res.theory_error_pct[-1] < 1.0  # L4 is very close to theory limit


def test_multi_level_convergence_asymptotic_approaching():
    # Only 3 levels, final delta is 6.8% (above 5% threshold but diminishing)
    probes = [
        {"peak_s11": 24.0, "max_u1": 0.051, "rf_error_pct": 0.0000},
        {"peak_s11": 27.5, "max_u1": 0.052, "rf_error_pct": 0.0000},
        {"peak_s11": 29.5, "max_u1": 0.0525, "rf_error_pct": 0.0000},
    ]

    res = evaluate_multi_level_mesh_convergence(
        probes=probes,
        tolerance=0.05,
    )

    assert res.converged is False
    assert res.status == "ASYMPTOTIC_APPROACHING"
    assert res.diminishing_increment is True
    assert res.is_monotonic is True
    assert res.final_delta_pct > 5.0


def test_multi_level_convergence_suspected_singularity():
    # Stress diverges wildly (non-diminishing delta, e.g. re-entrant sharp corner)
    probes = [
        {"peak_s11": 100.0, "max_u1": 0.010, "rf_error_pct": 0.0},
        {"peak_s11": 200.0, "max_u1": 0.011, "rf_error_pct": 0.0},
        {"peak_s11": 500.0, "max_u1": 0.0115, "rf_error_pct": 0.0},
    ]

    res = evaluate_multi_level_mesh_convergence(probes=probes, tolerance=0.05)
    assert res.converged is False
    assert res.status == "SINGULARITY_SUSPECTED"


def test_adaptive_mesh_convergence_controller_converges_in_loop():
    base_mesh = IntentMeshSpec(
        global_size=10.0,
        local_seeds=(LocalSeed(region_expression="HoleEdges", size=4.0),),
    )

    controller = AdaptiveMeshConvergenceController(
        base_mesh_spec=base_mesh,
        tolerance=0.05,
        max_levels=4,
        refinement_ratio=0.5,
    )

    # Simulated solver outputs across 4 levels
    stresses = [25.0, 28.5, 30.2, 31.1]
    displacements = [0.052, 0.0528, 0.0531, 0.0533]

    def mock_step_runner(level, mesh_spec):
        idx = level - 1
        probe = {
            "peak_s11": stresses[idx],
            "max_u1": displacements[idx],
            "rf_error_pct": 0.0,
            "level": level,
            "seed_size": mesh_spec.local_seeds[0].size,
        }
        return {"run_id": f"run_lvl_{level}"}, probe

    result = controller.execute_loop(mock_step_runner)
    assert result.is_converged is True
    assert result.status == "CONVERGED"
    assert result.levels_executed == 4
    # Final seed size at level 4: 4.0 * 0.5^3 = 0.5
    assert result.final_mesh_spec.local_seeds[0].size == pytest.approx(0.5)


def test_adaptive_mesh_convergence_controller_budget_exhaustion():
    base_mesh = IntentMeshSpec(global_size=10.0)
    controller = AdaptiveMeshConvergenceController(
        base_mesh_spec=base_mesh,
        tolerance=0.01,  # Strict 1% threshold cannot be reached in 2 levels
        max_levels=2,
    )

    def mock_step_runner(level, mesh_spec):
        probe = {
            "peak_s11": 20.0 + level * 5.0,  # 25.0, 30.0 -> delta ~16.7%
            "max_u1": 0.05,
            "rf_error_pct": 0.0,
        }
        return {"run": level}, probe

    result = controller.execute_loop(mock_step_runner)
    assert result.is_converged is False
    assert result.status == "BUDGET_EXHAUSTED"
    assert result.levels_executed == 2
