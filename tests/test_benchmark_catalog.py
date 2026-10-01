from abaqus_ai_agent.benchmark_catalog import standard_benchmarks


def test_standard_benchmark_catalog_is_deterministic_and_nonempty():
    cases = standard_benchmarks()
    assert [case.name for case in cases] == [
        "linear_elastic_axial_bar",
        "linear_elastic_cantilever",
        "gravity_static_balance",
    ]
    assert all(case.acceptance for case in cases)
    assert all(case.expected_actions for case in cases)
