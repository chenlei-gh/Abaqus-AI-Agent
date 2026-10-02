import json
from pathlib import Path
from tools.h7_sensitivity_uncertainty_e2e import run_h7_sensitivity_uncertainty


def test_h7_sensitivity_uncertainty_e2e():
    evidence = run_h7_sensitivity_uncertainty()
    assert evidence["status"] == "PASS"
    assert evidence["sensitivity"]["cases_count"] == 4
    assert evidence["sensitivity"]["e_perturbation_stress_invariance_verified"] is True
    assert evidence["sensitivity"]["load_perturbation_linearity_verified"] is True

    bounds = evidence["uncertainty"]["bounds"]
    assert bounds["tip_displacement"]["min"] < bounds["tip_displacement"]["nominal"] < bounds["tip_displacement"]["max"]
    assert bounds["root_mises"]["min"] < bounds["root_mises"]["nominal"] < bounds["root_mises"]["max"]

    ev_path = Path("machine_validation") / "h7_sensitivity_uncertainty_evidence.json"
    assert ev_path.exists()
