"""Tracked evidence must stay byte-identical when pytest runs under the read-only lock.

Several E2E drivers used to rewrite their own committed evidence JSON on import or
invocation, which polluted the working tree on every test run. The guard here is
deliberately byte-level: it catches line-ending churn as well as content changes.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = REPO_ROOT / "machine_validation"


def _snapshot(paths):
    return {p: p.read_bytes() for p in paths}


def test_evidence_writes_locked_environment_is_active():
    assert os.environ.get("ABAQUS_AGENT_EVIDENCE_READONLY") == "1"


def test_run_index_export_manifest_does_not_touch_tracked_manifest():
    from abaqus_ai_agent.run_index import RunIndex

    tracked = EVIDENCE / "case_memory_manifest.json"
    before = tracked.read_bytes()

    manifest = RunIndex().export_manifest(tracked)

    assert manifest["total_runs"] == 0
    assert tracked.read_bytes() == before


def _evidence_files():
    return [
        EVIDENCE / "h5_solver_failure_diagnostics_evidence.json",
        EVIDENCE / "h6_image_intent_grounding_evidence.json",
        EVIDENCE / "h7_sensitivity_uncertainty_evidence.json",
        EVIDENCE / "h8_case_memory_comparison_evidence.json",
        EVIDENCE / "case_memory_manifest.json",
    ]


def test_h5_e2e_leaves_evidence_bytes_unchanged():
    from tools.h5_solver_failure_diagnostics_e2e import run_h5_solver_failure_diagnostics

    before = _snapshot(_evidence_files())
    evidence = run_h5_solver_failure_diagnostics()

    assert evidence["status"] == "PASS"
    for path, payload in _snapshot(_evidence_files()).items():
        assert payload == before[path], f"{path.name} was rewritten during pytest"


def test_h7_e2e_leaves_evidence_bytes_unchanged():
    from tools.h7_sensitivity_uncertainty_e2e import run_h7_sensitivity_uncertainty

    before = _snapshot(_evidence_files())
    evidence = run_h7_sensitivity_uncertainty()

    assert evidence["status"] == "PASS"
    for path, payload in _snapshot(_evidence_files()).items():
        assert payload == before[path], f"{path.name} was rewritten during pytest"


def test_h8_e2e_leaves_evidence_bytes_unchanged():
    from tools.h8_case_memory_comparison_e2e import run_h8_case_memory_comparison

    before = _snapshot(_evidence_files())
    evidence = run_h8_case_memory_comparison()

    assert evidence["status"] == "PASS"
    for path, payload in _snapshot(_evidence_files()).items():
        assert payload == before[path], f"{path.name} was rewritten during pytest"


def test_committed_evidence_files_are_lf_only():
    """A CRLF checkout would silently break every recorded byte count and digest."""
    offenders = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in _evidence_files()
        if b"\r\n" in p.read_bytes()
    ]
    assert offenders == [], f"CRLF found in tracked evidence: {offenders}"
