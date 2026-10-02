"""Tests for the Thermal Steady-State Golden Case E2E tool."""

import json

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.engineering_checks import (
    EngineeringCheck,
    EngineeringCheckReport,
)
from tools.thermal_golden_e2e import (
    build_thermal_golden_script,
    parse_evidence_status_from_output,
    parse_thermal_report_from_output,
)


def test_thermal_golden_script_uses_architecture_pipeline():
    script = build_thermal_golden_script()
    assert "build_thermal_plan" in script
    assert "AnalysisRunner" in script
    assert "extract_field" in script
    assert "DC3D8" in script
    assert "thermal_flux_balance_from_field_evidence" in script
    assert "evaluate_result_acceptance" in script
    assert "STEADY_STATE" in script


def test_thermal_golden_script_does_not_contain_bypass():
    script = build_thermal_golden_script()
    assert "subprocess" not in script
    assert "run_input" not in script
    assert "run_nogui" not in script


def test_parse_thermal_report_from_output():
    sample_report = {
        "status": "pass",
        "case": "1d_steady_state_heat_conduction",
        "theory": {"T_mid_exact_C": 50.0, "Q_rate_total_mW": 5000.0},
    }
    raw = (
        "prefix\n"
        "AIAgent_THERMAL_GOLDEN_REPORT_JSON_BEGIN\n"
        + json.dumps(sample_report)
        + "\nAIAgent_THERMAL_GOLDEN_REPORT_JSON_END\n"
        "suffix\n"
    )
    parsed = parse_thermal_report_from_output(raw)
    assert parsed is not None
    assert parsed["status"] == "pass"
    assert parsed["theory"]["T_mid_exact_C"] == 50.0

    # Rpy prefix (#: ) support
    rpy_raw = "\n".join("#: " + line for line in raw.splitlines())
    parsed_rpy = parse_thermal_report_from_output(rpy_raw)
    assert parsed_rpy is not None
    assert parsed_rpy["status"] == "pass"


def test_parse_evidence_status_from_output():
    out = "some output\nAIAgent_THERMAL_E2E_EVIDENCE_STATUS: pass\nmore output"
    assert parse_evidence_status_from_output(out) == "pass"
    out_fail = "some output\nAIAgent_THERMAL_E2E_EVIDENCE_STATUS: fail\nmore output"
    assert parse_evidence_status_from_output(out_fail) == "fail"


def test_parse_evidence_status_rpy_prefix():
    out = "#: AIAgent_THERMAL_E2E_EVIDENCE_STATUS: pass"
    assert parse_evidence_status_from_output(out) == "pass"


def test_thermal_dual_acceptance_gate_logic():
    dummy_check = EngineeringCheck(
        name="thermal_energy_balance_RFL",
        passed=True,
        actual=0.001,
        expected=0.0,
        tolerance=0.01,
        unit="mW",
    )
    thermal_report = EngineeringCheckReport(checks=(dummy_check,))

    criteria = (
        {
            "name": "mid_temperature_lower",
            "value_key": "mid_temp_lower",
            "operator": ">=",
            "limit": 49.5,
            "unit": "C",
        },
        {
            "name": "mid_temperature_upper",
            "value_key": "mid_temp_upper",
            "operator": "<=",
            "limit": 50.5,
            "unit": "C",
        },
    )
    values = {"mid_temp_lower": 50.0, "mid_temp_upper": 50.0}

    # Normal physics gate should pass
    normal_acc = evaluate_result_acceptance(
        result_status="completed",
        engineering=thermal_report,
        values=values,
        criteria=criteria,
    )
    assert normal_acc.passed is True

    # Strict gate should fail
    strict_criteria = list(criteria) + [
        {
            "name": "strict_mid_temp",
            "value_key": "mid_temp_lower",
            "operator": ">=",
            "limit": 60.0,
            "unit": "C",
        }
    ]
    strict_acc = evaluate_result_acceptance(
        result_status="completed",
        engineering=thermal_report,
        values=values,
        criteria=tuple(strict_criteria),
    )
    assert strict_acc.passed is False
    assert any("strict_mid_temp" in f for f in strict_acc.failures)
