"""Dynamic energy balance acceptance contract.

The contract must judge energy conservation over the whole transient history,
never from one frame, never from absent evidence, and never with a threshold the
module invented. It is an independent sibling of the static stabilization
contract and must not share its metric, denominator or defaults.
"""

import pytest

from abaqus_ai_agent.contracts.dynamic_energy import (
    DynamicEnergyVerdict,
    evaluate_dynamic_energy_balance,
)


# Real Abaqus/Standard 2025 implicit dynamic history (single precision output),
# recorded verbatim in machine_validation/dynamic_golden_e2e.json. The identity
# ETOTAL = ALLIE + ALLKE - ALLWK holds to ~2.5e-5 here, so this is genuine
# solver output rather than a synthetic series.
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

# Threshold used only by these tests as a declared policy for one configuration.
_THRESHOLD = 0.01


def _evidence(variables):
    return {"step": "Step-1", "region": "Assembly ASSEMBLY", "variables": variables}


def _series(name, data):
    return {name: {"status": "available", "data": data}}


def _evaluate(variables, threshold=_THRESHOLD, product="standard", **kwargs):
    return evaluate_dynamic_energy_balance(
        _evidence(variables),
        threshold,
        solver_product=product,
        **kwargs,
    )


def test_real_implicit_history_passes_against_declared_policy():
    verdict = _evaluate(_REAL_IMPLICIT)
    assert verdict.status == "PASS"
    # E_ref is the largest component magnitude across all frames: 1037.3302.
    assert verdict.reference_energy == pytest.approx(1037.33020019531)
    assert verdict.ratio == pytest.approx(2.39511466026306 / 1037.33020019531)
    # The identity is verified from the histories, not trusted from ETOTAL alone.
    assert verdict.max_identity_deviation is not None
    assert verdict.max_identity_deviation < 1e-4
    # t=0 carries zero energy, so three frames hold a measurable residual.
    assert verdict.frame_count == 4
    assert verdict.informative_frame_count == 3
    assert verdict.details["empty_frame_indices"] == (0,)


def test_verdict_echoes_the_policy_that_was_applied():
    verdict = _evaluate(_REAL_IMPLICIT, threshold_source="intent.metadata.dynamic_energy_threshold")
    assert verdict.threshold == _THRESHOLD
    assert verdict.threshold_source == "intent.metadata.dynamic_energy_threshold"
    assert verdict.solver_product == "standard"
    assert verdict.details["metric"] == "max_over_frames(|ETOTAL| / E_ref)"
    assert verdict.details["contract"] == "dynamic_energy_balance"


def test_ratio_above_threshold_fails():
    verdict = _evaluate(_REAL_IMPLICIT, threshold=0.001)
    assert verdict.status == "FAIL"
    assert verdict.reason == "dynamic_energy_drift_exceeded"
    assert verdict.ratio > 0.001


def test_ratio_at_threshold_passes():
    verdict = _evaluate(_REAL_IMPLICIT, threshold=2.39511466026306 / 1037.33020019531)
    assert verdict.status == "PASS"


def test_identity_tolerance_is_relative_to_each_frame_not_to_an_absolute_floor():
    """A 1e-3 relative tolerance must not become a 1e3 absolute allowance.

    The previous implementation compared against ``1e-3 * max(reference, 1.0)``,
    which in a joule-scale model permits a 1 J imbalance inside a 1e-3 J event.
    """
    variables = {
        "ALLIE": [(0.0, 0.0), (0.01, 0.002)],
        "ALLKE": [(0.0, 0.0), (0.01, 0.0)],
        "ALLWK": [(0.0, 0.0), (0.01, 0.002)],
        # 0.5 J residual against a 0.002 J event: off by 250x.
        "ETOTAL": [(0.0, 0.0), (0.01, 0.5)],
    }
    verdict = _evaluate(variables, threshold=1.0)
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "total_energy_identity_violated"


