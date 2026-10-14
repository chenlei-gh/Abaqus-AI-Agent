"""Tests for Production Delivery Full-Chain Acceptance Contracts and Tooling (REQ-ISO-002, REQ-P1-036)."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import pytest

from abaqus_ai_agent.paths import (
    ExternalProjectContext,
    get_repo_root,
)
from abaqus_ai_agent.execution.solver import find_abaqus_executable
from tools.production_delivery_e2e import (
    build_production_delivery_cae_script,
    run_production_delivery_e2e,
)


def test_production_delivery_script_generation(tmp_path: Path):
    """Verify that build_production_delivery_cae_script generates valid, parseable Python syntax."""
    project_root = tmp_path / "mock_project_root"
    project_root.mkdir(parents=True)
    code = build_production_delivery_cae_script(project_root=project_root)

    # Must be syntactically valid Python code
    parsed = ast.parse(code)
    assert isinstance(parsed, ast.Module)

    # Must contain essential production-grade architectural contracts
    assert "require_production=True" in code
    assert "ExternalProjectContext.create" in code
    assert "CantileverProductionDelivery" in code
    assert "reaction_balance_from_field_evidence" in code
    assert "AIAgent_PROD_DELIVERY_RESULT_BEGIN" in code
    assert "AIAgent_PROD_DELIVERY_RESULT_END" in code


def test_production_delivery_context_isolation_contracts():
    """Verify that ExternalProjectContext strictly rejects repository-internal roots in production."""
    repo_root = get_repo_root()
    internal_target = repo_root / "runs" / "unauthorized_production_root"

    with pytest.raises((PermissionError, ValueError), match="escapes external root|Security violation|outside repository"):
        ExternalProjectContext.create(
            project_root=internal_target,
            project_name="ViolatingProject",
            enforce_outside_repo=True,
        )


def test_production_delivery_launcher_missing_fails_closed(tmp_path: Path):
    """Verify that production delivery execution fails closed if launcher is missing or invalid."""
    with pytest.raises(RuntimeError, match="Authentic Abaqus launcher not found"):
        run_production_delivery_e2e(launcher="non_existent_abaqus_binary_xyz_123")


@pytest.mark.skipif(
    not bool(find_abaqus_executable()),
    reason="Authentic SIMULIA Abaqus launcher required on host for live production delivery e2e",
)
def test_production_delivery_live_e2e_gate():
    """Live full-chain acceptance gate running against authentic Abaqus 2025."""
    report = run_production_delivery_e2e(timeout=1800)
    assert report["status"] == "pass"
    assert report["run_state"].lower() == "accepted"
    assert report["engineering_status"] == "RESULT_VALID"
    assert report["deliverable"] is True
    assert report["acceptance_status"] == "PASS"
    assert report["result_validity"] == "VALID"
    assert report["reaction_balance_passed"] is True
