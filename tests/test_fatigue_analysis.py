from abaqus_ai_agent.fatigue import (
    goodman_corrected_amplitude, rainflow_count,
    reduce_multiaxial_history, sn_life, miner_damage, fatigue_life_blocks, stress_range_and_amplitude,
)


def test_range_and_amplitude():
    assert stress_range_and_amplitude(-10, 30) == (40.0, 20.0)


def test_rainflow_full_and_half_cycles():
    cycles = rainflow_count((0, 10, 0, 10, 0))
    assert all(rng == 10.0 and count == 0.5 for rng, _, count in cycles)
    assert sum(count for _, _, count in cycles) == 1.0


def test_goodman_positive_mean_boundary():
    assert goodman_corrected_amplitude(10, -20, 100) == 10.0
    assert goodman_corrected_amplitude(10, 20, 100) == 12.5
    try:
        goodman_corrected_amplitude(10, 100, 100)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid Goodman boundary was accepted")


def test_multiaxial_measure_is_explicit():
    assert reduce_multiaxial_history(({"mises": 10.0},), "von_mises") == (10.0,)
    try:
        reduce_multiaxial_history(({"s11": 1.0},), "von_mises")
    except ValueError:
        pass
    else:
        raise AssertionError("implicit multiaxial reduction was accepted")


def test_sn_log_interpolation():
    assert abs(sn_life(10.0, ((10.0, 1e6), (20.0, 1e5))) - 1e6) < 1e-9


def test_miner_damage_and_repeated_spectrum_life():
    spectrum = ((20.0, 0.0, 1.0),)
    curve = ((10.0, 1e6), (20.0, 1e5))
    assert miner_damage(spectrum, curve) == 1e-5
    assert fatigue_life_blocks(spectrum, curve) == 1e5


    spectrum = ((20.0, 0.0, 1.0),)
    curve = ((10.0, 1e6), (20.0, 1e5))
    assert abs(miner_damage(spectrum, curve) - 1e-6) < 1e-12
    assert abs(fatigue_life_blocks(spectrum, curve) - 1e6) < 1e-6
