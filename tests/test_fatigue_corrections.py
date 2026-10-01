import pytest
from abaqus_ai_agent.fatigue import mean_stress_corrected_amplitude
from abaqus_ai_agent.contracts.fatigue import FatigueAnalysisIntent

def test_gerber_zero_mean_is_identity_and_tensile_mean_increases_equivalent_amplitude():
    assert mean_stress_corrected_amplitude(10, -10, 10, "GERBER", ultimate_strength=100) == pytest.approx(10.0)
    assert mean_stress_corrected_amplitude(10, 0, 20, "GERBER", ultimate_strength=100) > 10.0

def test_soderberg_requires_yield_strength():
    assert mean_stress_corrected_amplitude(10, 0, 20, "SODERBERG", yield_strength=100) > 10.0
    with pytest.raises(ValueError):
        mean_stress_corrected_amplitude(10, 0, 20, "SODERBERG")

def test_walker_matches_fe_safe_zero_mean_identity():
    assert mean_stress_corrected_amplitude(10, -10, 10, "WALKER", walker_gamma=0.5) == pytest.approx(10.0)

def test_walker_gamma_is_explicit_and_bounded():
    with pytest.raises(ValueError):
        FatigueAnalysisIntent(name="bad", mean_stress_correction="WALKER",
                              stress_variable="S11", stress_semantics="scalar_component",
                              walker_gamma=1.1, material_curve=((1, 1e6), (10, 1e3)))
    with pytest.raises(ValueError):
        mean_stress_corrected_amplitude(10, -1, 10, "WALKER", walker_gamma=0.5)

def test_fatigue_intent_accepts_explicit_correction_properties():
    intent = FatigueAnalysisIntent(
        name="gerber", mean_stress_correction="GERBER",
        ultimate_strength=200.0, stress_variable="S11",
        stress_semantics="scalar_component",
        material_curve=((1, 1e6), (100, 1e3)))
    assert intent.ultimate_strength == 200.0
