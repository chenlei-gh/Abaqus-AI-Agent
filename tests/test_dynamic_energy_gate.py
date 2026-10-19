"""Acceptance-gate wiring for the dynamic energy balance contract.

The contract itself is covered in test_dynamic_energy.py. These tests verify the
gate semantics: a physical violation must FAIL, absent or incomplete evidence must
BLOCK delivery, and an opt-in gate must never silently become an enforcement that
the caller never requested.
"""

import pytest

from abaqus_ai_agent.acceptance import CANONICAL_GATE_ORDER, evaluate_result_acceptance

_REAL_IMPLICIT = {
    "ALLIE": [
        (0.0, 0.0), (0.00788281206041574, 1034.71032714844),
        (0.0178828127682209, 996.005187988281), (0.0199999995529652, 1013.96575927734),
    ],
    "ALLKE": [
        (0.0, 0.0), (0.00788281206041574, 1.23314929008484),
        (0.0178828127682209, 0.00682488782331347), (0.0199999995529652, 0.148330762982368),
    ],
    "ALLWK": [
        (0.0, 0.0), (0.00788281206041574, 1037.33020019531),
        (0.0178828127682209, 998.300476074219), (0.0199999995529652, 1016.50921630859),
    ],
    "ETOTAL": [
        (0.0, 0.0), (0.00788281206041574, -1.38669860363007),
        (0.0178828127682209, -2.28848218917847), (0.0199999995529652, -2.39511466026306),
    ],
}


def _accept(**kwargs):
    base = dict(
        result_status="completed",
        values={"stress": 120.0},
        criteria=[{
            "name": "stress", "value_key": "stress", "operator": "<", "limit": 200.0,
        }],
    )
    base.update(kwargs)
    return evaluate_result_acceptance(**base)


def test_gate_is_skipped_when_not_requested():
    res = _accept()
    assert res.gates["dynamic_energy"] == "SKIPPED"
    assert res.status == "PASS"
    assert res.deliverable is True
    assert res.dynamic_energy is None


def test_gate_is_skipped_for_a_static_analysis_even_when_evidence_is_supplied():
    res = _accept(
        dynamic_energy={"variables": _REAL_IMPLICIT},
        dynamic_energy_threshold=0.01,
        dynamic_energy_solver_product="standard",
        dynamic_energy_enabled=True,
        analysis_is_dynamic=False,
    )
    assert res.gates["dynamic_energy"] == "SKIPPED"
    assert res.status == "PASS"


def test_within_threshold_passes_and_records_the_evidence():
    res = _accept(
        dynamic_energy={"variables": _REAL_IMPLICIT},
        dynamic_energy_threshold=0.01,
        dynamic_energy_threshold_source="intent.metadata.dynamic_energy_threshold",
        dynamic_energy_solver_product="standard",
        dynamic_energy_enabled=True,
    )
    assert res.gates["dynamic_energy"] == "PASS"
    assert res.status == "PASS"
    assert res.deliverable is True
    assert res.dynamic_energy["ratio"] == pytest.approx(2.39511466026306 / 1037.33020019531)
    assert res.dynamic_energy["threshold_source"] == "intent.metadata.dynamic_energy_threshold"


def test_exceeded_drift_is_a_physical_failure():
    res = _accept(
        dynamic_energy={"variables": _REAL_IMPLICIT},
        dynamic_energy_threshold=0.001,
        dynamic_energy_solver_product="standard",
        dynamic_energy_enabled=True,
    )
    assert res.gates["dynamic_energy"] == "FAIL"
    assert res.acceptance_status == "FAIL"
    assert res.status == "FAIL"
    assert res.deliverable is False
    assert any(f.startswith("dynamic_energy_exceeded:") for f in res.findings.failures)


def test_missing_evidence_blocks_without_fabricating_a_failure():
    res = _accept(
        dynamic_energy={"variables": {}},
        dynamic_energy_threshold=0.01,
        dynamic_energy_solver_product="standard",
        dynamic_energy_enabled=True,
    )
    assert res.gates["dynamic_energy"] == "BLOCKED"
    assert res.acceptance_status == "BLOCKED"
    assert res.deliverable is False
    assert any(
        f.startswith("dynamic_energy_unverifiable:missing_total_energy_history")
        for f in res.findings.failures
    )


def test_undeclared_solver_product_blocks():
    res = _accept(
        dynamic_energy={"variables": _REAL_IMPLICIT},
        dynamic_energy_threshold=0.01,
        dynamic_energy_enabled=True,
    )
    assert res.gates["dynamic_energy"] == "BLOCKED"
    assert res.acceptance_status == "BLOCKED"
    assert any(
        "dynamic_energy_solver_product_not_declared" in f for f in res.findings.failures
    )


def test_missing_threshold_blocks_instead_of_assuming_a_default():
    res = _accept(
        dynamic_energy={"variables": _REAL_IMPLICIT},
        dynamic_energy_solver_product="standard",
        dynamic_energy_enabled=True,
    )
    assert res.gates["dynamic_energy"] == "BLOCKED"
    assert any(
        "dynamic_energy_threshold_not_configured" in f for f in res.findings.failures
    )


def test_incomplete_evidence_blocks_delivery():
    variables = {name: data[1:2] for name, data in _REAL_IMPLICIT.items()}
    res = _accept(
        dynamic_energy={"variables": variables},
        dynamic_energy_threshold=0.01,
        dynamic_energy_solver_product="standard",
        dynamic_energy_enabled=True,
    )
    assert res.gates["dynamic_energy"] == "INCOMPLETE"
    assert res.acceptance_status == "BLOCKED"
    assert res.deliverable is False
    assert any(
        f.startswith("dynamic_energy_incomplete:insufficient_informative_frames")
        for f in res.findings.failures
    )


def test_gate_does_not_regress_other_passing_gates():
    res = _accept(
        dynamic_energy={"variables": _REAL_IMPLICIT},
        dynamic_energy_threshold=0.01,
        dynamic_energy_solver_product="standard",
        dynamic_energy_enabled=True,
    )
    assert res.gates["criteria"] == "PASS"
    assert all(c.passed for c in res.criteria)


def test_gate_respects_canonical_order():
    res = _accept(
        dynamic_energy={"variables": _REAL_IMPLICIT},
        dynamic_energy_threshold=0.01,
        dynamic_energy_solver_product="standard",
        dynamic_energy_enabled=True,
    )
    keys = list(res.gates.keys())
    order = {name: i for i, name in enumerate(CANONICAL_GATE_ORDER)}
    indices = [order[k] for k in keys if k in order]
    assert indices == sorted(indices)
    assert "dynamic_energy" in keys


def test_explicit_verdict_object_is_accepted_like_the_static_gate():
    from abaqus_ai_agent.contracts.dynamic_energy import evaluate_dynamic_energy_balance

    verdict = evaluate_dynamic_energy_balance(
        {"variables": _REAL_IMPLICIT}, 0.01, solver_product="standard"
    )
    res = _accept(dynamic_energy=verdict, dynamic_energy_enabled=True)
    assert res.gates["dynamic_energy"] == "PASS"
    assert res.dynamic_energy["status"] == "PASS"
