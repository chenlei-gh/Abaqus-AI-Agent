"""Regression tests for CONTACT_OPENING: a real contact-closure failure.

The decisive real-machine observation behind this pattern: three genuine
gap-closure failures (M_U_T001/T02/T05) contain thousands of
"NUMERICAL SINGULARITY WHEN PROCESSING NODE ..." lines and **zero**
"POINTS CHANGED FROM" transitions. CONTACT_CHATTER therefore never fires, so the
remediator never proposed contact stabilization for a failure that contact
stabilization demonstrably repairs.

All fixture text is verbatim from those Abaqus/Standard 2025 runs.
"""

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.diagnostics.remediator import (
    RemediationCategory,
    SolverRemediator,
)
from abaqus_ai_agent.diagnostics.solver_patterns import diagnose_solver_artifacts


# Captured from M_U_T02.msg: no chatter transitions at all.
SINGULAR_CONTACT_MSG = """
 ***WARNING: SOLVER PROBLEM. NUMERICAL SINGULARITY WHEN PROCESSING NODE
             SLIDER-1.74 D.O.F. 1 RATIO = 10.E+12     .

 ***WARNING: SOLVER PROBLEM. NUMERICAL SINGULARITY WHEN PROCESSING NODE
             SLIDER-1.70 D.O.F. 2 RATIO = 100.E+12     .

***ERROR: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT
"""

FAILED_STA = """
   1    29   5U    0     4     4  0.0182     0.0182     3.716e-07

 THE ANALYSIS HAS NOT BEEN COMPLETED
"""

# Same messages, but the job is reported as having completed.
CONVERGED_STA = """
   1     9   1     0     1     1  1.00       1.00       0.1707

 THE ANALYSIS HAS COMPLETED SUCCESSFULLY
"""

# A deck with a contact pair, as written by CAE.
CONTACT_DECK = """
*Surface Interaction, name=CP
1.,
*Surface Behavior, pressure-overclosure=HARD
*Contact Pair, interaction=CP, type=SURFACE TO SURFACE
SS, MS
"""

# A deck without any contact definition.
NO_CONTACT_DECK = """
*Material, name=Steel
*Elastic
210000., 0.3
*Boundary
BaseAll, 1, 6
"""


def _ids(issues):
    return {i.diagnosis_id for i in issues}


def test_singular_contact_nodes_are_diagnosed_on_failure_with_a_contact_deck():
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG,
        sta_text=FAILED_STA,
        job_status="SOLVER_FAILED",
        inp_text=CONTACT_DECK,
    )
    assert "CONTACT_OPENING" in _ids(issues)


def test_singular_contact_nodes_are_not_diagnosed_when_the_job_converged():
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG,
        sta_text=CONVERGED_STA,
        job_status="COMPLETED",
        inp_text=CONTACT_DECK,
    )
    assert "CONTACT_OPENING" not in _ids(issues)


def test_singular_contact_nodes_are_not_diagnosed_without_a_contact_deck():
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG,
        sta_text=FAILED_STA,
        job_status="SOLVER_FAILED",
        inp_text=NO_CONTACT_DECK,
    )
    assert "CONTACT_OPENING" not in _ids(issues)


def test_singular_contact_nodes_are_not_diagnosed_when_the_deck_is_unknown():
    """Missing deck text must suppress, not assume contact exists."""
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG,
        sta_text=FAILED_STA,
        job_status="SOLVER_FAILED",
        inp_text=None,
    )
    assert "CONTACT_OPENING" not in _ids(issues)


def test_contact_opening_selects_contact_stabilization():
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG,
        sta_text=FAILED_STA,
        job_status="SOLVER_FAILED",
        inp_text=CONTACT_DECK,
    )
    remediations = SolverRemediator.generate_remediations(issues)
    contact = [
        r for r in remediations
        if r.category == RemediationCategory.CONTACT_STABILIZATION
    ]
    assert len(contact) == 1
    assert contact[0].diagnosis_id == "CONTACT_OPENING"
    assert contact[0].parameters["contact_damping"] is True
    assert contact[0].parameters["max_dissipation_ratio"] == 0.05


def test_contact_opening_and_chatter_do_not_double_propose_stabilization():
    """Both issues present must still yield exactly one contact action."""
    chatter_and_singular = SINGULAR_CONTACT_MSG + (
        "\n                  11 POINTS CHANGED FROM CLOSED TO OPEN\n"
    )
    issues = diagnose_solver_artifacts(
        msg_text=chatter_and_singular,
        sta_text=FAILED_STA,
        job_status="SOLVER_FAILED",
        inp_text=CONTACT_DECK,
    )
    assert {"CONTACT_OPENING", "CONTACT_CHATTER"} <= _ids(issues)
    remediations = SolverRemediator.generate_remediations(issues)
    contact = [
        r for r in remediations
        if r.category == RemediationCategory.CONTACT_STABILIZATION
    ]
    assert len(contact) == 1
    # Chatter is the more specific mechanism, so it names the action.
    assert contact[0].diagnosis_id == "CONTACT_CHATTER"


class _Intent(EngineeringIntent):
    pass


def test_contact_opening_remediation_reaches_contact_metadata():
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG,
        sta_text=FAILED_STA,
        job_status="SOLVER_FAILED",
        inp_text=CONTACT_DECK,
    )
    remediations = SolverRemediator.generate_remediations(issues)
    intent = EngineeringIntent(id="i", kind="contact", description="gap closure")
    updated = SolverRemediator.apply_remediations(intent, remediations)

    contact_stabilization = updated.metadata["contact_stabilization"]
    assert contact_stabilization["stabilize_choice"] == "AUTOMATIC"
    assert contact_stabilization["damp_factor"] == 1e-4
    # Contact damping must not leak into the step-level control bag.
    assert "contact_damping" not in updated.metadata.get("step_controls", {})
    # The policy threshold travels with the action.
    assert updated.metadata["stabilization_energy_threshold"] == 0.05
