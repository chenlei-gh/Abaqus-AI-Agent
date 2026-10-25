"""Offline contract tests for the T-P4 500k Explicit benchmark evidence.

These tests never launch Abaqus. They lock the recorded model identity,
terminal-state evidence, scaling arithmetic, mode/domain mapping and the
corrected increment count so a future edit cannot silently drift.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "machine_validation" / "tp4_explicit_500k_parallel_benchmark.json"


def _load() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def _config(data: dict, mode: str, cpus: int) -> dict:
    return next(c for c in data["configs"] if c["mode"] == mode and c["cpus"] == cpus)


def test_model_and_run_inventory():
    data = _load()
    assert data["model"]["elements"] == 503500
    assert data["model"]["nodes"] == 531003
    assert data["model"]["element_type"] == "C3D8R"
    assert data["model"]["plate_mesh"] == "180x90x30"
    assert data["model"]["plate_mesh_original"] == "100x50x30"
    assert data["validation"]["run_count"] == 15
    assert data["validation"]["timed_run_count"] == 14
    assert len(data["configs"]) == 7
    assert len(data["runs"]) == 15
    for name in ("erode_500k.inp", "erode_material.inp", "build_500k.py"):
        assert len(data["model"]["input_files"][name]["sha256"]) == 64


def test_all_runs_completed_with_authentic_odb_and_measured_timing():
    data = _load()
    assert data["validation"]["all_terminal_states_completed"] is True
    assert data["validation"]["terminal_state_counts"] == {"COMPLETED": 15}
    assert data["validation"]["all_odb_authentic"] is True
    assert data["validation"]["all_timing_measured"] is True
    for run in data["runs"]:
        assert run["terminal_state"] == "COMPLETED"
        assert run["terminal_evidence"]
        assert run["returncode"] == 0
        assert run["odb_authentic"] is True
        assert run["solver_timing_status"] == "measured"
        assert run["solver_phase_s"] is not None
        assert run["increments"] in (2100, 2109, 2116, 2131)


def test_scaling_arithmetic_is_consistent():
    data = _load()
    base = _config(data, "default", 1)
    for c in data["configs"]:
        expected_speedup = base["solver_phase_median_s"] / c["solver_phase_median_s"]
        assert c["speedup_solver_phase"] == pytest.approx(expected_speedup, abs=0.001)
        expected_eff = expected_speedup / c["cpus"]
        assert c["parallel_efficiency"] == pytest.approx(expected_eff, abs=0.001)
        expected_elapsed = base["elapsed_median_s"] / c["elapsed_median_s"]
        assert c["speedup_elapsed"] == pytest.approx(expected_elapsed, abs=0.001)


def test_increment_normalized_speedup_accounts_for_domain_dependent_increments():
    data = _load()
    base = _config(data, "default", 1)
    base_rate = base["solver_phase_median_s"] / base["increments_median"]
    for c in data["configs"]:
        rate = c["solver_phase_median_s"] / c["increments_median"]
        assert c["increment_normalized_speedup"] == pytest.approx(base_rate / rate, abs=0.002)
    assert _config(data, "default", 8)["increment_normalized_speedup"] > 1.0
    assert _config(data, "threads", 8)["increment_normalized_speedup"] > 1.0


def test_mode_and_domain_mapping_matches_requested_commands():
    data = _load()
    baseline = _config(data, "default", 1)
    assert baseline["mp_mode"] == ["THREADS", "THREADS"]
    assert baseline["domains"] == [1, 1]
    for cpus in (2, 4, 8):
        default = _config(data, "default", cpus)
        threads = _config(data, "threads", cpus)
        assert default["mp_mode"] == ["MPI", "MPI"]
        assert default["domains"] == [cpus, cpus]
        assert threads["mp_mode"] == ["THREADS", "THREADS"]
        assert threads["domains"] == [cpus, cpus]
        assert default["solver_phase_median_s"] > 0
        assert threads["solver_phase_median_s"] > 0


def test_500k_scale_up_records_corrected_increment_count():
    data = _load()
    context = data["scale_up_context"]
    assert context["stage1_167_5k"]["increments"] == 1595
    assert context["stage3_500k"]["increments"] == 2131
    correction = context["metadata_correction"]
    assert correction["previous_increments"] == 10501
    assert correction["corrected_increments"] == 1595
    assert "node ID" in correction["reason"]
    assert 10501 not in {run["increments"] for run in data["runs"]}


def test_observed_multicore_conclusion_is_not_a_single_core_cap():
    data = _load()
    default8 = _config(data, "default", 8)
    threads8 = _config(data, "threads", 8)
    assert default8["speedup_solver_phase"] > 1.1
    assert threads8["speedup_solver_phase"] > 1.1
    assert threads8["speedup_solver_phase"] > default8["speedup_solver_phase"]
    assert data["production_code"]["explicit_single_core_cap_implemented"] is False
    assert "Explicit must use 1 CPU" in "\n".join(data["limitations"]) or "Explicit 一律单核" in "\n".join(data["conclusions"])