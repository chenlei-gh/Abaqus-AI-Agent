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
