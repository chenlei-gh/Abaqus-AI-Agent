"""Regression tests for the CONTACT_CHATTER wording and its failure gate.

Fixtures are verbatim lines captured from Abaqus/Standard 2025 jobs on this
machine, not invented text:

  Job_F1  friction slider, force controlled -> did not converge
  Job_F2  converged contact job -> status transitions still printed

The point of these tests is that chatter wording alone is not a diagnosis.
"""

import pytest

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.diagnostics.remediator import (
    RemediationCategory,
    SolverRemediator,
)
from abaqus_ai_agent.diagnostics.solver_patterns import diagnose_solver_artifacts


# Captured from Job_F1.msg (Abaqus 2025). The legacy phrases this pattern used to
# look for never appear in this release's output.
FAILED_MSG = """
                  44 POINTS CHANGED FROM STICKING TO SLIPPING
                  31 POINTS CHANGED FROM STICKING TO SLIPPING
                  11 POINTS CHANGED FROM CLOSED TO OPEN
                  14 POINTS CHANGED FROM SLIPPING TO STICKING
***ERROR: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT
"""

FAILED_STA = """
   1    31   5U    0    16    16  0.0184     0.0184     1.000e-10

 THE ANALYSIS HAS NOT BEEN COMPLETED
"""

# Captured from Job_F2.msg / Job_F2.sta: this job converged successfully yet
# printed the same kind of status transitions.
CONVERGED_MSG = """
                  11 POINTS CHANGED FROM CLOSED TO OPEN
                  34 POINTS CHANGED FROM STICKING TO SLIPPING
                  11 POINTS CHANGED FROM CLOSED TO OPEN
                  34 POINTS CHANGED FROM STICKING TO SLIPPING
"""

CONVERGED_STA = """
   1     9   1     0     1     1  1.00       1.00       0.1707

 THE ANALYSIS HAS COMPLETED SUCCESSFULLY
"""

# Converged runs also print these headers/counters; they must never be read as
# chatter evidence.
CONVERGED_BOILERPLATE_MSG = """
 EQUILIBRIUM WILL BE CHECKED FOR SEVERE DISCONTINUITY ITERATIONS
 0 ARE SEVERE DISCONTINUITY ITERATIONS AND 1 ARE EQUILIBRIUM ITERATIONS
 MAX. CONTACT FORCE ERROR 339.666E-12 AT NODE 41 OF CONTACT PAIR
"""


def _ids(issues):
    return {i.diagnosis_id for i in issues}


def test_real_chatter_wording_is_diagnosed_on_a_failed_job():
    issues = diagnose_solver_artifacts(
        msg_text=FAILED_MSG, sta_text=FAILED_STA, job_status="SOLVER_FAILED"
    )
    assert "CONTACT_CHATTER" in _ids(issues)

    chatter = next(i for i in issues if i.diagnosis_id == "CONTACT_CHATTER")
    assert any("POINTS CHANGED FROM" in line for line in chatter.supporting_evidence)
    assert chatter.metadata.get("failure_gated") is True


def test_chatter_is_not_diagnosed_when_the_job_completed():
    issues = diagnose_solver_artifacts(
        msg_text=CONVERGED_MSG, sta_text=CONVERGED_STA, job_status="RESULT_VALID"
    )
    assert "CONTACT_CHATTER" not in _ids(issues)


def test_successful_sta_vetoes_a_contradicting_failed_status():
    # A caller that mislabels a completed job must not unlock contact stabilization.
    issues = diagnose_solver_artifacts(
        msg_text=CONVERGED_MSG, sta_text=CONVERGED_STA, job_status="SOLVER_FAILED"
    )
    assert "CONTACT_CHATTER" not in _ids(issues)


def test_chatter_is_not_diagnosed_without_any_failure_evidence():
    # Bare status transitions, no sta, no terminal error, no status: unknown is not failed.
    issues = diagnose_solver_artifacts(msg_text=CONVERGED_MSG)
    assert "CONTACT_CHATTER" not in _ids(issues)


def test_converged_boilerplate_never_produces_chatter():
    issues = diagnose_solver_artifacts(
        msg_text=CONVERGED_BOILERPLATE_MSG,
        sta_text=CONVERGED_STA,
        job_status="RESULT_VALID",
    )
    assert "CONTACT_CHATTER" not in _ids(issues)


def test_terminal_error_alone_unlocks_the_gate():
    # No status and no sta, but the deck clearly stopped on a terminal error.
    issues = diagnose_solver_artifacts(
        msg_text=FAILED_MSG + "\n***ERROR: TIME INCREMENT REQUIRED IS LESS THAN THE MINIMUM SPECIFIED\n"
    )
    assert "CONTACT_CHATTER" in _ids(issues)


def test_slider_description_no_longer_blocks_remediation():
    """A sliding block is not a kinematic mechanism."""
    issues = diagnose_solver_artifacts(
        msg_text=FAILED_MSG, sta_text=FAILED_STA, job_status="SOLVER_FAILED"
    )
    intent = EngineeringIntent(
        id="intent_slider",
        kind="contact_analysis",
        description="Sliding block on base block, friction slider, force controlled.",
        analysis_type="general_contact",
    )
    actions = SolverRemediator().generate_remediations(list(issues), intent)
    assert any(
        a.category == RemediationCategory.CONTACT_STABILIZATION for a in actions
    )


@pytest.mark.parametrize(
    "word", ["mechanism", "kinematic", "linkage", "hinge", "fmbd"]
)
def test_mechanism_wording_still_blocks_blanket_encastre(word):
    """The guard targets the blanket-ENCASTRE remediation, so it needs a zero pivot."""
    issues = diagnose_solver_artifacts(
        msg_text=FAILED_MSG
        + "\n***ERROR: ZERO PIVOT ENCOUNTERED AT NODE 12 D.O.F. 1\n",
        sta_text=FAILED_STA,
        job_status="SOLVER_FAILED",
    )
    intent = EngineeringIntent(
        id="intent_mech",
        kind="contact_analysis",
        description="Four bar %s assembly under load." % word,
        analysis_type="general_contact",
    )
    actions = SolverRemediator().generate_remediations(list(issues), intent)
    assert any(a.category == RemediationCategory.UNRESOLVED for a in actions)
    assert not any(
        a.category == RemediationCategory.BOUNDARY_CONDITION for a in actions
    )
