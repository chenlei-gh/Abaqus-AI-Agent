"""P0-a: static stabilization-energy acceptance contract.

The contract must never manufacture a PASS from absent evidence, and must not
reuse the self-referential ALLSD/ALLIE ratio.
"""

import pytest

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.stabilization_energy import (
    detect_stabilization_in_deck,
    evaluate_static_stabilization_energy,
)
from abaqus_ai_agent.execution.odb import extract_energy_evidence


def _evidence(all_sd, all_se):
    return {
        "step": "Step-1",
        "region": "Assembly ASSEMBLY",
        "variables": {
            "ALLSD": {"status": "available", "data": all_sd},
            "ALLSE": {"status": "available", "data": all_se},
        },
    }


def test_ratio_at_or_below_threshold_passes():
    verdict = evaluate_static_stabilization_energy(
        _evidence([(0.0, 0.0), (0.5, 2.0), (1.0, 4.0)],
                  [(0.0, 100.0), (0.5, 200.0), (1.0, 200.0)]),
        threshold=0.05,
        threshold_source="test.policy",
    )
    assert verdict.status == "PASS"
    assert verdict.ratio == pytest.approx(0.02)
    assert verdict.threshold == 0.05
    assert verdict.threshold_source == "test.policy"
    assert verdict.informative_frame_count == 3


def test_ratio_above_threshold_fails_and_names_the_governing_frame():
    verdict = evaluate_static_stabilization_energy(
        _evidence([(0.0, 0.0), (0.5, 30.0), (1.0, 4.0)],
                  [(0.0, 100.0), (0.5, 100.0), (1.0, 200.0)]),
        threshold=0.05,
    )
    assert verdict.status == "FAIL"
    assert verdict.ratio == pytest.approx(0.3)
    assert verdict.details["governing_frame_index"] == 1
    assert verdict.details["governing_ALLSD"] == pytest.approx(30.0)


def test_worst_frame_governs_not_the_last_frame():
    # The final frame is clean (2%); an intermediate frame is at 40%.
    verdict = evaluate_static_stabilization_energy(
        _evidence([(0.0, 0.0), (0.5, 40.0), (1.0, 2.0)],
                  [(0.0, 100.0), (0.5, 100.0), (1.0, 100.0)]),
        threshold=0.05,
    )
    assert verdict.status == "FAIL"
    assert verdict.ratio == pytest.approx(0.4)


def test_allsd_is_not_divided_by_allie():
    """ALLIE must never be used as the denominator, even when supplied."""
    evidence = _evidence([(0.0, 10.0)], [(0.0, 1000.0)])
    evidence["variables"]["ALLIE"] = {"status": "available", "data": [(0.0, 100000.0)]}
    verdict = evaluate_static_stabilization_energy(evidence, threshold=0.05)
    assert verdict.ratio == pytest.approx(0.01)
    assert verdict.details["metric"] == "max_over_frames(ALLSD / ALLSE)"


def test_missing_allsd_blocks_instead_of_passing():
    evidence = {
        "variables": {
            "ALLSD": {"status": "unavailable", "reason": "history_output_missing"},
            "ALLSE": {"status": "available", "data": [(0.0, 100.0)]},
        }
    }
    verdict = evaluate_static_stabilization_energy(evidence, threshold=0.05)
    assert verdict.status == "BLOCKED"
    assert verdict.ratio is None
    assert verdict.reason == "missing_stabilization_dissipation_history"


def test_missing_allse_blocks_instead_of_passing():
    evidence = {
        "variables": {
            "ALLSD": {"status": "available", "data": [(0.0, 1.0)]},
            "ALLSE": {"status": "unavailable", "reason": "history_output_missing"},
        }
    }
    verdict = evaluate_static_stabilization_energy(evidence, threshold=0.05)
    assert verdict.status == "BLOCKED"
    assert verdict.ratio is None
    assert verdict.reason == "missing_strain_energy_history"


