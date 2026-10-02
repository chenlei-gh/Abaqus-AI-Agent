"""Tests for Phase I.3 Engineering Reproducibility & Tolerance Invariance."""

from __future__ import annotations

import pytest
from pathlib import Path

from tools.i3_reproducibility import (
    compare_reproducibility,
    execute_dual_run_verification,
    execute_live_abaqus_dual_run,
)

ROOT = Path(__file__).resolve().parent.parent


def test_reproducibility_rejects_missing_or_none_run_b():
    """Assert that self-comparison is forbidden and requires an independent Run B."""
    evidence_path = ROOT / "machine_validation" / "static_golden_e2e.json"
    with pytest.raises(ValueError, match="Run B evidence file is strictly required"):
        compare_reproducibility(evidence_path, None, relative_tolerance=1e-4)


def test_reproducibility_on_independent_runs():
    evidence_a = ROOT / "machine_validation" / "static_golden_e2e.json"
    evidence_b = ROOT / "machine_validation" / "static_golden_run_b.json"
    manifest = compare_reproducibility(evidence_a, evidence_b, relative_tolerance=1e-4)

    assert manifest["schema_version"] == "reproducibility_evidence_v1"
    assert manifest["case_id"] == "static_cantilever"
    assert manifest["structural_invariance"]["intent_hash_match"] is True
    assert manifest["acceptance_invariance"]["verdict_match"] is True
    assert manifest["numerical_metrics_evaluated"] >= 3
    assert manifest["all_metrics_within_tolerance"] is True
    assert manifest["reproducibility_verified"] is True


def test_independent_dual_run_reproducibility_invariance():
    """Verify two independently synthesized runs produce exact hash & tolerance invariance."""
    res = execute_dual_run_verification(case_id="CASE-01-STATIC", perturb_run_b=False, relative_tolerance=1e-4)

    assert res.reproducibility_passed is True
    assert res.intent_match is True
    assert res.action_plan_match is True
    assert res.inp_match is True
    assert res.metrics_within_tolerance is True
    assert res.acceptance_match is True
    assert len(res.metric_comparisons) == 2


def test_dual_run_detects_and_rejects_perturbation():
    """Deliberately perturbed run B must fail reproducibility check and highlight disparity."""
    res = execute_dual_run_verification(case_id="CASE-01-STATIC", perturb_run_b=True, relative_tolerance=1e-4)

    # Must FAIL reproducibility
    assert res.reproducibility_passed is False
    assert res.intent_match is False  # Param difference detected in intent
    assert res.action_plan_match is False  # Action plan difference detected
    assert res.inp_match is False  # INP deck difference detected
    assert res.metrics_within_tolerance is False  # Displacement difference (~11%) exceeds 1e-4

    failed_metrics = [m for m in res.metric_comparisons if not m.passed]
    assert len(failed_metrics) > 0
    assert failed_metrics[0].metric_name == "tip_displacement"
    assert failed_metrics[0].rel_difference > 1e-2
