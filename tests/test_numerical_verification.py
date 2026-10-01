from abaqus_ai_agent.numerical_verification import verify_series


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
