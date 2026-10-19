"""P0-a: static stabilization-energy acceptance contract.

The contract must never manufacture a PASS from absent evidence, must not reuse
the self-referential ALLSD/ALLIE ratio, and must bind the gate to the step that
actually requested stabilization.
"""

import pytest

from abaqus_ai_agent.acceptance import evaluate_result_acceptance
from abaqus_ai_agent.contracts.stabilization_energy import (
    detect_stabilization_in_deck,
    evaluate_static_stabilization_energy,
    resolve_stabilized_step,
)
from abaqus_ai_agent.execution.analysis_run import AnalysisRunner
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


def test_unaligned_strain_history_blocks_instead_of_passing():
    """Histories that disagree on the timeline cannot decide the ratio."""
    verdict = evaluate_static_stabilization_energy(
        _evidence([(0.0, 1.0), (1.0, 2.0)], [(0.7, 100.0)]), threshold=0.05
    )
    assert verdict.status == "BLOCKED"
    assert verdict.ratio is None
    assert verdict.reason == "unaligned_strain_energy_history"
    assert verdict.skipped_frame_count == 2
    reasons = {frame["reason"] for frame in verdict.skipped_frames}
    assert reasons == {"unaligned_strain_energy_history"}


def test_partially_aligned_history_still_blocks():
    """One aligned frame must not outvote a misaligned one.

    Frames 0-1 are usable and would pass at 2%. Frame 2 has no ALLSE sample at
    its time, so the paired evidence is incomplete and the gate must block
    rather than report a clean ratio computed from a partial timeline.
    """
    verdict = evaluate_static_stabilization_energy(
        _evidence(
            [(0.0, 0.0), (0.5, 2.0), (1.0, 4.0)],
            [(0.0, 100.0), (0.5, 100.0)],
        ),
        threshold=0.05,
    )
    assert verdict.status == "BLOCKED"
    assert verdict.ratio is None
    assert verdict.reason == "unaligned_strain_energy_history"
    assert verdict.informative_frame_count == 2
    assert verdict.details["blocked_frame_index"] == 2
    assert "governing_frame_index" not in verdict.details


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
    assert marks["step_stabilization"] is False
    assert marks["contact_stabilization"] is False
    assert marks["steps"] == [{"name": "Step-1", "step_stabilization": False,
                               "contact_stabilization": False}]


def test_deck_detection_finds_step_and_contact_stabilization():
    step_marks = detect_stabilization_in_deck(
        "*STEP, NAME=Step-1\n*STATIC, STABILIZE\n0.01, 1.0\n*END STEP\n"
    )
    assert step_marks["step_stabilization"] is True
    assert step_marks["steps"][0]["step_stabilization"] is True

    contact_marks = detect_stabilization_in_deck(
        "*CONTACT CONTROLS, STABILIZE\n*STEP, NAME=Step-1\n*STATIC\n"
    )
    assert contact_marks["contact_stabilization"] is True


def test_deck_detection_ignores_comment_mentions():
    marks = detect_stabilization_in_deck("** this model does not *STATIC, STABILIZE\n")
    assert marks["step_stabilization"] is False


def test_deck_detection_ignores_data_lines_and_comments_inside_steps():
    marks = detect_stabilization_in_deck(
        "*STEP, NAME=Step-1\n** *STATIC, STABILIZE\n*STATIC\n0.01, 1.0\n*END STEP\n"
    )
    assert marks["step_stabilization"] is False


def test_deck_detection_attributes_stabilization_per_step():
    deck = (
        "*STEP, NAME=Step-1\n*STATIC\n0.01, 1.0\n*END STEP\n"
        "*STEP, NAME=Step-2\n*STATIC, STABILIZE=1e-4\n0.01, 1.0\n*END STEP\n"
    )
    marks = detect_stabilization_in_deck(deck)
    assert [entry["name"] for entry in marks["steps"]] == ["Step-1", "Step-2"]
    assert [entry["step_stabilization"] for entry in marks["steps"]] == [False, True]


