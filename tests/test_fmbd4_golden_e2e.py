"""Tests for the Flexible Multi-Body Dynamics 4 (FMBD-4) Golden E2E Case."""

import json
from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.golden_registry import standard_golden_catalog
from abaqus_ai_agent.golden_evidence import normalize_golden_evidence, validate_golden_evidence_dict
from tools.fmbd4_rigid_flexible_golden_e2e import (
    build_fmbd4_golden_script,
    _extract_report,
    parse_evidence_status_from_output,
)


def test_fmbd4_golden_script_uses_existing_pipeline():
    script = build_fmbd4_golden_script()
    for marker in (
        "reference_point(",
        "rigid_body(",
        "coupling_constraint(",
        "connector_section(",
        "wire_connector(",
        "displacement_bc(",
        "implicit_dynamic_step(",
        "gravity(",
        "material_density(",
        "field_output(",
        "history_output(",
        "AnalysisRunner(executor).run(",
        "evaluate_result_acceptance(",
        "seed_part(",
        "generate_mesh(",
    ):
        assert marker in script, "Missing expected marker in script: %s" % marker


def test_fmbd4_golden_script_has_no_direct_process_solver_bypass():
    script = build_fmbd4_golden_script()
    assert "subprocess" not in script
    assert "run_input(" not in script
    assert "run_nogui(" not in script


def _extract_migrated_harness(script):
    """Pull the migrated namespace harness (_NS + _run_code) out of the
    generated CAE script so offline tests can drive it with a fake kernel."""
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
    script = build_fmbd4_golden_script()
    env = {}
    exec(_extract_migrated_harness(script), env)
    run_code = env["_run_code"]

    sentinel = object()
    globals()["LOG"] = sentinel
    try:
        # seed constants are visible to fragments; caller LOG is untouched
        out = run_code("result = {\"log\": LOG}")
        assert out == {"log": "SymbolicConstant<LOG>"}
        assert globals()["LOG"] is sentinel
        # cross-fragment persistence inside the namespace
        run_code("carried = 41")
        assert run_code("result = {\"v\": carried + 1}") == {"v": 42}
        # a fragment that sets no result must not see the stale one
        assert run_code("other = 1") == {"status": "COMPLETED"}
        # fragment exceptions propagate
        import pytest

        with pytest.raises(ValueError):
            run_code("raise ValueError(\"fragment-boom\")")
    finally:
        globals().pop("LOG", None)
    # harness bookkeeping never entered the caller env
    assert "carried" not in env
    assert "result" not in env


def test_fmbd4_golden_report_parser():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    stdout = (
        "preamble noise\n"
        "AIAgent_FMBD4_GOLDEN_RESULT_BEGIN\n"
        + json.dumps(report)
        + "\nAIAgent_FMBD4_GOLDEN_RESULT_END\n"
        "trailing noise\n"
    )
    assert _extract_report(stdout) == report
    assert parse_evidence_status_from_output(stdout) == "PASS"


def test_fmbd4_golden_report_parser_with_rpy_prefixes():
    report = {"status": "pass", "workflow": {"solver_completed": True}}
    raw_json = json.dumps(report, indent=2)
    rpy_lines = ["#: " + line for line in raw_json.splitlines()]
    stdout = (
        "AIAgent_FMBD4_GOLDEN_RESULT_BEGIN\n"
        + "\n".join(rpy_lines)
        + "\nAIAgent_FMBD4_GOLDEN_RESULT_END\n"
    )
    assert _extract_report(stdout) == report


