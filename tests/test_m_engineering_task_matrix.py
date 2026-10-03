"""Tests for R5: Engineering Task Acceptance Matrix (T1–T6)."""

from pathlib import Path
from tools.m_engineering_task_matrix import (
    run_all_engineering_tasks,
    run_t1_static_strength_and_fos,
    run_t2_coupled_thermal_stress,
    run_t3_contact_tribology,
    run_t4_plastic_residual_stress,
    run_t5_dynamic_energy_balance,
    run_t6_diagnostics_and_self_healing,
)

ROOT = Path(__file__).resolve().parent.parent


def test_t1_static_strength_and_fos():
    res = run_t1_static_strength_and_fos()
    assert res.passed is True
    assert res.metrics["factor_of_safety"] >= 1.5
    assert res.metrics["tip_displacement_mm"] <= 1.0


def test_t2_coupled_thermal_stress():
    res = run_t2_coupled_thermal_stress()
    assert res.passed is True
    assert abs(res.metrics["thermal_stress_mpa"]) <= 250.0
    assert res.metrics["reaction_force_n"] > 0


def test_t3_contact_tribology():
    res = run_t3_contact_tribology()
    assert res.passed is True
    assert res.metrics["contact_pressure_mpa"] == 2.5
    assert res.metrics["tangential_shear_force_n"] == 1500.0


def test_t4_plastic_residual_stress():
    res = run_t4_plastic_residual_stress()
    assert res.passed is True
    assert res.metrics["residual_plastic_strain"] > 0.009
    assert res.metrics["peak_stress_mpa"] == 420.0


def test_t5_dynamic_energy_balance():
    res = run_t5_dynamic_energy_balance()
    assert res.passed is True
    assert res.metrics["energy_discrepancy_rel"] <= 1e-4


def test_t6_diagnostics_and_self_healing():
    res = run_t6_diagnostics_and_self_healing()
    assert res.passed is True
    assert res.metrics["healed_solver_exit_code"] == 0
    assert res.metrics["final_equilibrium_residual"] <= 1e-4


def test_run_all_engineering_tasks_manifest():
    manifest = run_all_engineering_tasks()
    assert manifest["schema_version"] == "engineering_task_matrix_v1"
    assert manifest["total_tasks"] == 6
    assert manifest["passed_tasks"] == 6
    assert manifest["all_passed"] is True

    ev_path = ROOT / "machine_validation" / "m_engineering_task_evidence.json"
    assert ev_path.exists()
