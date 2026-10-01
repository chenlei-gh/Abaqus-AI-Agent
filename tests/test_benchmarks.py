from abaqus_ai_agent.benchmarks import evaluate_benchmark
from abaqus_ai_agent.contracts.benchmarks import BenchmarkCase


def test_benchmark_records_evidence_and_passes_tolerance():
    case = BenchmarkCase(
        name="cantilever",
        description="simple reference case",
        acceptance=(
            {"value_key": "tip_displacement", "operator": "<=", "limit": 10.0,
             "relative_tolerance": 0.05},
        ),
    )
    result = evaluate_benchmark(case, {"tip_displacement": 10.4}, case.acceptance)
    assert result.passed
    assert result.evidence[0]["passed"] is True
    assert result.evidence[0]["actual"] == 10.4


def test_benchmark_missing_observation_is_failure():
    case = BenchmarkCase("case", "reference")
    result = evaluate_benchmark(
        case, {}, ({"value_key": "reaction", "operator": "==", "limit": 100.0},)
    )
    assert not result.passed
    assert result.failures == ("missing:reaction",)
    assert result.evidence[0]["status"] == "missing"


def test_benchmark_rejects_unknown_operator():
    case = BenchmarkCase("case", "reference")
    try:
        evaluate_benchmark(
            case, {"x": 1.0}, ({"value_key": "x", "operator": "~", "limit": 1.0},)
        )
    except ValueError:
        pass
    else:
        raise AssertionError("unknown benchmark operator must fail")



def test_benchmark_derives_relative_error_only_from_explicit_reference():
    from abaqus_ai_agent.benchmarks import derive_benchmark_observations

    case = BenchmarkCase(
        "case",
        "reference",
        acceptance=(
            {
                "value_key": "displacement_error",
                "observed_value_key": "displacement",
                "metric": "relative_error",
                "reference_key": "reference_displacement",
                "operator": "<=",
                "limit": 0.02,
            },
        ),
    )
    observed, evidence, failures = derive_benchmark_observations(
        case,
        {"displacement": 10.2},
        {"reference_displacement": 10.0},
    )
    assert failures == ()
    assert observed["displacement_error"] == 0.02
    assert evidence[0]["reference"] == 10.0


def test_benchmark_missing_reference_is_explicit_failure():
    from abaqus_ai_agent.benchmarks import derive_benchmark_observations

    case = BenchmarkCase(
        "case",
        "reference",
        acceptance=(
            {
                "value_key": "displacement_error",
                "observed_value_key": "displacement",
                "metric": "relative_error",
                "operator": "<=",
                "limit": 0.02,
            },
        ),
    )
    observed, _, failures = derive_benchmark_observations(case, {"displacement": 10.0})
    assert observed == {}
    assert failures == ("missing_reference:displacement_error",)


def test_benchmark_result_criteria_preserves_explicit_odb_mapping():
    from abaqus_ai_agent.benchmarks import benchmark_result_criteria

    case = BenchmarkCase(
        "case",
        "reference",
        acceptance=(
            {
                "value_key": "tip_error",
                "observed_value_key": "tip",
                "operator": "<=",
                "limit": 0.05,
                "result": {
                    "field": "U",
                    "invariant": "MAGNITUDE",
                    "aggregation": "max",
                    "step": "Step-1",
                },
            },
        ),
    )
    criteria = benchmark_result_criteria(case)
    assert criteria[0]["value_key"] == "tip"
    assert criteria[0]["field"] == "U"
    assert criteria[0]["step"] == "Step-1"



def test_benchmark_zero_reference_requires_absolute_error():
    from abaqus_ai_agent.benchmarks import derive_benchmark_observations

    case = BenchmarkCase(
        "case",
        "reference",
        acceptance=(
            {
                "value_key": "error",
                "observed_value_key": "value",
                "metric": "relative_error",
                "reference_key": "reference",
                "operator": "<=",
                "limit": 0.01,
            },
        ),
    )
    observed, _, failures = derive_benchmark_observations(
        case, {"value": 0.1}, {"reference": 0.0}
    )
    assert observed == {}
    assert failures == ("zero_reference_requires_absolute_error:reference",)



def test_benchmark_reference_metadata_is_preserved_in_evidence():
    from abaqus_ai_agent.benchmarks import derive_benchmark_observations

    case = BenchmarkCase(
        "case",
        "reference",
        acceptance=(
            {
                "value_key": "error",
                "observed_value_key": "value",
                "metric": "relative_error",
                "reference_key": "reference",
                "operator": "<=",
                "limit": 0.05,
            },
        ),
    )
    _, evidence, failures = derive_benchmark_observations(
        case,
        {"value": 10.5},
        {"reference": {"value": 10.0, "source": "analytical PL/(AE)", "unit": "mm"}},
    )
    assert failures == ()
    assert evidence[0]["reference_source"] == "analytical PL/(AE)"
    assert evidence[0]["reference_unit"] == "mm"
