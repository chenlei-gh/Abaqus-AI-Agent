from abaqus_ai_agent.acceptance import evaluate_criteria


def test_acceptance_passes():
    result = evaluate_criteria(
        {"max_stress": 180.0},
        [{"name": "stress", "value_key": "max_stress",
          "operator": "<", "limit": 250.0, "unit": "MPa"}],
    )
    assert result.passed
    assert not result.failures


def test_acceptance_fails():
    result = evaluate_criteria(
        {"max_stress": 280.0},
        [{"name": "stress", "value_key": "max_stress",
          "operator": "<", "limit": 250.0, "unit": "MPa"}],
    )
    assert not result.passed
    assert len(result.failures) == 1


def test_acceptance_relative_tolerance_and_warning():
    result = evaluate_criteria(
        {"stress": 101.0},
        [{"name": "stress", "value_key": "stress", "operator": "<", "limit": 100.0,
          "relative_tolerance": 0.02, "unit": "MPa"}],
    )
    assert result.passed
    assert result.criteria[0].relative_error == 0.01


def test_acceptance_warns_when_tolerance_has_no_order_semantics():
    result = evaluate_criteria(
        {"stress": 100.1},
        [{"value_key": "stress", "operator": "==", "limit": 100.0,
          "relative_tolerance": 0.01}],
    )
    assert not result.passed
    assert result.warnings == ("relative_tolerance_ignored_for_==",)


def test_result_acceptance_requires_completed_solver_status():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    result = evaluate_result_acceptance(
        "completed",
        values={"max_stress": 180.0},
        criteria=[{"value_key": "max_stress", "operator": "<", "limit": 250.0}],
    )
    assert result.passed


def test_result_acceptance_does_not_treat_failed_solver_as_engineering_pass():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    result = evaluate_result_acceptance(
        "error",
        values={"max_stress": 180.0},
        criteria=[{"value_key": "max_stress", "operator": "<", "limit": 250.0}],
    )
    assert not result.passed
    assert "solver_status:error" in result.failures


def test_result_acceptance_blocks_failed_engineering_checks():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    class Checks:
        passed = False
    result = evaluate_result_acceptance(
        "completed",
        engineering=Checks(),
        values={"max_stress": 180.0},
        criteria=[{"value_key": "max_stress", "operator": "<", "limit": 250.0}],
    )
    assert not result.passed
    assert "engineering_checks_failed" in result.failures

def test_result_acceptance_contact_only_status_mapping():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    from abaqus_ai_agent.contracts.contact import (
        ContactDiagnostic,
        ContactDiagnosticReport,
    )

    cases = (
        ("pass", True, ()),
        ("warning", True, ()),
        ("fail", False, ("contact:contact_state:fail",)),
        ("insufficient_evidence", False, (
            "contact:contact_state:insufficient_evidence",
        )),
        ("ambiguous", False, ("contact:contact_state:ambiguous",)),
        ("not_applicable", True, ()),
    )
    for diagnostic_status, expected_passed, expected_failures in cases:
        result = evaluate_result_acceptance(
            "completed",
            values=None,
            criteria=(),
            contact_diagnostics=ContactDiagnosticReport((
                ContactDiagnostic("contact_state", diagnostic_status),
            )),
        )
        assert result.passed is expected_passed
        assert result.failures == expected_failures



def test_result_acceptance_benchmark_failure_blocks_without_solver_failure():
    from abaqus_ai_agent.acceptance import evaluate_result_acceptance
    from abaqus_ai_agent.contracts.benchmarks import BenchmarkCase, BenchmarkResult

    case = BenchmarkCase("case", "reference")
    benchmark = BenchmarkResult(
        case=case,
        passed=False,
        failures=("missing_reference:x",),
    )
    result = evaluate_result_acceptance(
        "completed",
        values={},
        criteria=(),
        benchmark_result=benchmark,
    )
    assert result.passed is False
    assert result.failures == ("benchmark:missing_reference:x",)
