"""Tests for the General Contact & Friction E2E tool."""

import json

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.engineering_checks import (
    EngineeringCheck,
    EngineeringCheckReport,
)
from tools.general_contact_e2e import (
    build_general_contact_script,
    parse_evidence_status_from_output,
    parse_general_contact_report_from_output,
)


def test_general_contact_script_uses_architecture_pipeline():
    script = build_general_contact_script()
    assert "contact(" in script
    assert "contact_property(" in script
    assert "AnalysisRunner(executor).run(" in script
    assert "extract_field(" in script
    assert "coulomb_friction_from_reaction_evidence(" in script
    assert "evaluate_result_acceptance(" in script
    assert "ContactDiagnosticReport(" in script
    assert "contact_evidence_sufficiency(" in script
    assert "expected_contact_state(" in script
    assert "unexpected_opening(" in script
    assert "unexpected_overclosure(" in script
    assert "PENALTY" in script
    assert "HARD" in script
    assert "C3D8R" in script


def test_build_contact_plan_integration():
    from abaqus_ai_agent.workflow.contact import build_contact_plan
    plan = build_contact_plan(
        model_name="TestContactModel",
        material={"name": "Steel", "youngs_modulus": 210000.0, "poisson": 0.3},
        region_map={
            "master_surface": "MasterSurf",
            "slave_surface": "SlaveSurf",
            "fixed_base": "BaseFixed",
            "moving_slider": "SliderMove",
        },
        step_name="Step-1",
        contact_property_name="TestContactProp",
        friction_coefficient=0.25,
    )
    assert len(plan.actions) > 0
    types = [a.action_type for a in plan.actions]
    assert "contact" in types
    assert "contact_property" in types


def test_general_contact_script_does_not_contain_bypass():
    script = build_general_contact_script()
    assert "subprocess" not in script
    assert "run_input" not in script
    assert "run_nogui" not in script


def test_parse_general_contact_report_from_output():
    sample_report = {
        "status": "pass",
        "case": "two_body_frictional_contact_sliding",
        "forces_and_equilibrium": {
            "effective_friction_mu": 0.25,
            "theoretical_friction_mu": 0.25,
            "coulomb_law_passed": True,
        },
    }
    raw = (
        "prefix\n"
        "AIAgent_GENERAL_CONTACT_REPORT_JSON_BEGIN\n"
        + json.dumps(sample_report)
        + "\nAIAgent_GENERAL_CONTACT_REPORT_JSON_END\n"
        "suffix\n"
    )
    parsed = parse_general_contact_report_from_output(raw)
    assert parsed is not None
    assert parsed["status"] == "pass"
    assert parsed["forces_and_equilibrium"]["effective_friction_mu"] == 0.25

    # Rpy prefix (#: ) support
    rpy_raw = "\n".join("#: " + line for line in raw.splitlines())
    parsed_rpy = parse_general_contact_report_from_output(rpy_raw)
    assert parsed_rpy is not None
    assert parsed_rpy["status"] == "pass"


def test_parse_evidence_status_from_output():
    out = "some output\nAIAgent_GENERAL_CONTACT_EVIDENCE_STATUS: pass\nmore output"
    assert parse_evidence_status_from_output(out) == "pass"
    out_fail = "some output\nAIAgent_GENERAL_CONTACT_EVIDENCE_STATUS: fail\nmore output"
    assert parse_evidence_status_from_output(out_fail) == "fail"


def test_parse_evidence_status_rpy_prefix():
    out = "#: AIAgent_GENERAL_CONTACT_EVIDENCE_STATUS: pass"
    assert parse_evidence_status_from_output(out) == "pass"


def test_contact_dual_acceptance_gate_logic():
    coulomb_check = EngineeringCheck(
        name="coulomb_friction_ratio",
        passed=True,
        actual=0.25,
        expected=0.25,
        tolerance=0.08,
        unit="",
    )
    report = EngineeringCheckReport(checks=(coulomb_check,))

    criteria = (
        {
            "name": "effective_friction_coefficient_lower",
            "value_key": "effective_friction_coefficient",
            "operator": ">=",
            "limit": 0.20,
            "unit": "",
        },
        {
            "name": "effective_friction_coefficient_upper",
            "value_key": "effective_friction_coefficient",
            "operator": "<=",
            "limit": 0.30,
            "unit": "",
        },
        {
            "name": "global_normal_equilibrium_error",
            "value_key": "normal_equilibrium_rel_error",
            "operator": "<=",
            "limit": 0.01,
            "unit": "",
        },
    )
    values = {
        "effective_friction_coefficient": 0.25,
        "normal_equilibrium_rel_error": 0.0005,
    }

    # Normal physics gate should pass
    normal_acc = evaluate_result_acceptance(
        result_status="completed",
        engineering=report,
        values=values,
        criteria=criteria,
    )
    assert normal_acc.passed is True

    # Strict gate should fail
    strict_criteria = list(criteria) + [
        {
            "name": "strict_contact_pressure_artificial",
            "value_key": "effective_friction_coefficient",
            "operator": ">=",
            "limit": 10.0,
            "unit": "",
        }
    ]
    strict_acc = evaluate_result_acceptance(
        result_status="completed",
        engineering=report,
        values=values,
        criteria=tuple(strict_criteria),
    )
    assert strict_acc.passed is False
    assert len(strict_acc.failures) == 1


def _extract_migrated_harness(script):
    """Extract the namespace harness for offline testing with a fake kernel."""
    head, sep, rest = script.partition("_NS = KernelNamespace")
    assert sep, "generated script must construct a KernelNamespace"
    harness_src = sep + rest.split("class CAEInProcessExecutor", 1)[0]
    return (
        "from abaqus_ai_agent.execution.kernel_namespace import "
        "KernelNamespace, build_cae_seed\n" + harness_src
    )


def _fake_cae_modules(monkeypatch):
    import sys
    import types

    fake_abaqus = types.ModuleType("abaqus")
    fake_abaqus.mdb = object()
    fake_abaqus.__all__ = ["mdb"]
    fake_const = types.ModuleType("abaqusConstants")
    fake_const.LOG = "SymbolicConstant<LOG>"
    fake_const.__all__ = ["LOG"]
    monkeypatch.setitem(sys.modules, "abaqus", fake_abaqus)
    monkeypatch.setitem(sys.modules, "abaqusConstants", fake_const)


def test_migrated_run_code_runs_fragments_in_isolated_namespace(monkeypatch):
    _fake_cae_modules(monkeypatch)
    script = build_general_contact_script()
    env = {}
    exec(_extract_migrated_harness(script), env)
    run_code = env["_run_code"]

    sentinel = object()
    globals()["LOG"] = sentinel
    try:
        out = run_code("result = {\"log\": LOG}")
        assert out == {"log": "SymbolicConstant<LOG>"}
        assert globals()["LOG"] is sentinel

        run_code("carried = 41")
        assert run_code("result = {\"v\": carried + 1}") == {"v": 42}
        assert run_code("other = 1") == {"status": "COMPLETED"}

        import pytest

        with pytest.raises(ValueError):
            run_code("raise ValueError(\"fragment-boom\")")
    finally:
        globals().pop("LOG", None)

    assert "carried" not in env
    assert "result" not in env
