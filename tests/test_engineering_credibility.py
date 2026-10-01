from abaqus_ai_agent.engineering_checks import check_balance, evaluate_checks
from abaqus_ai_agent.provenance import stable_hash, hash_text
from abaqus_ai_agent.sensitivity import evaluate_sensitivity
from abaqus_ai_agent.contracts.sensitivity import SensitivityCase
from abaqus_ai_agent.correction import can_retry, select_repairs, can_apply_repair
from abaqus_ai_agent.contracts.correction import CorrectionPolicy, RepairCandidate
from abaqus_ai_agent.numerical_verification import verify_series
from abaqus_ai_agent.contact_diagnostics import evaluate_contact_checks
from abaqus_ai_agent.contracts.contact import ContactDiagnostic
from abaqus_ai_agent.contracts.uncertainty import UncertaintyParameter


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
