import json
from pathlib import Path
import pytest

from tools.acceptance_evidence_closure_e2e import (
    probe_static_domain,
    probe_thermal_domain,
    probe_contact_domain,
    probe_modal_domain,
    probe_multi_step_domain,
    probe_real_odb_missing_field_and_report,
    run_batch2_acceptance_closure,
)

ROOT = Path(__file__).resolve().parent.parent


def test_batch2_acceptance_manifest_contract():
    """Verify that the official Batch 2 acceptance evidence closure manifest is valid and fail-closed."""
    manifest_path = ROOT / "machine_validation" / "acceptance_evidence_closure_manifest.json"
    if not manifest_path.exists():
        manifest = run_batch2_acceptance_closure()
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "acceptance_evidence_closure_v1"
    assert manifest["all_domains_fail_closed"] is True
    assert manifest["domains_verified_count"] == 5

    probes = manifest["probes"]
    for dom in ("static", "thermal", "contact", "modal", "multi_step"):
        assert dom in probes, f"Domain {dom} missing from manifest"
        assert probes[dom]["fail_closed"] is True, f"Domain {dom} failed closed contract"

    real_probe = probes["real_odb_missing_output"]
    assert real_probe["odb_exists"] is True
    assert real_probe["solver_completed"] is True
    assert real_probe["acceptance_passed"] is False
    assert real_probe["result_validity"] == "RESULT_INVALID"
    assert real_probe["audit_summary_line"] == "Solver: PASS | ODB: PASS | Required Result: FAIL | Engineering Acceptance: FAIL"
    assert real_probe["report_has_audit_summary"] is True
    assert real_probe["report_has_rejected_verdict"] is True
    assert real_probe["fail_closed"] is True


def test_static_domain_fail_closed_contract():
    """Verify that static domain requires displacement/stress/reaction and fails closed when missing."""
    res = probe_static_domain()
    assert res["baseline_pass"] is True
    assert res["missing_metric_blocked"] is True
    assert res["result_validity"] == "RESULT_INVALID"
    assert "max_displacement" in res["missing_metrics"]
    assert res["fail_closed"] is True


def test_thermal_domain_fail_closed_contract():
    """Verify that thermal domain requires temperature/flux and fails closed when missing."""
    res = probe_thermal_domain()
    assert res["baseline_pass"] is True
    assert res["missing_metric_blocked"] is True
    assert res["result_validity"] == "RESULT_INVALID"
    assert "max_temperature" in res["missing_metrics"]
    assert res["fail_closed"] is True


def test_contact_domain_mandatory_gate_and_metrics():
    """Verify that contact domain strictly enforces the contact gate and required contact metrics."""
    res = probe_contact_domain()
    assert res["baseline_pass"] is True
    assert res["missing_mandatory_gate_blocked"] is True
    assert res["missing_metric_blocked"] is True
    assert "contact" in res["missing_gate_ids"]
    assert "contact_pressure" in res["missing_metric_ids"]
    assert res["fail_closed"] is True


def test_modal_domain_fail_closed_contract():
    """Verify that modal domain requires frequency/eigenvalues and fails closed when missing."""
    res = probe_modal_domain()
    assert res["baseline_pass"] is True
    assert res["missing_metric_blocked"] is True
    assert res["result_validity"] == "RESULT_INVALID"
    assert "frequency" in res["missing_metrics"]
    assert res["fail_closed"] is True


def test_multi_step_domain_fail_closed_contract():
    """Verify that multi-step procedure domain requires step-specific outputs and fails closed when missing."""
    res = probe_multi_step_domain()
    assert res["baseline_pass"] is True
    assert res["missing_metric_blocked"] is True
    assert res["result_validity"] == "RESULT_INVALID"
    assert "torque_reaction" in res["missing_metrics"]
    assert res["fail_closed"] is True


def test_real_odb_missing_field_and_unforgeable_report():
    """Verify on real Abaqus 2025 ODB that missing field output produces RESULT_INVALID and unforgeable report."""
    res = probe_real_odb_missing_field_and_report()
    assert res["odb_exists"] is True
    assert res["solver_completed"] is True
    assert res["acceptance_passed"] is False
    assert res["acceptance_status"] == "BLOCKED"
    assert res["result_validity"] == "RESULT_INVALID"
    assert res["audit_summary_line"] == "Solver: PASS | ODB: PASS | Required Result: FAIL | Engineering Acceptance: FAIL"
    assert res["report_has_audit_summary"] is True
    assert res["report_has_rejected_verdict"] is True
    assert res["report_has_missing_metric_listed"] is True
    assert res["fail_closed"] is True
