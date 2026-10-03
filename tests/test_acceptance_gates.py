import pytest
from abaqus_ai_agent.acceptance import (
    AcceptanceResult,
    evaluate_criteria,
    evaluate_result_acceptance,
)


def test_missing_required_field_blocks_acceptance():
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_displacement": 0.5},
        criteria=[{"name": "disp", "value_key": "max_displacement", "operator": "<", "limit": 1.0}],
        physics_domain="static",
        odb_fields=["U"],  # static requires U, S, RF; S and RF are missing
    )
    assert res.passed is False
    assert res.status == "BLOCKED"
    assert res.result_validity == "RESULT_INVALID"
    assert "missing_required_field:S" in res.blocked
    assert "missing_required_field:RF" in res.blocked
    assert "Required Result: FAIL | Engineering Acceptance: FAIL" in res.audit_summary
    assert res.gates["required_results"] == "BLOCKED"


def test_matching_required_fields_passes():
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"max_displacement": 0.5, "max_mises": 120.0, "reaction_force": 1000.0},
        criteria=[{"name": "disp", "value_key": "max_displacement", "operator": "<", "limit": 1.0}],
        physics_domain="static",
        odb_fields=["U", "S", "RF"],
    )
    assert res.passed is True
    assert res.status == "PASS"
    assert res.result_validity == "VALID"
    assert len(res.missing_required_fields) == 0
    assert "Required Result: PASS | Engineering Acceptance: PASS" in res.audit_summary


def test_missing_required_metric_blocks_acceptance():
    criteria = [
        {"name": "mises", "value_key": "max_mises", "operator": "<", "limit": 250.0, "required": True},
    ]
    # Value is missing from values dict
    result = evaluate_result_acceptance(
        result_status="completed",
        values={},
        criteria=criteria,
    )
    assert result.passed is False
    assert result.status == "BLOCKED"
    assert any("missing_required_metric:max_mises" in b for b in result.blocked)
    assert result.gates["criteria"] == "BLOCKED"


def test_missing_required_evidence_blocks_acceptance():
    result = evaluate_result_acceptance(
        result_status="completed",
        values={"disp": 1.2},
        criteria=[{"name": "disp", "value_key": "disp", "operator": "<", "limit": 2.0}],
        require_evidence=True,
        evidence=None,
    )
    assert result.passed is False
    assert result.status == "BLOCKED"
    assert "missing_required_evidence" in result.blocked
    assert result.gates["evidence_sufficiency"] == "BLOCKED"


def test_status_distinctions_pass_warning_fail_blocked():
    # 1. PASS
    res_pass = evaluate_result_acceptance(
        result_status="completed",
        values={"disp": 1.0},
        criteria=[{"name": "disp", "value_key": "disp", "operator": "<", "limit": 2.0}],
    )
    assert res_pass.passed is True
    assert res_pass.status == "PASS"

    # 2. WARNING
    res_warn = evaluate_result_acceptance(
        result_status="completed",
        values=None,
        criteria=None,
    )
    assert res_warn.passed is True
    assert res_warn.status == "WARNING"
    assert "no_explicit_acceptance_criteria" in res_warn.warnings

    # 3. FAIL
    res_fail = evaluate_result_acceptance(
        result_status="completed",
        values={"disp": 5.0},
        criteria=[{"name": "disp", "value_key": "disp", "operator": "<", "limit": 2.0}],
    )
    assert res_fail.passed is False
    assert res_fail.status == "FAIL"

    # 4. BLOCKED
    res_blocked = evaluate_result_acceptance(
        result_status="error",
        values={"disp": 1.0},
        criteria=[{"name": "disp", "value_key": "disp", "operator": "<", "limit": 2.0}],
    )
    assert res_blocked.passed is False
    assert res_blocked.status == "BLOCKED"


def test_acceptance_result_to_dict():
    res = evaluate_result_acceptance(
        result_status="completed",
        values={"stress": 120.0},
        criteria=[{"name": "stress", "value_key": "stress", "operator": "<", "limit": 200.0, "unit": "MPa"}],
    )
    d = res.to_dict()
    assert d["passed"] is True
    assert d["status"] == "PASS"
    assert len(d["criteria"]) == 1
    assert d["criteria"][0]["actual"] == 120.0
    assert d["gates"]["execution"] == "PASS"
    assert d["gates"]["criteria"] == "PASS"
