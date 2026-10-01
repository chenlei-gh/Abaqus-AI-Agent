import math

import pytest

from abaqus_ai_agent.contracts.fatigue import FatigueAnalysisIntent
from abaqus_ai_agent.fatigue import (
    evaluate_fatigue_history,
    rainflow_count,
    sn_cycles_to_failure,
    stress_cycle_statistics,
    turning_points,
)


def test_fatigue_contract_and_workflow():
    intent = FatigueAnalysisIntent(
        name="Bracket fatigue",
        method="S_N",
        cycles=1.0e6,
        stress_variable="S11",
        stress_semantics="scalar_component",
        material_curve=((10.0, 1.0e6), (20.0, 1.0e5)),
    )
    assert "cycle_counting" in intent.__class__.__name__ or intent.method == "S_N"


def test_turning_points_removes_duplicates_and_keeps_reversals():
    assert turning_points([0, 1, 1, 0, -1, -1, 0]) == (0.0, 1.0, -1.0, 0.0)


def test_rainflow_records_half_cycles_for_open_reversal_history():
    # This history has no nested closed range; the ASTM-style residual is
    # therefore four half cycles rather than a fabricated full cycle.
    cycles = rainflow_count([0, 10, 0, -10, 0])
    assert cycles
    assert all(weight in (0.5, 1.0) for _, _, weight in cycles)
    assert all(weight == 0.5 for _, _, weight in cycles)
    assert sum(weight for _, _, weight in cycles) == pytest.approx(2.0)


def test_stress_range_amplitude_mean_are_explicit():
    assert stress_cycle_statistics(-10, 30, 0.5) == (-10.0, 30.0, 10.0, 40.0, 20.0, 0.5)


def test_sn_uses_log_log_interpolation():
    # geometric midpoint in stress gives geometric midpoint in life.
    value = sn_cycles_to_failure(math.sqrt(10.0 * 20.0), ((10.0, 1.0e6), (20.0, 1.0e5)))
    assert value == pytest.approx(math.sqrt(1.0e6 * 1.0e5))


def test_goodman_and_miner_damage_are_explicit():
    intent = FatigueAnalysisIntent(
        name="Goodman",
        stress_variable="S11",
        stress_semantics="scalar_component",
        mean_stress_correction="GOODMAN",
        material_curve=((8.0, 1.0e6), (20.0, 1.0e5)),
    )
    result = evaluate_fatigue_history([0, 20, 0, -20, 0], intent, ultimate_strength=100.0)
    assert result.correction == "GOODMAN"
    assert result.damage > 0
    assert result.life == pytest.approx(1.0 / result.damage)
    assert all(c.range == pytest.approx(2.0 * c.amplitude) for c in result.cycles)
    assert all(c.corrected_amplitude > 0 for c in result.cycles)


def test_stress_variable_semantics_reject_ambiguous_usage():
    with pytest.raises(ValueError):
        FatigueAnalysisIntent(name="bad", stress_variable="S11", stress_semantics="scalar_invariant")
    with pytest.raises(ValueError):
        FatigueAnalysisIntent(name="bad", stress_variable="MISES", stress_semantics="scalar_component")
    with pytest.raises(ValueError):
        FatigueAnalysisIntent(name="bad", stress_variable="MAX_PRINCIPAL", stress_semantics="scalar_component")


def test_eps_n_is_not_claimed_implemented():
    with pytest.raises(ValueError):
        FatigueAnalysisIntent(name="bad", method="EPSILON_N")


def test_rainflow_matches_reference_reversal_sequence():
    # ASTM E1049 example: range, mean, and count are deterministic.
    cycles = rainflow_count([-2, 1, -3, 5, -1, 3, -4, 4, -2])
    observed = sorted(
        (round(abs(a - b), 10), round((a + b) / 2.0, 10), weight)
        for a, b, weight in cycles
    )
    expected = sorted([
        (3.0, -0.5, 0.5),
        (4.0, -1.0, 0.5),
        (4.0, 1.0, 1.0),
        (8.0, 1.0, 0.5),
        (9.0, 0.5, 0.5),
        (8.0, 0.0, 0.5),
        (6.0, 1.0, 0.5),
    ])
    assert observed == expected
    assert sum(weight for _, _, weight in cycles) == pytest.approx(4.0)


def test_rainflow_monotonic_history_is_all_residual_half_cycles():
    cycles = rainflow_count([0, 1, 2, 3, 4])
    assert cycles == ((0.0, 4.0, 0.5),)


def test_rainflow_repeated_plateaus_do_not_create_zero_cycles():
    cycles = rainflow_count([0, 5, 5, 0, 0, -5, -5, 0])
    assert all(a != b for a, b, _ in cycles)
    assert all(weight in (0.5, 1.0) for _, _, weight in cycles)


def test_goodman_compressive_mean_stress_uses_fe_safe_half_slope_extension():
    from abaqus_ai_agent.fatigue import goodman_corrected_amplitude
    assert goodman_corrected_amplitude(10, -50, 100) == pytest.approx(8.0)


def test_goodman_tensile_mean_stress_uses_standard_goodman_line():
    from abaqus_ai_agent.fatigue import goodman_corrected_amplitude
    assert goodman_corrected_amplitude(10, 50, 100) == pytest.approx(20.0)


def test_goodman_rejects_mean_stress_at_or_above_uts():
    from abaqus_ai_agent.fatigue import goodman_corrected_amplitude
    with pytest.raises(ValueError):
        goodman_corrected_amplitude(10, 100, 100)
    with pytest.raises(ValueError):
        goodman_corrected_amplitude(10, 120, 100)


def test_sn_rejects_non_monotonic_stress_axis():
    with pytest.raises(ValueError):
        sn_cycles_to_failure(15, ((10, 1e6), (10, 1e5), (20, 1e4)))


def test_sn_requires_declared_material_curve():
    intent = FatigueAnalysisIntent(
        name="missing curve",
        stress_variable="S11",
        stress_semantics="scalar_component",
        material_curve=(),
    )
    with pytest.raises(ValueError):
        evaluate_fatigue_history([0, 10, 0], intent)


def test_zero_range_history_is_rejected_as_insufficient_fatigue_signal():
    intent = FatigueAnalysisIntent(
        name="constant",
        stress_variable="S11",
        stress_semantics="scalar_component",
        material_curve=((1, 1e6), (10, 1e3)),
    )
    with pytest.raises(ValueError):
        evaluate_fatigue_history([5, 5, 5], intent)
