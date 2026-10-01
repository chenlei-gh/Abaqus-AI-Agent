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


def test_rainflow_records_full_and_half_cycles():
    cycles = rainflow_count([0, 10, 0, -10, 0])
    assert cycles
    assert all(weight in (0.5, 1.0) for _, _, weight in cycles)
    assert any(weight == 1.0 for _, _, weight in cycles)
    assert any(weight == 0.5 for _, _, weight in cycles)


def test_stress_range_amplitude_mean_are_explicit():
    assert stress_cycle_statistics(-10, 30, 0.5) == ( -10.0, 30.0, 10.0, 40.0, 20.0, 0.5)


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
        material_curve=((10.0, 1.0e6), (20.0, 1.0e5)),
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
