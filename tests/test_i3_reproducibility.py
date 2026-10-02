"""Tests for Phase I.3 Engineering Reproducibility & Tolerance Invariance."""

from __future__ import annotations

from pathlib import Path

from tools.i3_reproducibility import compare_reproducibility

ROOT = Path(__file__).resolve().parent.parent


def test_reproducibility_on_static_golden():
    evidence_path = ROOT / "machine_validation" / "static_golden_e2e.json"
    manifest = compare_reproducibility(evidence_path, None, relative_tolerance=1e-4)

    assert manifest["schema_version"] == "reproducibility_evidence_v1"
    assert manifest["case_id"] == "static_cantilever"
    assert manifest["structural_invariance"]["intent_hash_match"] is True
    assert manifest["acceptance_invariance"]["verdict_match"] is True
    assert manifest["numerical_metrics_evaluated"] >= 3
    assert manifest["all_metrics_within_tolerance"] is True
    assert manifest["reproducibility_verified"] is True
