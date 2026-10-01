from abaqus_ai_agent.contracts.experimental_validation import ExperimentalObservation
from abaqus_ai_agent.experimental_validation import validate_observations


def test_experimental_validation_uses_explicit_tolerance():
    report = validate_observations((
        ExperimentalObservation(
            "tip_displacement", 10.0, 10.2, tolerance=0.5, unit="mm",
            uncertainty=0.3, source="test-rig-01"
        ),
    ))
    result = report.results[0]
    assert report.passed
    assert result.error == 0.2
    assert result.relative_error == 0.02
    assert result.uncertainty == 0.3
    assert result.source == "test-rig-01"


def test_experimental_uncertainty_does_not_silently_relax_tolerance():
    report = validate_observations((
        ExperimentalObservation(
            "reaction", 100.0, 102.0, tolerance=1.0, uncertainty=5.0
        ),
    ))
    assert report.passed is False


def test_zero_measurement_has_no_relative_error_but_absolute_check():
    report = validate_observations((
        ExperimentalObservation("residual", 0.0, 0.01, tolerance=0.02),
    ))
    result = report.results[0]
    assert result.relative_error is None
    assert result.passed


def test_empty_validation_does_not_pass():
    from abaqus_ai_agent.contracts.experimental_validation import ExperimentalValidationReport
    assert ExperimentalValidationReport().passed is False
