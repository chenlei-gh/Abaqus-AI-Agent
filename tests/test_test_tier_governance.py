"""Unit tests for Phase 3.4 test tier governance and marker isolation contracts."""

import json
from pathlib import Path
import pytest


def test_marker_partition_and_isolation(request):
    """Tier 1 (unit) markers must be strictly exclusive of smoke, acceptance, and live markers.

    Guarantees that `pytest -m unit` never runs or pollutes integration/smoke/acceptance suites.
    """
    session = request.node.session
    unit_count = 0
    smoke_count = 0
    acceptance_count = 0
    live_count = 0

    for item in session.items:
        markers = {m.name for m in item.iter_markers()}
        is_unit = "unit" in markers
        is_smoke = "smoke" in markers
        is_acceptance = "acceptance" in markers
        is_live = "live" in markers

        if is_unit:
            unit_count += 1
            # Contract: A unit test must NOT be tagged with smoke, acceptance, or live
            assert not is_smoke, f"Test {item.nodeid} has both unit and smoke markers!"
            assert not is_acceptance, f"Test {item.nodeid} has both unit and acceptance markers!"
            assert not is_live, f"Test {item.nodeid} has both unit and live markers!"

        if is_smoke:
            smoke_count += 1

        if is_acceptance:
            acceptance_count += 1

        if is_live:
            live_count += 1
            # Contract: A live test must also be marked acceptance, but NEVER unit
            assert is_acceptance, f"Live test {item.nodeid} must be marked acceptance!"
            assert not is_unit, f"Live test {item.nodeid} must NOT have unit marker!"

    assert unit_count > 0, "Expected at least one unit test collected"


def test_live_environment_probe_contract():
    """Verify that the physical Abaqus environment probe returns valid four-state diagnostic codes."""
    from tests.conftest import _probe_physical_abaqus_environment

    code, ready, message = _probe_physical_abaqus_environment()

    assert code in {
        "LAUNCHER_MISSING",
        "LAUNCHER_FOUND_PROBE_FAILED",
        "LICENSE_UNAVAILABLE",
        "LAUNCHER_READY",
        "ENVIRONMENT_READY",
        "SMOKE_SOLVE_PASSED",
    }
    assert isinstance(ready, bool)
    assert isinstance(message, str) and len(message) > 0


def test_live_gate_audit_logging(tmp_path, monkeypatch):
    """Verify that blocked live tests produce an auditable JSON trace in runs/live_environment_gate.json."""
    from tests.conftest import _record_live_gate_audit

    repo_root = Path(__file__).resolve().parent.parent
    gate_file = repo_root / "runs" / "live_environment_gate.json"

    # Record a synthetic blocked event
    test_node = "tests/test_synthetic.py::test_blocked_case"
    _record_live_gate_audit(
        nodeid=test_node,
        test_name="test_blocked_case",
        verdict="BLOCKED",
        probe_status="LAUNCHER_MISSING",
        reason="Synthetic test probe launcher missing",
    )

    assert gate_file.exists(), "live_environment_gate.json was not created"
    records = json.loads(gate_file.read_text(encoding="utf-8"))
    assert test_node in records
    assert records[test_node]["verdict"] == "BLOCKED"
    assert records[test_node]["probe_status"] == "LAUNCHER_MISSING"
