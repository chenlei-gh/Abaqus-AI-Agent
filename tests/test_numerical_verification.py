import pytest
from abaqus_ai_agent.numerical_verification import (\n    verify_series, verify_richardson, assess_singularity_interpretation,\n)


def test_verify_series_insufficient_data_is_explicit():
    result = verify_series("mesh", (100.0,), 0.01)
    assert not result.passed
    assert result.status == "insufficient_data"
    assert result.method == "successive_relative_change"


def test_verify_series_reports_explicit_method_and_message():
    result = verify_series("mesh", (100.0, 100.5, 100.45), 0.01)
    assert result.passed
    assert result.method == "successive_relative_change"
    assert result.message == "relative_change=%g" % result.error


def test_verify_richardson_returns_order_and_gci():
    # Synthetic second-order convergence to a limit of 1.0:
    # 1 + 1/4, 1 + 1/16, 1 + 1/64.
    result = verify_richardson(
        "tip_displacement", (1.25, 1.0625, 1.015625),
        refinement_ratio=2.0, tolerance=0.10,
    )
    assert result.passed
    assert result.method == "richardson_gci"
    assert abs(result.observed_order - 2.0) < 1e-9
    assert result.gci is not None
    assert result.extrapolated_value is not None


def test_verify_richardson_requires_three_levels():
    result = verify_richardson(
        "mesh", (1.0, 1.1), refinement_ratio=2.0, tolerance=0.1
    )
    assert not result.passed
    assert result.status == "insufficient_data"


def test_verify_richardson_rejects_invalid_ratio():
    try:
        verify_richardson("mesh", (1.0, 1.1, 1.05), 1.0, 0.1)
    except ValueError:
        pass
    else:
        raise AssertionError("refinement ratio must be > 1")


def test_execute_refinement_study_uses_analysis_runner_and_existing_results():
    from abaqus_ai_agent.contracts.numerical import NumericalRefinementCase
    from abaqus_ai_agent.numerical_verification import execute_refinement_study

    class Run:
        state = type("S", (), {"value": "accepted"})()
        id = "run-1"
        acceptance_passed = True
        evidence = ()
        provenance = None
        diagnostics = ()
        metadata = {"result_values": {"tip": 1.01}}

    class Runner:
        calls = []
        def run(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return Run()

    cases = (
        NumericalRefinementCase("coarse", 4.0, action_plan=({"action_type": "python"},)),
        NumericalRefinementCase("medium", 2.0, action_plan=({"action_type": "python"},)),
        NumericalRefinementCase("fine", 1.0, action_plan=({"action_type": "python"},)),
    )
    runner = Runner()
    report = execute_refinement_study(
        object(), runner, "mesh", "element_size", "Model", "Job",
        cases, criteria=({"value_key": "tip"},), tolerance=0.01, value_key="tip",
    )
    assert report.passed
    assert report.dimension == "element_size"
    assert len(runner.calls) == 3
    assert runner.calls[0][1]["action_plan"] == ({"action_type": "python"},)


def test_execute_refinement_study_fails_closed_without_application_plan():
    from abaqus_ai_agent.contracts.numerical import NumericalRefinementCase
    from abaqus_ai_agent.numerical_verification import execute_refinement_study

    report = execute_refinement_study(
        object(), object(), "time", "time_step", "Model", "Job",
        (NumericalRefinementCase("dt1", 0.1),),
        criteria=({"value_key": "u"},), tolerance=0.01, value_key="u",
    )
    assert not report.passed
    assert report.failed_cases[0]["diagnostics"][0]["reason"] == "refinement_action_plan_required"


def test_execute_refinement_study_uses_richardson_for_three_levels():
    from abaqus_ai_agent.contracts.numerical import NumericalRefinementCase
    from abaqus_ai_agent.numerical_verification import execute_refinement_study

    class Runner:
        def run(self, *args, **kwargs):
            value = {"coarse": 1.25, "medium": 1.0625, "fine": 1.015625}[args[1].split("_")[-1]]
            return type("Run", (), {
                "state": type("S", (), {"value": "accepted"})(),
                "id": args[1], "acceptance_passed": True, "evidence": (),
                "provenance": None, "diagnostics": (),
                "metadata": {"result_values": {"tip": value}},
            })()

    cases = tuple(
        NumericalRefinementCase(name, value, action_plan=({"action_type": "python"},))
        for name, value in (("coarse", 4.0), ("medium", 2.0), ("fine", 1.0))
    )
    report = execute_refinement_study(
        object(), Runner(), "mesh", "element_size", "Model", "Job",
        cases, criteria=({"value_key": "tip"},), tolerance=0.10,
        method="richardson_gci", refinement_ratio=2.0, value_key="tip",
    )
    assert report.passed
    assert report.verification.observed_order == pytest.approx(2.0)


def test_singularity_interpretation_requires_explicit_basis():
    result = assess_singularity_interpretation(
        identified=True,
        basis="explicit geometric corner stress concentration",
        local_values=(10.0, 15.0, 22.0),
        global_values=(5.0, 5.1, 5.05),
    )
    assert result["status"] == "identified"
    assert result["interpretation"] == "singularity_limited"
    assert result["local_trend"] == (10.0, 15.0, 22.0)


def test_singularity_is_not_inferred_from_nonconvergence():
    result = assess_singularity_interpretation(
        identified=False,
        local_values=(10.0, 20.0, 40.0),
        global_values=(5.0, 5.5, 5.2),
    )
    assert result["interpretation"] == "global"
    assert result["status"] == "not_identified"


def test_singularity_identification_requires_basis():
    with pytest.raises(ValueError):
        assess_singularity_interpretation(identified=True)
