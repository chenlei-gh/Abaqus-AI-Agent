from abaqus_ai_agent.engineering_checks import check_balance, evaluate_checks, STANDARD_ENGINEERING_CHECKS
from abaqus_ai_agent.provenance import stable_hash, hash_text
from abaqus_ai_agent.sensitivity import evaluate_sensitivity
from abaqus_ai_agent.contracts.sensitivity import SensitivityCase
from abaqus_ai_agent.correction import can_retry, select_repairs, can_apply_repair
from abaqus_ai_agent.contracts.correction import CorrectionPolicy, RepairCandidate
from abaqus_ai_agent.numerical_verification import verify_series
from abaqus_ai_agent.contact_diagnostics import (
    diagnose_contact,
    evaluate_contact_checks,
    expected_contact_state,
)
from abaqus_ai_agent.contracts.contact import (
    ContactDiagnostic,
    ContactDiagnosticReport,
    ExpectedContactBehavior,
)
from abaqus_ai_agent.contracts.uncertainty import UncertaintyParameter


def test_standard_engineering_check_families_are_bounded():
    assert "global_equilibrium" in STANDARD_ENGINEERING_CHECKS["static"]
    assert "energy_balance" in STANDARD_ENGINEERING_CHECKS["dynamic"]
    assert "contact_state" in STANDARD_ENGINEERING_CHECKS["contact"]
    assert "contact_reaction_consistency" in STANDARD_ENGINEERING_CHECKS["contact"]


def test_balance_check_is_deterministic():
    check = check_balance("reaction", 99.0, 100.0, 0.02, "N")
    assert check.passed
    assert evaluate_checks((check,)).passed


def test_provenance_hash_is_stable():
    assert stable_hash({"b": 2, "a": 1}) == stable_hash({"a": 1, "b": 2})
    assert hash_text("x") == hash_text("x")


def test_sensitivity_ranks_largest_influence():
    baseline = {"stress": 100.0}
    case = SensitivityCase("load_plus", {"load": 1.1})
    result = evaluate_sensitivity(
        baseline,
        (type("R", (), {
            "case": case,
            "values": {"stress": 120.0},
            "status": "completed",
        })(),),
    )
    assert result.ranking == (("stress", 0.2),)


def test_correction_policy_is_bounded():
    policy = CorrectionPolicy(max_attempts=1)
    candidate = RepairCandidate(
        "add_output", "missing_output_request", {"field": "S"})
    assert select_repairs("missing_output_request", (candidate,), policy)
    assert can_retry(0, policy)
    assert not can_apply_repair(candidate)
    assert can_apply_repair(candidate, confirmed=True)
    assert not can_retry(1, policy)
    assert not select_repairs("solver_failed", (candidate,), policy)


def test_numerical_verification():
    result = verify_series("mesh", (100.0, 100.5, 100.45), 0.01)
    assert result.passed
    assert result.method == "successive_relative_change"
    assert "relative_change=" in result.message


def test_contact_diagnostics():
    report = evaluate_contact_checks((
        ContactDiagnostic("penetration", "pass", value=0.0),
    ))
    assert report.passed


def _contact_evidence(cstatus, copen=(0.0,), cpress=(10.0,)):
    return {
        "region": "Surface-A-B",
        "fields": {
            "CSTATUS": {
                "status": "available",
                "values": [{"data": value} for value in cstatus],
            },
            "COPEN": {
                "status": "available",
                "values": [{"data": value} for value in copen],
            },
            "CPRESS": {
                "status": "available",
                "values": [{"data": value} for value in cpress],
            },
        },
        "history": {"status": "available"},
    }


def test_contact_diagnostic_requires_declared_expected_behavior():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        expected_regions=("Surface-A-B",),
        expected_separation=0.1,
        required_outputs=("CSTATUS", "COPEN", "CPRESS"),
    )
    report = diagnose_contact(
        _contact_evidence(("sticking",)),
        expected,
    )
    assert report.passed
    assert {item.name for item in report.diagnostics} == {
        "contact_evidence_sufficiency",
        "expected_contact_state",
        "unexpected_opening",
        "unexpected_overclosure",
        "contact_behavior_consistency",
    }