def test_missing_threshold_blocks_rather_than_defaulting_to_five_percent():
    verdict = evaluate_static_stabilization_energy(
        _evidence([(0.0, 1.0)], [(0.0, 100.0)]), threshold=None
    )
    assert verdict.status == "BLOCKED"
    assert verdict.threshold is None
    assert verdict.reason == "stabilization_threshold_not_configured"


def test_non_finite_values_block():
    verdict = evaluate_static_stabilization_energy(
        _evidence([(0.0, float("nan"))], [(0.0, 100.0)]), threshold=0.05
    )
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "non_finite_stabilization_energy"
    assert verdict.ratio is None


def test_negative_dissipation_blocks():
    verdict = evaluate_static_stabilization_energy(
        _evidence([(0.0, -1.0)], [(0.0, 100.0)]), threshold=0.05
    )
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "invalid_stabilization_energy_sign"


def test_near_zero_denominator_with_dissipation_blocks():
    verdict = evaluate_static_stabilization_energy(
        _evidence([(0.0, 5.0)], [(0.0, 0.0)]), threshold=0.05
    )
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "stabilization_energy_undefined_denominator"
    assert verdict.ratio is None


def test_empty_energy_frame_is_skipped_and_recorded():
    verdict = evaluate_static_stabilization_energy(
        _evidence(
            [(0.0, 0.0), (0.5, 0.0), (1.0, 4.0)],
            [(0.0, 0.0), (0.5, 0.0), (1.0, 200.0)],
        ),
        threshold=0.05,
    )
    assert verdict.status == "PASS"
    assert verdict.ratio == pytest.approx(0.02)
    assert verdict.skipped_frame_count == 2
    reasons = {frame["reason"] for frame in verdict.skipped_frames}
    assert reasons == {"zero_energy_frame"}


def test_unaligned_strain_history_is_skipped_and_recorded():
    verdict = evaluate_static_stabilization_energy(
        _evidence([(0.0, 1.0), (1.0, 2.0)], [(0.7, 100.0)]), threshold=0.05
    )
    assert verdict.status == "PASS"
    assert verdict.skipped_frame_count == 2
    reasons = {frame["reason"] for frame in verdict.skipped_frames}
    assert reasons == {"unaligned_strain_energy_history"}


def test_rigid_body_step_without_dissipation_passes_with_audit_trail():
    verdict = evaluate_static_stabilization_energy(
        _evidence([(0.0, 0.0), (1.0, 0.0)], [(0.0, 0.0), (1.0, 0.0)]), threshold=0.05
    )
    assert verdict.status == "PASS"
    assert verdict.informative_frame_count == 0
    assert verdict.skipped_frame_count == 2
    assert verdict.details["ratio_basis"] == "no_measurable_dissipation"


def test_stabilization_disabled_skips_the_gate():
    verdict = evaluate_static_stabilization_energy(
        None, threshold=None, stabilization_enabled=False
    )
    assert verdict.status == "SKIPPED"
    assert verdict.reason == "stabilization_not_enabled"


def test_deck_detection_ignores_plain_static_steps():
    marks = detect_stabilization_in_deck(
        "*STEP, NAME=Step-1\n*STATIC\n0.01, 1.0\n*END STEP\n"
    )
    assert marks == {"step_stabilization": False, "contact_stabilization": False}


def test_deck_detection_finds_step_and_contact_stabilization():
    step_marks = detect_stabilization_in_deck(
        "*STEP, NAME=Step-1\n*STATIC, STABILIZE\n0.01, 1.0\n*END STEP\n"
    )
    assert step_marks["step_stabilization"] is True

    contact_marks = detect_stabilization_in_deck(
        "*CONTACT CONTROLS, STABILIZE\n*STEP, NAME=Step-1\n*STATIC\n"
    )
    assert contact_marks["contact_stabilization"] is True


def test_deck_detection_ignores_comment_mentions():
    marks = detect_stabilization_in_deck("** this model does not *STATIC, STABILIZE\n")
    assert marks["step_stabilization"] is False