def test_fmbd4_golden_dual_acceptance_gate():
    nominal_criteria = (
        {'name': 'joint_drift', 'value_key': 'joint_drift', 'operator': '<=', 'limit': 1e-3, 'unit': 'mm'},
        {'name': 'max_mises_stress_lower', 'value_key': 'max_mises_stress_lower', 'operator': '>=', 'limit': 0.01, 'unit': 'MPa'},
        {'name': 'max_mises_stress_upper', 'value_key': 'max_mises_stress_upper', 'operator': '<=', 'limit': 100.0, 'unit': 'MPa'},
        {'name': 'strain_energy_active', 'value_key': 'strain_energy_active', 'operator': '>=', 'limit': 0.01, 'unit': ''},
        {'name': 'energy_dissipation', 'value_key': 'energy_dissipation', 'operator': '<=', 'limit': 0.05, 'unit': ''},
    )
    strict_criteria = (
        {'name': 'joint_drift_impossible', 'value_key': 'joint_drift_impossible', 'operator': '<=', 'limit': 1e-15, 'unit': 'mm'},
    )

    valid_values = {
        'joint_drift': 1.5e-5,
        'max_mises_stress_lower': 0.05,
        'max_mises_stress_upper': 0.05,
        'strain_energy_active': 0.08,
        'energy_dissipation': 0.02,
        'joint_drift_impossible': 1.5e-5,
    }

    acc_nom = evaluate_result_acceptance('completed', values=valid_values, criteria=nominal_criteria)
    acc_strict = evaluate_result_acceptance('completed', values=valid_values, criteria=strict_criteria)
    assert acc_nom.passed is True
    assert acc_strict.passed is False

    # Negative test: Excessive joint drift must fail
    invalid_values = dict(valid_values, joint_drift=0.05)
    acc_nom_fail = evaluate_result_acceptance('completed', values=invalid_values, criteria=nominal_criteria)
    assert acc_nom_fail.passed is False
    assert any("joint_drift" in f for f in acc_nom_fail.failures)


def test_fmbd4_golden_catalog_registration():
    case = standard_golden_catalog.get_case("fmbd4_rigid_flexible")
    assert case is not None
    assert case.category == "FMBD"
    assert case.physics_type == "flexible_multibody_dynamics"
    assert case.tool_script == "tools/fmbd4_rigid_flexible_golden_e2e.py"
    assert len(case.criteria) == 5
    assert len(case.strict_criteria) == 1
    assert "coupling" in case.tags
    assert "fmbd" in case.tags


def test_fmbd4_golden_evidence_normalization():
    mock_report = {
        "status": "pass",
        "case_id": "fmbd4_rigid_flexible",
        "release": "Abaqus 2025",
        "solver": "standard",
        "procedure": "implicit_dynamic",
        "job_name": "FMBD4GoldenJob",
        "odb_path": "/path/to/FMBD4GoldenJob.odb",
        "simulation_results": {
            "max_joint_drift_mm": 1.2e-5,
            "max_mises_stress_mpa": 115.0,
            "strain_energy_ratio": 0.065,
            "energy_dissipation_ratio": 0.018,
            "num_frames": 105,
            "total_time_s": 1.2,
        },
        "workflow": {
            "solver_completed": True,
            "odb_path": "/path/to/FMBD4GoldenJob.odb",
            "mesh_quality_passed": True,
        },
        "verification": {
            "joint_drift_passed": True,
            "stress_sanity_passed": True,
            "strain_energy_passed": True,
            "energy_conservation_passed": True,
            "normal_acceptance_passed": True,
            "strict_acceptance_passed": False,
        },
        "acceptance": {
            "passed": True,
            "criteria": [
                {"name": "joint_drift", "passed": True},
                {"name": "max_mises_stress_lower", "passed": True},
                {"name": "max_mises_stress_upper", "passed": True},
                {"name": "strain_energy_active", "passed": True},
                {"name": "energy_dissipation", "passed": True},
            ],
            "failures": [],
            "warnings": [],
        },
        "provenance": {
            "action_count": 22,
            "intent_id": "fmbd4-rigid-flexible-golden-e2e",
            "release": "Abaqus 2025",
        },
    }

    raw_evidence = {
        "case_id": "fmbd4_rigid_flexible",
        "release": "Abaqus 2025",
        "status": "pass",
        "launcher": "C:\\SIMULIA\\Commands\\abaqus.bat",
        "workdir": "/work",
        "script": "/work/script.py",
        "process_succeeded": True,
        "return_code": 0,
        "solver_status": "completed",
        "report": mock_report,
    }

    envelope = normalize_golden_evidence(raw_evidence)
    assert envelope.case_id == "fmbd4_rigid_flexible"
    assert envelope.release == "Abaqus 2025"
    assert envelope.solver_status == "completed"
    assert envelope.acceptance["passed"] is True

    dict_repr = envelope.to_dict()
    errors = validate_golden_evidence_dict(dict_repr)
    assert not errors, "Schema validation errors: %s" % errors
