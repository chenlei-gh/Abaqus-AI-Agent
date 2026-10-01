from abaqus_ai_agent.numerical_verification import verify_series, verify_richardson


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