def test_governing_frame_is_reported_not_only_the_last_one():
    verdict = _evaluate(_REAL_IMPLICIT, threshold=1.0)
    assert verdict.details["governing_frame_index"] == 3
    # A quiet final frame must not be able to hide an earlier residual. The
    # history stays identity-consistent so the drift, not a broken history set,
    # is what the contract judges.
    variables = {
        "ALLIE": [(0.0, 0.0), (0.005, 100.0), (0.01, 100.0)],
        "ALLKE": [(0.0, 0.0), (0.005, 0.0), (0.01, 0.0)],
        "ALLWK": [(0.0, 0.0), (0.005, 150.0), (0.01, 103.0)],
        "ETOTAL": [(0.0, 0.0), (0.005, -50.0), (0.01, -3.0)],
    }
    verdict = _evaluate(variables, threshold=0.01)
    assert verdict.status == "FAIL"
    assert verdict.details["governing_frame_index"] == 1
    assert verdict.ratio == pytest.approx(50.0 / 150.0)


def test_missing_etotal_blocks():
    variables = {k: v for k, v in _REAL_IMPLICIT.items() if k != "ETOTAL"}
    verdict = _evaluate(variables)
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "missing_total_energy_history"
    assert verdict.ratio is None


def test_etotal_reported_unavailable_blocks():
    variables = dict(_REAL_IMPLICIT)
    variables["ETOTAL"] = {"status": "unavailable", "reason": "history_output_missing"}
    verdict = _evaluate(variables)
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "missing_total_energy_history"


@pytest.mark.parametrize("missing", ["ALLIE", "ALLKE", "ALLWK"])
def test_missing_identity_component_blocks(missing):
    variables = {k: v for k, v in _REAL_IMPLICIT.items() if k != missing}
    verdict = _evaluate(variables)
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "missing_energy_component_history:%s" % missing
    assert verdict.details["missing_component"] == missing
    assert verdict.ratio is None


def test_identity_violation_blocks_instead_of_trusting_etotal():
    """A 1000x unit mismatch in one component cannot be silently accepted."""
    variables = dict(_REAL_IMPLICIT)
    variables["ALLIE"] = [(t, v * 1000.0) for t, v in _REAL_IMPLICIT["ALLIE"]]
    verdict = _evaluate(variables)
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "total_energy_identity_violated"
    assert verdict.ratio is None


def test_non_finite_etotal_blocks():
    variables = dict(_REAL_IMPLICIT)
    variables["ETOTAL"] = [(0.0, 0.0), (0.007882812, float("nan")),
                           (0.017882813, -2.28848), (0.020000000, -2.39511)]
    verdict = _evaluate(variables)
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "non_finite_total_energy"
    assert verdict.ratio is None


def test_non_finite_component_blocks():
    variables = dict(_REAL_IMPLICIT)
    variables["ALLKE"] = [(0.0, 0.0), (0.007882812, float("inf")),
                          (0.017882813, 0.006825), (0.020000000, 0.148331)]
    verdict = _evaluate(variables)
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "non_finite_total_energy"


def test_unaligned_history_blocks_even_if_most_frames_agree():
    variables = dict(_REAL_IMPLICIT)
    variables["ALLKE"] = _REAL_IMPLICIT["ALLKE"][:-1]
    verdict = _evaluate(variables)
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "unaligned_total_energy_history"
    assert verdict.ratio is None


def test_single_frame_is_incomplete_not_pass():
    variables = {name: [(0.01, data[1][1])] for name, data in _REAL_IMPLICIT.items()}
    verdict = _evaluate(variables)
    assert verdict.status == "INCOMPLETE"
    assert verdict.reason == "insufficient_informative_frames"
    assert verdict.ratio is None


def test_zero_energy_history_is_incomplete_rather_than_conservation():
    """An all-zero history measures nothing, so it cannot evidence balance."""
    variables = {name: [(0.0, 0.0), (0.01, 0.0)] for name in _REAL_IMPLICIT}
    verdict = _evaluate(variables)
    assert verdict.status == "INCOMPLETE"
    assert verdict.reason == "no_measurable_energy_in_history"
    assert verdict.ratio is None


