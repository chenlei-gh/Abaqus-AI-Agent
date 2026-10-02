"""Tests for Phase I.5 Packaging, CLI Entrypoints & Runtime Capability Fallback."""

from __future__ import annotations

import json
from pathlib import Path
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
    assert data["runtime_mode"] in ("LIVE_ABAQUS", "HEADLESS_CONTRACT_FALLBACK")
    assert "python_version" in data
    assert "workdir_writable" in data
    assert data["workdir_writable"] is True


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
    prompt = "1D steady heat conduction problem with cold end 0C and hot end 100C."
    ret = main(["ask", prompt, "--dry-run"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "=== JEV-Powered Engineering Intent Routing ===" in captured.out
    assert "steady_thermal" in captured.out
    assert "[DRY-RUN]" in captured.out