def test_contact_open_is_failure_only_when_contact_is_required():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        expected_separation=0.0,
        required_outputs=("CSTATUS", "COPEN"),
    )
    report = diagnose_contact(
        _contact_evidence(("open",), copen=(0.5,), cpress=(0.0,)),
        expected,
    )
    assert any(item.status == "fail" for item in report.diagnostics)
    assert any(item.name == "expected_contact_state" for item in report.failed)


def test_contact_separation_can_be_expected():
    expected = ExpectedContactBehavior(
        contact_required=True,
        expected_state="open",
        required_outputs=("CSTATUS", "COPEN"),
    )
    report = diagnose_contact(
        _contact_evidence(("open",), copen=(0.5,), cpress=(0.0,)),
        expected,
    )
    assert report.diagnostics[1].status == "pass"
    assert report.diagnostics[2].status == "not_applicable"


def test_positive_contact_pressure_is_not_contact_correctness():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        expected_separation=0.1,
        required_outputs=("CSTATUS", "CPRESS", "COPEN"),
    )
    report = diagnose_contact(
        _contact_evidence(("open",), copen=(0.5,), cpress=(100.0,)),
        expected,
    )
    assert any(item.name == "expected_contact_state" and item.status == "fail"
               for item in report.diagnostics)


def test_missing_output_is_not_zero_evidence():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        required_outputs=("CSTATUS", "COPEN"),
    )
    evidence = _contact_evidence((1.0,))
    evidence["fields"]["COPEN"] = {
        "status": "unavailable",
        "reason": "field_output_missing",
    }
    report = diagnose_contact(evidence, expected)
    assert report.diagnostics[0].status == "insufficient_evidence"
    assert report.passed is False


def test_negative_copen_without_declared_interference_limit_is_not_failure():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        expected_separation=0.1,
        required_outputs=("CSTATUS", "COPEN"),
    )
    report = diagnose_contact(
        _contact_evidence(("sticking",), copen=(-0.02,), cpress=(10.0,)),
        expected,
    )
    diagnostic = next(
        item for item in report.diagnostics
        if item.name == "unexpected_overclosure"
    )
    assert diagnostic.status == "warning"


def test_negative_copen_with_declared_interference_limit_can_fail():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        expected_separation=0.1,
        allowed_initial_interference=0.01,
        required_outputs=("CSTATUS", "COPEN"),
    )
    report = diagnose_contact(
        _contact_evidence((1.0,), copen=(-0.02,), cpress=(10.0,)),
        expected,
    )
    diagnostic = next(
        item for item in report.diagnostics
        if item.name == "unexpected_overclosure"
    )
    assert diagnostic.status == "fail"


def test_opening_without_problem_specific_limit_is_insufficient():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        required_outputs=("CSTATUS", "COPEN"),
    )
    report = diagnose_contact(
        _contact_evidence((1.0,), copen=(0.2,), cpress=(1.0,)),
        expected,
    )
    diagnostic = next(
        item for item in report.diagnostics
        if item.name == "unexpected_opening"
    )
    assert diagnostic.status == "insufficient_evidence"


def test_uncertainty_bounds():
    UncertaintyParameter("load", 100.0, 90.0, 110.0, "N")


def test_load_balance_and_energy_ratio():
    from abaqus_ai_agent.engineering_checks import check_load_balance, check_energy_ratio
    assert check_load_balance(100.0, -99.0, 0.02, "N").passed
    assert check_load_balance(100.0, -90.0, 0.02, "N").passed is False
    assert check_energy_ratio(1.0, 100.0, 0.02).passed
    assert check_energy_ratio(5.0, 100.0, 0.02).passed is False


def test_sum_reaction_components_preserves_explicit_resultant():
    from abaqus_ai_agent.engineering_checks import sum_reaction_components
    result = sum_reaction_components([
        {"data": (1.0, 2.0, 3.0)},
        {"data": (-0.5, 1.0, -1.0)},
    ])
    assert result["components"] == (0.5, 3.0, 2.0)
    assert result["count"] == 2