def test_single_measured_frame_is_incomplete_even_next_to_empty_frames():
    """t=0 frames are empty, so they cannot stand in for a drift trend."""
    variables = {
        name: [(0.0, 0.0), data[1]] for name, data in _REAL_IMPLICIT.items()
    }
    verdict = _evaluate(variables)
    assert verdict.status == "INCOMPLETE"
    assert verdict.reason == "insufficient_informative_frames"
    assert verdict.informative_frame_count == 1


def test_negligible_reference_with_nonzero_residual_blocks():
    variables = {
        "ALLIE": [(0.0, 0.0), (0.01, 0.0)],
        "ALLKE": [(0.0, 0.0), (0.01, 0.0)],
        "ALLWK": [(0.0, 0.0), (0.01, 0.0)],
        "ETOTAL": [(0.0, 0.0), (0.01, 1.0)],
    }
    verdict = _evaluate(variables)
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "dynamic_energy_zero_reference"
    assert verdict.ratio is None


def test_non_dynamic_analysis_is_skipped():
    verdict = _evaluate(_REAL_IMPLICIT, analysis_is_dynamic=False)
    assert verdict.status == "SKIPPED"
    assert verdict.reason == "analysis_not_dynamic"
    assert verdict.ratio is None


@pytest.mark.parametrize("product", [None, "", "implicit", "STANDARD-ish"])
def test_undeclared_solver_product_blocks(product):
    verdict = _evaluate(_REAL_IMPLICIT, product=product)
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "dynamic_energy_solver_product_not_declared"


def test_solver_product_is_case_insensitive_and_echoed():
    verdict = _evaluate(_REAL_IMPLICIT, product="EXPLICIT")
    assert verdict.status == "PASS"
    assert verdict.solver_product == "explicit"


@pytest.mark.parametrize("threshold", [None, -0.01, float("nan"), "not-a-number"])
def test_missing_or_invalid_threshold_blocks(threshold):
    verdict = _evaluate(_REAL_IMPLICIT, threshold=threshold)
    assert verdict.status == "BLOCKED"
    assert verdict.reason == "dynamic_energy_threshold_not_configured"
    assert verdict.ratio is None


def test_implicit_and_explicit_thresholds_are_independently_honoured():
    """The same histories may pass one solver policy and fail the other."""
    implicit = _evaluate(_REAL_IMPLICIT, threshold=0.01, product="standard")
    explicit = _evaluate(_REAL_IMPLICIT, threshold=0.001, product="explicit")
    assert implicit.status == "PASS"
    assert explicit.status == "FAIL"


def test_metric_is_not_the_static_stabilization_ratio():
    variables = dict(_REAL_IMPLICIT)
    variables["ALLSD"] = {"status": "available", "data": [(0.0, 0.0), (0.02, 5.0)]}
    variables["ALLSE"] = {"status": "available", "data": [(0.0, 0.0), (0.02, 100.0)]}
    verdict = _evaluate(variables)
    assert verdict.ratio == pytest.approx(2.39511466026306 / 1037.33020019531)
    assert verdict.details["metric"] == "max_over_frames(|ETOTAL| / E_ref)"


def test_verdict_is_a_stable_serialisable_record():
    verdict = _evaluate(_REAL_IMPLICIT)
    payload = verdict.to_dict()
    assert isinstance(verdict, DynamicEnergyVerdict)
    assert payload["status"] == "PASS"
    assert payload["ratio"] == verdict.ratio
    assert payload["threshold"] == _THRESHOLD
    assert payload["reference_energy"] == verdict.reference_energy
    assert payload["details"]["contract"] == "dynamic_energy_balance"


def test_no_ratio_is_ever_manufactured_when_evidence_is_absent():
    for payload in (None, {}, {"variables": {}}, "not-a-mapping"):
        verdict = evaluate_dynamic_energy_balance(
            payload, _THRESHOLD, solver_product="standard"
        )
        assert verdict.status == "BLOCKED"
        assert verdict.ratio is None
