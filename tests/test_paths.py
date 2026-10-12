"""Tests for canonical workspace paths resolution contracts."""

import os
from pathlib import Path
import pytest

from abaqus_ai_agent.paths import (
    ENV_RUNS_DIR,
    ENV_DELIVERABLES_DIR,
    ENV_VALIDATION_ASSETS_DIR,
    get_repo_root,
    resolve_runs_root,
    resolve_deliverables_root,
    resolve_validation_assets_root,
    create_run_workdir,
)


def test_get_repo_root_detects_project():
    root = get_repo_root()
    assert root.is_dir()
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "abaqus_ai_agent").is_dir()


def test_resolve_runs_root_default(monkeypatch):
    monkeypatch.delenv(ENV_RUNS_DIR, raising=False)
    root = get_repo_root()
    runs_dir = resolve_runs_root()
    assert runs_dir == (root / "runs").resolve()


def test_resolve_runs_root_env_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom_runs"
    monkeypatch.setenv(ENV_RUNS_DIR, str(custom))
    assert resolve_runs_root() == custom.resolve()


def test_resolve_runs_root_explicit_param(monkeypatch, tmp_path):
    env_dir = tmp_path / "env_runs"
    explicit_dir = tmp_path / "explicit_runs"
    monkeypatch.setenv(ENV_RUNS_DIR, str(env_dir))
    assert resolve_runs_root(override=explicit_dir) == explicit_dir.resolve()


def test_resolve_deliverables_root_default(monkeypatch):
    monkeypatch.delenv(ENV_DELIVERABLES_DIR, raising=False)
    root = get_repo_root()
    deliv_dir = resolve_deliverables_root()
    assert deliv_dir == (root / "deliverables").resolve()


def test_resolve_deliverables_root_override(monkeypatch, tmp_path):
    target = tmp_path / "official_deliverables"
    monkeypatch.setenv(ENV_DELIVERABLES_DIR, str(target))
    assert resolve_deliverables_root() == target.resolve()
    explicit = tmp_path / "another_target"
    assert resolve_deliverables_root(override=explicit) == explicit.resolve()


def test_resolve_validation_assets_root_fallback(monkeypatch):
    monkeypatch.delenv(ENV_VALIDATION_ASSETS_DIR, raising=False)
    val_dir = resolve_validation_assets_root()
    assert val_dir.is_dir()
    # Should resolve to either validation_assets or fallback to machine_validation
    assert val_dir.name in ("validation_assets", "machine_validation")


def test_resolve_validation_assets_root_override(monkeypatch, tmp_path):
    custom_val = tmp_path / "custom_val"
    monkeypatch.setenv(ENV_VALIDATION_ASSETS_DIR, str(custom_val))
    assert resolve_validation_assets_root() == custom_val.resolve()


def test_create_run_workdir(tmp_path):
    run_id = "test-run-12345"
    workdir = create_run_workdir(run_id, runs_root=tmp_path)
    assert workdir.is_dir()
    assert workdir == (tmp_path / run_id).resolve()


def test_analysis_runner_respects_external_runs_dir(monkeypatch, tmp_path):
    external_runs = tmp_path / "ext_runs"
    monkeypatch.setenv(ENV_RUNS_DIR, str(external_runs))

    from abaqus_ai_agent.execution.analysis_run import AnalysisRunner

    class DummyExecutor:
        workdir = None

    executor = DummyExecutor()
    runner = AnalysisRunner(executor)
    run = runner.run(model_name="TestModel", job_name="Job-Test")
    # Verify that the run directory was created inside external_runs
    created_run_dir = external_runs / run.id
    assert created_run_dir.is_dir()


def test_telemetry_tracker_respects_external_runs_dir(monkeypatch, tmp_path):
    external_runs = tmp_path / "ext_runs"
    monkeypatch.setenv(ENV_RUNS_DIR, str(external_runs))

    from abaqus_ai_agent.telemetry.tracker import ContextTelemetryTracker

    tracker = ContextTelemetryTracker(case_id="case_01", run_id="run_999")
    assert tracker.output_dir.resolve().is_relative_to(external_runs.resolve())
    assert tracker.calls_dir.is_dir()
