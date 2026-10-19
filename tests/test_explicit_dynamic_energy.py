"""Explicit-dynamics evidence path for the dynamic energy balance contract.

Two separate risks are pinned here:

1. The post-processing profile for explicit strategies must actually plan an
   ``ALLWK`` history request. Without it the contract can only ever answer
   ``BLOCKED`` for a deck the planner generated itself, and no amount of solver
   output can rescue that.
2. The contract must behave on *explicit* solver output, not just implicit. The
   series below are verbatim from a real Abaqus/Explicit 2025 job
   (``ExplicitProbeJob``, C3D8R cantilever, 201 history frames, recorded in
   ``machine_validation/explicit_dynamic_energy_balance.json``).
"""

import pytest

from abaqus_ai_agent.contracts.dynamic_energy import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_INCOMPLETE,
    STATUS_PASS,
    evaluate_dynamic_energy_balance,
)
from abaqus_ai_agent.contracts.postprocess import profile_for_solver_selection
from abaqus_ai_agent.planning.output import plan_outputs


class _Selection:
    def __init__(self, strategy):
        self.strategy = strategy


# --- Real Abaqus/Explicit 2025 output -------------------------------------
# Identity ETOTAL = ALLIE + ALLKE - ALLWK holds to 2.5e-4 relative in this run.
_REAL_EXPLICIT = {
    "ALLIE": [
        (0.0, 0.0),
        (1.034181423165137e-05, 0.0017913277260959148),
        (0.0010000752517953515, 22155.41015625),
        (0.0020000000949949026, 22497.408203125),
    ],
    "ALLKE": [
        (0.0, 0.0),
        (1.034181423165137e-05, 0.005904148332774639),
        (0.0010000752517953515, 12.875739097595215),
        (0.0020000000949949026, 22.728179931640625),
    ],
    "ALLWK": [
        (0.0, 0.0),
        (1.034181423165137e-05, 0.007683544419705868),
        (0.0010000752517953515, 22168.423828125),
        (0.0020000000949949026, 22520.279296875),
    ],
    "ETOTAL": [
        (0.0, 0.0),
        (1.034181423165137e-05, 1.3860640137863811e-05),
        (0.0010000752517953515, 0.1794615089893341),
        (0.0020000000949949026, 0.20017565786838531),
    ],
}

_REFERENCE = 22520.279296875


def _evaluate(threshold=0.01, product="explicit", variables=None):
    return evaluate_dynamic_energy_balance(
        {"history": {"status": "available", "variables": variables or _REAL_EXPLICIT}},
        threshold,
        solver_product=product,
    )


@pytest.mark.parametrize("strategy", ["DYNAMIC_EXPLICIT", "QUASI_STATIC_EXPLICIT"])
def test_explicit_profiles_request_every_variable_the_contract_requires(strategy):
    """A planner-generated explicit deck must not be born unevaluable."""
    profile = profile_for_solver_selection(_Selection(strategy))
    assert set(("ALLIE", "ALLKE", "ALLWK", "ETOTAL")) <= set(profile.history_variables)

    plan = plan_outputs((), postprocess_profile=profile)
    assert set(("ALLIE", "ALLKE", "ALLWK", "ETOTAL")) <= set(plan.history_variables)


def test_planned_explicit_history_is_evaluable_by_the_contract():
    """The planned variable set is a superset of what the contract consumes."""
    profile = profile_for_solver_selection(_Selection("DYNAMIC_EXPLICIT"))
    planned = set(plan_outputs((), postprocess_profile=profile).history_variables)
    consumed = set(("ALLIE", "ALLKE", "ALLWK", "ETOTAL"))
    assert consumed <= planned


def test_real_explicit_history_passes_a_declared_one_percent_policy():
    verdict = _evaluate()
    assert verdict.status == STATUS_PASS
    assert verdict.solver_product == "explicit"
    assert verdict.reference_energy == pytest.approx(_REFERENCE)
    assert verdict.ratio == pytest.approx(0.20017565786838531 / _REFERENCE)
    assert verdict.informative_frame_count == 3


def test_real_explicit_history_fails_a_stricter_declared_policy():
    verdict = _evaluate(threshold=1.0e-6)
    assert verdict.status == STATUS_FAIL
    # Same measurement, different policy: the ratio must not move.
    assert verdict.ratio == pytest.approx(0.20017565786838531 / _REFERENCE)


def test_explicit_identity_holds_so_the_evidence_is_genuinely_consistent():
    verdict = _evaluate()
    assert verdict.status == STATUS_PASS
    assert verdict.max_identity_deviation < 1.0e-3 * _REFERENCE


@pytest.mark.parametrize("missing", ["ALLIE", "ALLKE", "ALLWK"])
def test_explicit_evidence_without_a_component_blocks(missing):
    variables = {k: v for k, v in _REAL_EXPLICIT.items() if k != missing}
    verdict = _evaluate(variables=variables)
    assert verdict.status == STATUS_BLOCKED
    assert missing in verdict.reason
    assert verdict.ratio is None


def test_explicit_evidence_without_etotal_blocks_instead_of_synthesising_it():
    """ALLIE + ALLKE - ALLWK must never be substituted for a missing ETOTAL."""
    variables = {k: v for k, v in _REAL_EXPLICIT.items() if k != "ETOTAL"}
    verdict = _evaluate(variables=variables)
    assert verdict.status == STATUS_BLOCKED
    assert verdict.reason == "missing_total_energy_history"
    assert verdict.ratio is None


def test_single_explicit_frame_is_incomplete_not_a_pass():
    variables = {
        name: [series[-1]] for name, series in _REAL_EXPLICIT.items()
    }
    verdict = _evaluate(variables=variables)
    assert verdict.status == STATUS_INCOMPLETE
    assert verdict.ratio is None


def test_explicit_policy_still_requires_a_declared_threshold():
    verdict = evaluate_dynamic_energy_balance(
        {"history": {"status": "available", "variables": _REAL_EXPLICIT}},
        None,
        solver_product="explicit",
    )
    assert verdict.status == STATUS_BLOCKED
    assert verdict.reason == "dynamic_energy_threshold_not_configured"


def test_explicit_policy_still_requires_a_declared_solver_product():
    verdict = evaluate_dynamic_energy_balance(
        {"history": {"status": "available", "variables": _REAL_EXPLICIT}},
        0.01,
        solver_product=None,
    )
    assert verdict.status == STATUS_BLOCKED
    assert verdict.reason == "dynamic_energy_solver_product_not_declared"


def test_explicit_and_implicit_policies_are_independently_applied():
    """The same explicit evidence can satisfy one product policy and fail another."""
    assert _evaluate(threshold=0.01, product="explicit").status == STATUS_PASS
    assert _evaluate(threshold=1.0e-6, product="explicit").status == STATUS_FAIL
