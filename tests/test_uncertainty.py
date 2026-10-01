import pytest

from abaqus_ai_agent.contracts.uncertainty import (
    UncertaintyParameter,
    UncertaintyScenario,
)
from abaqus_ai_agent.uncertainty import (
    aggregate_uncertainty_outputs,
    build_uncertainty_scenarios,
    execute_uncertainty,
)


def test_uncertainty_parameter_validates_finite_bounds():
    UncertaintyParameter("load", 100.0, 90.0, 110.0, "N")
    with pytest.raises(ValueError):
        UncertaintyParameter("load", float("inf"), 90.0, 110.0, "N")
    with pytest.raises(ValueError):
        UncertaintyParameter("load", 100.0, 110.0, 90.0, "N")


def test_uncertainty_scenario_normalizes_identity_without_applying_parameters():
    scenarios = build_uncertainty_scenarios(
        "Model-1",
        "Job-1",
        (UncertaintyScenario("low_load", {"load": 90.0}),),
    )
    assert scenarios[0].model_name == "Model-1"
    assert scenarios[0].job_name == "Job-1_low_load"
    assert scenarios[0].parameters == {"load": 90.0}


def test_uncertainty_requires_explicit_application_plan():
    report, aggregate = execute_uncertainty(
        executor=object(),
        runner=object(),
        model_name="Model-1",
        job_name="Job-1",
        scenarios=(UncertaintyScenario("low_load", {"load": 90.0}),),
    )
    assert not report.completed
    assert report.failed_cases[0]["diagnostics"][0]["reason"] == "scenario_action_plan_required"
    assert aggregate == ()


def test_uncertainty_executes_each_scenario_through_analysis_runner():
    class Provenance:
        run_id = "run-1"

    class Evidence:
        items = ("evidence",)

    class Run:
        state = type("State", (), {"value": "accepted"})()
        id = "run-1"
        odb_path = "/tmp/Job.odb"
        provenance = Provenance()
        acceptance_passed = True
        evidence = Evidence()
        diagnostics = ()
        metadata = {"result_values": {"stress": 120.0}}

    class Runner:
        def __init__(self):
            self.calls = []

        def run(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return Run()

    runner = Runner()
    scenario = UncertaintyScenario(
        "high_load",
        {"load": 110.0},
        action_plan=({"action_type": "python"},),
    )
    report, aggregate = execute_uncertainty(
        executor=object(),
        runner=runner,
        model_name="Model-1",
        job_name="Job-1",
        scenarios=(scenario,),
        criteria=({"value_key": "stress", "operator": "<=", "limit": 150.0},),
    )

    assert report.completed
    assert report.outputs[0]["status"] == "completed"
    assert report.outputs[0]["values"] == {"stress": 120.0}
    assert runner.calls[0][0] == ("Model-1", "Job-1_high_load")
    assert runner.calls[0][1]["action_plan"] == ({"action_type": "python"},)
    assert runner.calls[0][1]["environment"]["uncertainty_parameters"] == {"load": 110.0}
    assert aggregate == ({
        "value_key": "stress",
        "min": 120.0,
        "max": 120.0,
        "mean": 120.0,
        "range": 0.0,
        "count": 1,
    },)


def test_uncertainty_can_supply_plans_separately_from_scenarios():
    class Run:
        state = type("State", (), {"value": "accepted"})()
        id = "run-2"
        odb_path = None
        provenance = None
        acceptance_passed = True
        evidence = None
        diagnostics = ()
        metadata = {"result_values": {"u": 1.0}}

    class Runner:
        calls = []

        def run(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return Run()

    runner = Runner()
    scenario = UncertaintyScenario("nominal", {"load": 100.0})
    report, _ = execute_uncertainty(
        object(), runner, "Model", "Job", (scenario,),
        scenario_action_plans={"nominal": ({"action_type": "python"},)},
    )
    assert report.completed
    assert runner.calls[0][1]["action_plan"] == ({"action_type": "python"},)


def test_uncertainty_aggregation_ignores_failed_cases():
    result = aggregate_uncertainty_outputs((
        {"status": "completed", "values": {"stress": 10.0}},
        {"status": "completed", "values": {"stress": 20.0}},
        {"status": "failed", "values": {"stress": 999.0}},
    ))
    assert result[0]["min"] == 10.0
    assert result[0]["max"] == 20.0
    assert result[0]["mean"] == 15.0
    assert result[0]["range"] == 10.0
    assert result[0]["count"] == 2


def test_uniform_uncertainty_sampling_is_reproducible_and_bounded():
    from abaqus_ai_agent.uncertainty import sample_uniform_parameters
    parameter = UncertaintyParameter("load", 100.0, 90.0, 110.0, "N")
    first = sample_uniform_parameters((parameter,), 5, seed=7)
    second = sample_uniform_parameters((parameter,), 5, seed=7)
    assert first == second
    assert all(90.0 <= item["load"] <= 110.0 for item in first)


def test_probabilistic_summary_reports_sample_statistics():
    from abaqus_ai_agent.uncertainty import summarize_probabilistic_outputs
    summary = summarize_probabilistic_outputs((
        {"status": "completed", "values": {"stress": 10.0}},
        {"status": "completed", "values": {"stress": 20.0}},
        {"status": "completed", "values": {"stress": 30.0}},
        {"status": "failed", "values": {"stress": 999.0}},
    ))
    assert summary[0]["count"] == 3
    assert summary[0]["mean"] == 20.0
    assert summary[0]["min"] == 10.0
    assert summary[0]["max"] == 30.0
    assert summary[0]["quantiles"]["0.5"] == 20.0


def test_probabilistic_execution_requires_explicit_action_plan_factory():
    from abaqus_ai_agent.uncertainty import execute_probabilistic_uncertainty
    parameter = UncertaintyParameter("load", 100.0, 90.0, 110.0)
    with pytest.raises(TypeError):
        execute_probabilistic_uncertainty(
            object(), object(), "Model", "Job", (parameter,), 2, None
        )