def test_extraction_requests_allse_for_the_static_contract():
    class FakeExecutor:
        def __init__(self):
            self.code = None

        def execute(self, code):
            self.code = code
            return {
                "step": "Step-1",
                "region": "Assembly ASSEMBLY",
                "variables": {"ALLSD": [(0.0, 0.0)], "ALLSE": [(0.0, 1.0)]},
            }

    executor = FakeExecutor()
    result = extract_energy_evidence(executor, "job.odb", "Step-1", "Assembly ASSEMBLY")
    assert "ALLSE" in result["variables"]
    assert "'ALLSE'" in executor.code
    assert "'ALLSD'" in executor.code


def _accept(**kwargs):
    base = dict(result_status="completed", values={}, criteria=[])
    base.update(kwargs)
    return evaluate_result_acceptance(**base)


def test_acceptance_gate_passes_when_evidence_is_valid():
    res = _accept(
        stabilization_energy=_evidence(
            [(0.0, 0.0), (1.0, 1.0)], [(0.0, 100.0), (1.0, 100.0)]
        ),
        stabilization_threshold=0.05,
        stabilization_enabled=True,
    )
    assert res.gates["stabilization_energy"] == "PASS"
    assert res.status == "PASS"
    assert res.stabilization_energy["ratio"] == pytest.approx(0.01)


def test_acceptance_gate_fails_when_ratio_exceeded():
    res = _accept(
        stabilization_energy=_evidence([(0.0, 50.0)], [(0.0, 100.0)]),
        stabilization_threshold=0.05,
        stabilization_enabled=True,
    )
    assert res.gates["stabilization_energy"] == "FAIL"
    assert res.status == "FAIL"
    assert any(f.startswith("stabilization_energy_exceeded:") for f in res.failures)


def test_acceptance_gate_blocks_when_evidence_missing():
    res = _accept(
        stabilization_energy={"variables": {"ALLSE": {"status": "available", "data": [(0.0, 1.0)]}}},
        stabilization_threshold=0.05,
        stabilization_enabled=True,
    )
    assert res.gates["stabilization_energy"] == "BLOCKED"
    assert res.status == "BLOCKED"
    assert any(f.startswith("stabilization_energy_unverifiable:") for f in res.failures)


def test_acceptance_gate_blocks_when_stabilization_enabled_but_no_evidence():
    res = _accept(stabilization_enabled=True, stabilization_threshold=0.05)
    assert res.gates["stabilization_energy"] == "BLOCKED"
    assert res.status == "BLOCKED"
    assert res.deliverable is False


def test_acceptance_gate_skipped_when_stabilization_disabled():
    res = _accept()
    assert res.gates["stabilization_energy"] == "SKIPPED"
    assert res.status == "PASS"
    assert res.deliverable is True


def test_blocked_stabilization_is_not_promoted_to_physical_failure():
    """Missing evidence must stay BLOCKED, never turn into a fabricated FAIL."""
    res = _accept(
        stabilization_energy={"variables": {}},
        stabilization_threshold=0.05,
        stabilization_enabled=True,
    )
    assert res.status == "BLOCKED"
    assert res.acceptance_status == "BLOCKED"


def test_stabilization_gate_respects_canonical_order():
    from abaqus_ai_agent.acceptance import CANONICAL_GATE_ORDER

    res = _accept(
        stabilization_energy=_evidence([(0.0, 1.0)], [(0.0, 100.0)]),
        stabilization_threshold=0.05,
        stabilization_enabled=True,
    )
    keys = list(res.gates.keys())
    order = {name: i for i, name in enumerate(CANONICAL_GATE_ORDER)}
    indices = [order[k] for k in keys if k in order]
    assert indices == sorted(indices)
    assert "stabilization_energy" in keys


def test_stabilization_gate_runs_even_when_other_gates_pass():
    """A clean run must still be blocked by insufficient stabilization evidence."""
    res = _accept(
        values={"stress": 120.0},
        criteria=[{"name": "stress", "value_key": "stress", "operator": "<",
                   "limit": 200.0}],
        stabilization_enabled=True,
        stabilization_threshold=0.05,
    )
    assert res.criteria and all(c.passed for c in res.criteria)
    assert res.gates["stabilization_energy"] == "BLOCKED"
    assert res.status == "BLOCKED"
    assert res.deliverable is False