def test_deck_detection_flags_keywords_outside_a_step_block():
    marks = detect_stabilization_in_deck("*CONTACT CONTROLS, STABILIZE\n")
    assert marks["unattributed_contact_stabilization"] is True
    assert marks["contact_stabilization"] is True


def test_resolution_picks_the_only_stabilized_step_not_the_last_one():
    deck = (
        "*STEP, NAME=Step-1\n*STATIC, STABILIZE\n*END STEP\n"
        "*STEP, NAME=Step-2\n*STATIC\n*END STEP\n"
    )
    selection = resolve_stabilized_step(
        detect_stabilization_in_deck(deck), ["Step-1", "Step-2"]
    )
    assert selection.resolved is True
    assert selection.step_name == "Step-1"


def test_resolution_reports_not_enabled_without_stabilization():
    deck = "*STEP, NAME=Step-1\n*STATIC\n*END STEP\n"
    selection = resolve_stabilized_step(detect_stabilization_in_deck(deck), ["Step-1"])
    assert selection.resolved is False
    assert selection.status == "NOT_ENABLED"
    assert selection.step_name is None


def test_resolution_blocks_when_several_steps_are_stabilized():
    deck = (
        "*STEP, NAME=Step-1\n*STATIC, STABILIZE\n*END STEP\n"
        "*STEP, NAME=Step-2\n*CONTACT CONTROLS, STABILIZE\n*END STEP\n"
    )
    selection = resolve_stabilized_step(
        detect_stabilization_in_deck(deck), ["Step-1", "Step-2"]
    )
    assert selection.resolved is False
    assert selection.status == "UNRESOLVED"
    assert selection.reason == "stabilization_step_ambiguous"
    assert selection.candidates == ("Step-1", "Step-2")


def test_resolution_blocks_when_stabilized_step_is_missing_from_odb():
    deck = "*STEP, NAME=Step-2\n*STATIC, STABILIZE\n*END STEP\n"
    selection = resolve_stabilized_step(detect_stabilization_in_deck(deck), ["Step-1"])
    assert selection.resolved is False
    assert selection.reason == "stabilized_step_missing_in_odb"


def test_resolution_blocks_when_keyword_is_outside_any_step():
    selection = resolve_stabilized_step(
        detect_stabilization_in_deck("*CONTACT CONTROLS, STABILIZE\n"), ["Step-1"]
    )
    assert selection.resolved is False
    assert selection.reason == "stabilization_step_unattributed"


def test_resolution_blocks_when_step_block_has_no_name():
    deck = "*STEP\n*STATIC, STABILIZE\n*END STEP\n"
    selection = resolve_stabilized_step(detect_stabilization_in_deck(deck), ["Step-1"])
    assert selection.resolved is False
    assert selection.reason == "stabilization_step_unattributed"


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


# --- runner-level step binding -------------------------------------------


def _runner_gate(monkeypatch, deck, odb_steps, extracted_steps, energy=None,
                 threshold=0.05):
    """Exercise AnalysisRunner._evaluate_stabilization_gate in isolation.

    ``extracted_steps`` records which ODB step the energy extractor was asked
    for, so a wrong-step read is visible rather than inferred from a verdict.
    The threshold is supplied explicitly because the contract never invents one.
    """

    class _Intent:
        metadata = (
            {"stabilization_energy_threshold": threshold}
            if threshold is not None else {}
        )

    class _Executor:
        def execute(self, code, timeout=120):
            return code

    def _fake_extract(_executor, _path, step, _region):
        extracted_steps.append(step)
        if energy is not None:
            return energy
        return {
            "step": step,
            "region": "Assembly ASSEMBLY",
            "variables": {
                "ALLSD": {"status": "available", "data": [(0.0, 0.0), (1.0, 1.0)]},
                "ALLSE": {"status": "available", "data": [(0.0, 100.0), (1.0, 100.0)]},
            },
        }

    import abaqus_ai_agent.execution.odb as odb_module

    monkeypatch.setattr(odb_module, "extract_energy_evidence", _fake_extract)
    runner = AnalysisRunner(_Executor())
    return runner._evaluate_stabilization_gate(
        deck,
        {"steps": list(odb_steps)},
        {"history_regions": ["Assembly ASSEMBLY"]},
        "job.odb",
        _Intent(),
    )