def test_declared_load_balance_does_not_infer_applied_load():
    from abaqus_ai_agent.engineering_checks import check_declared_load_balance
    report = check_declared_load_balance(
        (100.0, 0.0, 0.0), (-99.0, 0.0, 0.0), 0.02, "N"
    )
    assert report.passed
    assert report.checks[0].name == "global_load_balance_RF1"


def test_sensitivity_case_normalization():
    from abaqus_ai_agent.sensitivity import build_sensitivity_cases
    cases = build_sensitivity_cases(
        "Model-1", "Job-1", (SensitivityCase("load_plus", {"load": 1.1}),)
    )
    assert cases[0].model_name == "Model-1"
    assert cases[0].job_name == "Job-1_load_plus"


def test_sensitivity_execution_uses_existing_runner():
    from abaqus_ai_agent.sensitivity import execute_sensitivity

    class Run:
        state = type("S", (), {"value": "odb_validated"})()
        diagnostics = ()

    class Runner:
        calls = []
        def run(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return Run()

    runner = Runner()
    cases = (SensitivityCase("load_plus", {"load": 1.1}),)
    report = execute_sensitivity(
        executor=object(),
        runner=runner,
        model_name="Model-1",
        job_name="Job-1",
        baseline_values={"stress": 100.0},
        cases=cases,
        value_extractor=lambda executor, run, case: {"stress": 120.0},
    )
    assert report.completed
    assert report.ranking == (("stress", 0.2),)
    assert runner.calls[0][0] == ("Model-1", "Job-1_load_plus")


def test_reproducibility_manifest_is_deterministic():
    from abaqus_ai_agent.provenance import build_reproducibility_manifest
    from abaqus_ai_agent.contracts.provenance import AnalysisProvenance
    from abaqus_ai_agent.execution.artifacts import JobArtifact
    provenance = AnalysisProvenance(
        "run-1", "Model-1", "Job-1", executor="TestExecutor"
    )
    artifacts = (JobArtifact("Job-1", ".odb", "Job-1.odb", True, 10, 2.0),)
    first = build_reproducibility_manifest(provenance, artifacts)
    second = build_reproducibility_manifest(provenance, artifacts)
    assert first == second
    assert first["content_hashes_available"] is False
    assert first["manifest_hash"]


def test_correction_attempt_records_confirmation_and_retry_gate():
    from abaqus_ai_agent.correction import record_attempt
    policy = CorrectionPolicy(max_attempts=1)
    proposed = record_attempt(
        0, "missing_output_request", "add_output", confirmed=False, policy=policy
    )
    assert proposed.confirmed is False
    assert proposed.retry_allowed is False
    confirmed = record_attempt(
        0, "missing_output_request", "add_output", confirmed=True, policy=policy
    )
    assert confirmed.confirmed is True
    assert confirmed.retry_allowed is True


def test_contact_mixed_status_is_ambiguous_not_failure():
    from abaqus_ai_agent.contracts.contact import ExpectedContactBehavior
    from abaqus_ai_agent.contact_diagnostics import expected_contact_state

    expected = ExpectedContactBehavior(
        expected_state="contact",
        required_outputs=("CSTATUS",),
    )
    evidence = {
        "fields": {
            "CSTATUS": {
                "status": "available",
                "values": [{"data": "closed"}, {"data": "open"}],
            },
        },
        "history": {"status": "available"},
    }
    diagnostic = expected_contact_state(evidence, expected)
    assert diagnostic.status == "ambiguous"

def test_contact_numeric_cstatus_uses_abaqus_three_state_encoding():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        required_outputs=("CSTATUS",),
    )
    evidence = {
        "fields": {
            "CSTATUS": {
                "status": "available",
                "values": [{"data": 1.0}],
            },
        },
        "history": {"status": "available"},
    }
    diagnostic = diagnose_contact(evidence, expected).diagnostics[0]
    assert diagnostic.status == "pass"
    state = expected_contact_state(evidence, expected)
    assert state.status == "pass"


