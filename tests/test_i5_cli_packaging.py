"""Tests for Phase I.5 Packaging, CLI Entrypoints & Runtime Capability Fallback."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch
import pytest

from abaqus_ai_agent.cli import main

ROOT = Path(__file__).resolve().parent.parent


def test_cli_inspect_json(capsys):
    ret = main(["inspect", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "launcher" in data
    assert "runtime_mode" in data
    assert data["runtime_mode"] in ("LIVE_ABAQUS_SOLVER", "LAUNCHER_DETECTED_NO_LICENSE", "HEADLESS_CONTRACT_FALLBACK")
    assert "launcher_found" in data
    assert "version_probe_ok" in data
    assert "runtime_startable" in data
    assert "license_verified" in data
    assert "solver_submit_capable" in data
    assert "python_version" in data
    assert "workdir_writable" in data
    assert data["workdir_writable"] is True


def test_cli_inspect_failure_probe_does_not_spoof_license(capsys):
    """When launcher exists but information=release returns non-zero, license must not be ok!"""
    with patch("shutil.which", return_value="C:\\fake\\abaqus.bat"):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "License initialization failed: FlexNet Error -15"
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            ret = main(["inspect", "--json"])
            assert ret == 0
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert data["launcher_found"] is True
            assert data["version_probe_ok"] is False
            assert data["runtime_startable"] is False
            assert data["license_verified"] is False
            assert data["solver_submit_capable"] is False
            assert data["runtime_mode"] == "LAUNCHER_DETECTED_NO_LICENSE"


def test_cli_inspect_success_probe_enables_live_solver(capsys):
    """When launcher exists and information=release returns 0 without license error, solver capable is True."""
    with patch("shutil.which", return_value="C:\\SIMULIA\\Commands\\abaqus.bat"):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Abaqus 2025 Release Candidate 1\nSIMULIA Licensing active"
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            ret = main(["inspect", "--json"])
            assert ret == 0
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert data["launcher_found"] is True
            assert data["version_probe_ok"] is True
            assert data["runtime_startable"] is True
            assert data["license_verified"] is True
            assert data["solver_submit_capable"] is True
            assert data["runtime_mode"] == "LIVE_ABAQUS_SOLVER"


def test_cli_subprocess_packaging_smoke():
    """Verify package CLI can be invoked in a real standalone subprocess."""
    proc = subprocess.run(
        [sys.executable, "-m", "abaqus_ai_agent.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "abaqus-ai-agent" in proc.stdout or "usage:" in proc.stdout
    assert "inspect" in proc.stdout
    assert "ask" in proc.stdout

    proc_inspect = subprocess.run(
        [sys.executable, "-m", "abaqus_ai_agent.cli", "inspect", "--json"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc_inspect.returncode == 0
    data = json.loads(proc_inspect.stdout)
    assert "runtime_mode" in data
    assert "python_version" in data


def test_cli_ask_dry_run_json(capsys):
    prompt = "对100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm。"
    ret = main(["ask", prompt, "--dry-run", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "intent" in data
    assert data["intent"]["analysis_type"] == "linear_static"
    assert data["intent"]["unit_system"] == "MM_N_MPA"
    assert "jev_decision_bundle" in data
    assert data["jev_decision_bundle"]["is_well_constrained_noul"]["is_yes"] is True


def test_cli_ask_text_output(capsys):
    # Fully specified prompt routes cleanly
    prompt = "100mm 1D steady heat conduction steel bar with cold end 0C and hot end 100C. 校核中点温度不超过50C。"
    ret = main(["ask", prompt, "--dry-run"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "=== JEV-Powered Engineering Intent Routing ===" in captured.out
    assert "steady_thermal" in captured.out
    assert "[DRY-RUN]" in captured.out

    # Ambiguous prompt returns 2 and informs user of missing prerequisites
    ambiguous = "1D steady heat conduction problem."
    ret_ambig = main(["ask", ambiguous, "--dry-run"])
    assert ret_ambig == 2
    captured_ambig = capsys.readouterr()
    assert "NEEDS CLARIFICATION" in captured_ambig.out
    assert "BLOCKED (Fail-Closed)" in captured_ambig.out