_STABILIZED_TWO_STEP_DECK = (
    "*STEP, NAME=Step-1\n*STATIC, STABILIZE\n0.01, 1.0\n*END STEP\n"
    "*STEP, NAME=Step-2\n*STATIC\n0.01, 1.0\n*END STEP\n"
)


def test_runner_reads_the_stabilized_step_not_the_last_step(monkeypatch):
    extracted = []
    enabled, verdict = _runner_gate(
        monkeypatch, _STABILIZED_TWO_STEP_DECK,
        ["Initial", "Step-1", "Step-2"], extracted,
    )
    assert enabled is True
    assert extracted == ["Step-1"]
    assert verdict.status == "PASS"


def test_runner_blocks_when_stabilized_step_is_absent_from_the_odb(monkeypatch):
    extracted = []
    enabled, verdict = _runner_gate(
        monkeypatch, _STABILIZED_TWO_STEP_DECK, ["Initial", "Step-2"], extracted
    )
    assert enabled is True
    assert extracted == []
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "stabilized_step_missing_in_odb"
    assert verdict.ratio is None


def test_runner_blocks_when_two_steps_enable_stabilization(monkeypatch):
    deck = (
        "*STEP, NAME=Step-1\n*STATIC, STABILIZE\n*END STEP\n"
        "*STEP, NAME=Step-2\n*CONTACT CONTROLS, STABILIZE\n*END STEP\n"
    )
    extracted = []
    enabled, verdict = _runner_gate(
        monkeypatch, deck, ["Initial", "Step-1", "Step-2"], extracted
    )
    assert enabled is True
    assert extracted == []
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "stabilization_step_ambiguous"


def test_runner_leaves_plain_deck_skipped_without_extraction(monkeypatch):
    extracted = []
    enabled, verdict = _runner_gate(
        monkeypatch,
        "*STEP, NAME=Step-1\n*STATIC\n*END STEP\n",
        ["Initial", "Step-1"],
        extracted,
    )
    assert enabled is False
    assert verdict is None
    assert extracted == []


def test_runner_blocks_on_extraction_failure_instead_of_optional_gate(monkeypatch):
    class _Executor:
        def execute(self, code, timeout=120):
            return code

    def _boom(*_args, **_kwargs):
        raise RuntimeError("odb step missing")

    import abaqus_ai_agent.execution.odb as odb_module

    monkeypatch.setattr(odb_module, "extract_energy_evidence", _boom)
    runner = AnalysisRunner(_Executor())

    class _Intent:
        metadata = {"stabilization_energy_threshold": 0.05}

    enabled, verdict = runner._evaluate_stabilization_gate(
        _STABILIZED_TWO_STEP_DECK,
        {"steps": ["Initial", "Step-1", "Step-2"]},
        {"history_regions": ["Assembly ASSEMBLY"]},
        "job.odb",
        _Intent(),
    )
    assert enabled is True
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "stabilization_energy_extraction_failed"


def test_runner_blocks_when_energy_histories_are_misaligned(monkeypatch):
    energy = {
        "step": "Step-1",
        "region": "Assembly ASSEMBLY",
        "variables": {
            "ALLSD": {"status": "available", "data": [(0.0, 0.0), (1.0, 2.0)]},
            "ALLSE": {"status": "available", "data": [(0.0, 100.0)]},
        },
    }
    extracted = []
    _, verdict = _runner_gate(
        monkeypatch, _STABILIZED_TWO_STEP_DECK,
        ["Initial", "Step-1", "Step-2"], extracted, energy=energy,
    )
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "unaligned_strain_energy_history"
