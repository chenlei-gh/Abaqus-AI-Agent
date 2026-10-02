import pytest
from math import isfinite
from abaqus_ai_agent.fatigue import (
    compute_scalar_stress,
    evaluate_cycle_life,
    accumulate_palmgren_miner_damage,
    evaluate_fatigue_from_stress_history,
    build_odb_fatigue_postprocess_script,
)


def test_compute_scalar_stress_signed_mises():
    # Tensile hydrostatic stress (trace > 0) -> positive signed Mises
    rec_tensile = {
        "mises": 200.0,
        "data": [100.0, 50.0, 10.0, 0.0, 0.0, 0.0],
    }
    assert compute_scalar_stress(rec_tensile, "signed_mises") == 200.0

    # Compressive hydrostatic stress (trace < 0) -> negative signed Mises
    rec_compressive = {
        "mises": 250.0,
        "data": [-150.0, -80.0, -20.0, 0.0, 0.0, 0.0],
    }
    assert compute_scalar_stress(rec_compressive, "signed_mises") == -250.0

    # Fallback to maxPrincipal if data is not available
    rec_principal = {
        "mises": 150.0,
        "maxPrincipal": -30.0,
    }
    assert compute_scalar_stress(rec_principal, "signed_mises") == -150.0


def test_compute_scalar_stress_other_measures():
    rec = {
        "mises": 180.0,
        "maxPrincipal": 210.0,
        "tresca": 220.0,
        "data": [100.0, 50.0, -20.0, 15.0, 0.0, 0.0],
    }
    assert compute_scalar_stress(rec, "von_mises") == 180.0
    assert compute_scalar_stress(rec, "max_principal") == 210.0
    assert compute_scalar_stress(rec, "tresca") == 220.0
    assert compute_scalar_stress(rec, "s11") == 100.0
    assert compute_scalar_stress(rec, "s22") == 50.0
    assert compute_scalar_stress(rec, "s12") == 15.0


def test_compute_scalar_stress_validation():
    with pytest.raises(ValueError, match="stress_record must be a dictionary"):
        compute_scalar_stress("invalid")

    with pytest.raises(ValueError, match="requires 'mises' field"):
        compute_scalar_stress({}, "signed_mises")

    with pytest.raises(ValueError, match="unsupported multiaxial fatigue measure"):
        compute_scalar_stress({"mises": 10.0}, "unknown_measure")


def test_evaluate_cycle_life_endurance_limit():
    sn_curve = (
        (100.0, 1.0e7),
        (200.0, 1.0e6),
        (400.0, 1.0e4),
    )
    # Below endurance limit -> infinite life
    assert evaluate_cycle_life(50.0, sn_curve, endurance_limit_infinite=True) == float("inf")

    # Above max curve stress -> returns highest stress life limit
    assert evaluate_cycle_life(500.0, sn_curve) == 1.0e4

    # Exact point match
    assert evaluate_cycle_life(200.0, sn_curve) == pytest.approx(1.0e6, rel=1e-6)

    # Log-log interpolation between 200 MPa and 400 MPa
    life_mid = evaluate_cycle_life(282.84, sn_curve)
    assert 1.0e4 < life_mid < 1.0e6


def test_accumulate_palmgren_miner_damage():
    sn_curve = (
        (100.0, 1.0e7),
        (300.0, 1.0e5),
        (600.0, 1.0e3),
    )
    cycles = (
        (600.0, 0.0, 1.0),      # amp=300 MPa, mean=0 -> Nf=1e5, damage=1e-5
        (50.0, 10.0, 1.0),       # amp=25 MPa (below 100 MPa endurance limit) -> damage=0
    )
    total_damage, details = accumulate_palmgren_miner_damage(
        cycles, material_curve=sn_curve, ultimate_strength=800.0
    )
    assert len(details) == 2
    assert abs(total_damage - 1.0e-5) < 1.0e-10
    assert details[0]["life_cycles"] == pytest.approx(1.0e5, rel=1e-6)
    assert details[1]["life_cycles"] == float("inf")
    assert details[1]["damage"] == 0.0


def test_evaluate_fatigue_from_stress_history_full_pipeline():
    # Alternating sinusoidal stress history: 0 -> 300 -> -300 -> 300 -> -300 -> 0
    stresses = (0.0, 150.0, 300.0, 0.0, -300.0, 0.0, 300.0, 0.0, -300.0, 0.0)
    times = tuple(float(i) * 0.1 for i in range(len(stresses)))
    sn_curve = (
        (100.0, 1.0e7),
        (300.0, 1.0e5),
        (600.0, 1.0e3),
    )
    result = evaluate_fatigue_from_stress_history(
        times=times,
        stresses=stresses,
        material_curve=sn_curve,
        ultimate_strength=800.0,
        mean_stress_correction="GOODMAN",
    )
    assert result["status"] == "pass"
    assert result["passed"] is True
    assert result["cycle_summary"]["total_cycles_count"] > 0
    assert result["cycle_summary"]["cumulative_damage"] > 0.0
    assert result["cycle_summary"]["cumulative_damage"] < 1.0
    assert isfinite(result["cycle_summary"]["life_blocks"])
    assert result["acceptance"]["passed"] is True

    # Negative gate verification: strict threshold should fail as cumulative damage > 1e-15
    assert result["strict_gate"]["passed"] is False
    assert result["strict_gate"]["expected_fail"] is True


def test_build_odb_fatigue_postprocess_script():
    script = build_odb_fatigue_postprocess_script(
        odb_path="test.odb",
        output_json="out.json",
        material_curve=((100.0, 1.0e6), (200.0, 1.0e4)),
        ultimate_strength=750.0,
    )
    assert "extract_stress_history_from_odb" in script
    assert "evaluate_fatigue_from_stress_history" in script
    assert "AIAgent_FATIGUE_EVALUATION_COMPLETED" in script
    assert "test.odb" in script
    assert "out.json" in script
