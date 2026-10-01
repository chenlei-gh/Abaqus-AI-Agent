from abaqus_ai_agent.engineering_evidence import (
    reaction_balance_from_field_evidence,
    energy_ratio_from_history_evidence,
)


def test_reaction_balance_adapter():
    evidence = {
        "status": "available",
        "values": [
            {"data": (-100.0, 0.0, 0.0)},
            {"data": (0.0, 0.0, 0.0)},
        ],
    }
    report, reaction = reaction_balance_from_field_evidence(
        evidence, (100.0, 0.0, 0.0), 0.01, "N"
    )
    assert report.passed
    assert reaction["components"] == (-100.0, 0.0, 0.0)


def test_reaction_balance_requires_available_evidence():
    try:
        reaction_balance_from_field_evidence(
            {"status": "unavailable"}, (100.0, 0.0, 0.0), 0.01, "N"
        )
    except ValueError:
        pass
    else:
        raise AssertionError("unavailable reaction evidence must fail")


def test_energy_ratio_adapter_uses_last_sample():
    evidence = {
        "status": "available",
        "variables": {
            "ALLAE": {"status": "available", "data": [(0.0, 0.0), (1.0, 1.0)]},
            "ALLIE": {"status": "available", "data": [(0.0, 50.0), (1.0, 100.0)]},
        },
    }
    check, values = energy_ratio_from_history_evidence(
        evidence, "ALLAE", "ALLIE", 0.02
    )
    assert check.passed
    assert values == {"numerator": 1.0, "denominator": 100.0}


def test_energy_ratio_requires_both_history_series():
    try:
        energy_ratio_from_history_evidence(
            {"status": "available", "variables": {"ALLIE": None}},
            "ALLAE", "ALLIE", 0.02,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("incomplete history evidence must fail")