def test_contact_expected_region_mismatch_is_insufficient():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        expected_regions=("Surface-A-B",),
        required_outputs=("CSTATUS",),
    )
    evidence = {
        "region": "Surface-C-D",
        "fields": {
            "CSTATUS": {
                "status": "available",
                "values": [{"data": "sticking"}],
            },
        },
        "history": {"status": "available"},
    }
    diagnostic = diagnose_contact(evidence, expected).diagnostics[0]
    assert diagnostic.status == "insufficient_evidence"

def test_contact_report_helpers_match_acceptance_blocking_statuses():
    assert ContactDiagnosticReport((
        ContactDiagnostic("x", "pass"),
        ContactDiagnostic("y", "not_applicable"),
    )).passed
    assert not ContactDiagnosticReport((
        ContactDiagnostic("x", "warning"),
    )).passed
    report = ContactDiagnosticReport((
        ContactDiagnostic("x", "insufficient_evidence"),
        ContactDiagnostic("y", "ambiguous"),
    ))
    assert not report.passed
    assert len(report.failed) == 2

def test_contact_unmapped_status_does_not_pass_as_contact():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        required_outputs=("CSTATUS",),
    )
    evidence = {
        "fields": {
            "CSTATUS": {
                "status": "available",
                "values": [{"data": 1.0}, {"data": 2.0}],
            },
        },
        "history": {"status": "available"},
    }
    diagnostic = expected_contact_state(evidence, expected)
    assert diagnostic.status == "ambiguous"


def test_contact_either_rejects_unmapped_status():
    expected = ExpectedContactBehavior(
        expected_state="either",
        required_outputs=("CSTATUS",),
    )
    evidence = {
        "fields": {
            "CSTATUS": {
                "status": "available",
                "values": [{"data": "open"}, {"data": "unknown-state"}],
            },
        },
        "history": {"status": "available"},
    }
    diagnostic = expected_contact_state(evidence, expected)
    assert diagnostic.status == "ambiguous"

def test_contact_only_cstatus_contract_does_not_require_optional_diagnostics():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        required_outputs=("CSTATUS",),
    )
    report = diagnose_contact(
        _contact_evidence(("sticking",)),
        expected,
    )
    assert report.passed
    assert all(
        item.status in ("pass", "not_applicable")
        for item in report.diagnostics
    )


def test_ambiguous_history_is_not_a_field_evidence_blocker():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        expected_regions=("Surface-A-B",),
        required_outputs=("CSTATUS",),
    )
    evidence = _contact_evidence(("sticking",))
    evidence["history"] = {
        "status": "ambiguous",
        "reason": "multiple_history_regions",
    }
    report = diagnose_contact(evidence, expected)
    assert report.passed


def test_contact_not_required_is_neutral_even_when_outputs_are_not_available():
    expected = ExpectedContactBehavior(
        contact_required=False,
        expected_state="either",
        required_outputs=("CSTATUS", "COPEN"),
    )
    report = diagnose_contact({}, expected)
    assert report.passed


def test_quantitative_contact_check_requires_explicit_region_scope():
    expected = ExpectedContactBehavior(
        expected_state="contact",
        expected_separation=0.1,
        allowed_initial_interference=0.1,
        required_outputs=("CSTATUS", "COPEN"),
    )
    evidence = _contact_evidence(("sticking",), copen=(0.01,))
    evidence["region"] = None
    report = diagnose_contact(evidence, expected)
    assert any(
        item.name == "unexpected_opening"
        and item.status == "insufficient_evidence"
        for item in report.diagnostics
    )

def test_contact_contract_requires_cstatus_for_behavior_expectation():
    import pytest
    with pytest.raises(ValueError):
        ExpectedContactBehavior(
            expected_state="contact",
            required_outputs=("COPEN",),
        )


def test_contact_contract_requires_copen_for_quantitative_limits():
    import pytest
    with pytest.raises(ValueError):
        ExpectedContactBehavior(
            expected_state="contact",
            expected_separation=0.1,
            required_outputs=("CSTATUS",),
        )
    with pytest.raises(ValueError):
        ExpectedContactBehavior(
            expected_state="contact",
            allowed_initial_interference=0.01,
            required_outputs=("CSTATUS",),
        )
