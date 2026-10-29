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

# Verbatim from a real Abaqus/Standard 2025 contact run (.msg header).
MSG_WITH_CONTACT_BANNER = """
     SOFT CONTACT CONSTRAINT COMPATIBILITY TOLERANCE FOR P>P0          5.000E-03

 CONTACT CONTROLS APPLIED TO ALL CONTACT PAIRS:
     GLOBAL STABILIZATION CONTROL IS NOT USED
     RELATIVE PENETRATION TOLERANCE FOR AUGMENTED LAGRANGE CONTACT:
          FINITE-SLIDING SURFACE-TO-SURFACE                            5.000E-02
"""

# Verbatim from a measured no-contact model that genuinely failed with 90
# numerical singularities. It still prints the generic contact tolerances, so
# those lines must never be treated as contact evidence.
MSG_WITHOUT_CONTACT = """
     SOFT CONTACT CONSTRAINT COMPATIBILITY TOLERANCE FOR P>P0          5.000E-03
     SOFT CONTACT CONSTRAINT COMPATIBILITY TOLERANCE FOR P=0.0         0.100
     CONTACT FORCE ERROR TOLERANCE FOR CONVERT SDI=YES                 1.00
     MAXIMUM CONTACT AUGMENTATIONS FOR *SURFACE BEHAVIOR,AUGMENTED LAGRANGE   50

 ***WARNING: SOLVER PROBLEM. NUMERICAL SINGULARITY WHEN PROCESSING NODE
             N7 D.O.F. 1 RATIO = 10.E+12     .
"""

# The .dat "OPTIONS BEING PROCESSED" echo of a contact model.
DAT_WITH_CONTACT_PAIR = """
  *contactpair, interaction=CP, type=SURFACETOSURFACE
  *surface, type=ELEMENT, name=ASSEMBLY_MS
  *surface, type=ELEMENT, name=ASSEMBLY_SS
"""

# A stabilized deck's .dat echo: the remediation writes *contactcontrols itself,
# so that card must never count as evidence that contact already existed.
DAT_WITH_CONTACT_CONTROLS_ONLY = """
  *contactcontrols, main=ASSEMBLY_MS, reset, secondary=ASSEMBLY_SS
  *contactcontrols, main=ASSEMBLY_MS, secondary=ASSEMBLY_SS, stabiliz
"""

# A no-contact .dat window, as measured.
DAT_WITHOUT_CONTACT = """
          NUMBER OF ELEMENTS IS                                     1
          NUMBER OF ELEMENTS DEFINED BY THE USER AND *TIE           1
          NUMBER OF NODES IS                                        8
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
    """Missing deck text must suppress when no other artifact proves contact."""
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG,
        sta_text=FAILED_STA,
        job_status="SOLVER_FAILED",
        inp_text=None,
    )
    assert "CONTACT_OPENING" not in _ids(issues)


def test_msg_contact_banner_keeps_the_diagnosis_alive_without_a_deck():
    """An unreadable deck must not silently disable a real contact diagnosis."""
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG + MSG_WITH_CONTACT_BANNER,
        sta_text=FAILED_STA,
        job_status="SOLVER_FAILED",
        inp_text=None,
    )
    opening = [i for i in issues if i.diagnosis_id == "CONTACT_OPENING"]
    assert len(opening) == 1
    assert opening[0].metadata["contact_model_source"] == "msg"


def test_dat_contact_pair_echo_keeps_the_diagnosis_alive_without_a_deck():
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG,
        sta_text=FAILED_STA,
        dat_text=DAT_WITH_CONTACT_PAIR,
        job_status="SOLVER_FAILED",
        inp_text=None,
    )
    opening = [i for i in issues if i.diagnosis_id == "CONTACT_OPENING"]
    assert len(opening) == 1
    assert opening[0].metadata["contact_model_source"] == "dat"


def test_contact_controls_echo_alone_is_not_contact_evidence():
    """The remediation writes *contactcontrols, so it cannot prove contact exists."""
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG,
        sta_text=FAILED_STA,
        dat_text=DAT_WITH_CONTACT_CONTROLS_ONLY,
        job_status="SOLVER_FAILED",
        inp_text=None,
    )
    assert "CONTACT_OPENING" not in _ids(issues)


def test_generic_contact_tolerances_are_not_contact_evidence():
    """Measured: a no-contact failing model still prints contact tolerances."""
    issues = diagnose_solver_artifacts(
        msg_text=MSG_WITHOUT_CONTACT,
        sta_text=FAILED_STA,
        dat_text=DAT_WITHOUT_CONTACT,
        job_status="SOLVER_FAILED",
        inp_text=NO_CONTACT_DECK,
    )
    assert "CONTACT_OPENING" not in _ids(issues)


def test_no_contact_evidence_anywhere_still_suppresses():
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG,
        sta_text=FAILED_STA,
        dat_text=DAT_WITHOUT_CONTACT,
        job_status="SOLVER_FAILED",
        inp_text=NO_CONTACT_DECK,
    )
    assert "CONTACT_OPENING" not in _ids(issues)


def test_deck_evidence_takes_precedence_and_is_named():
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG + MSG_WITH_CONTACT_BANNER,
        sta_text=FAILED_STA,
        dat_text=DAT_WITH_CONTACT_PAIR,
        job_status="SOLVER_FAILED",
        inp_text=CONTACT_DECK,
    )
    opening = [i for i in issues if i.diagnosis_id == "CONTACT_OPENING"]
    assert len(opening) == 1
    assert opening[0].metadata["contact_model_source"] == "deck"


def test_artifact_evidence_still_requires_failure_evidence():
    """Broadened contact evidence must not weaken the failure gate."""
    issues = diagnose_solver_artifacts(
        msg_text=SINGULAR_CONTACT_MSG + MSG_WITH_CONTACT_BANNER,
        sta_text=CONVERGED_STA,
        job_status="COMPLETED",
        inp_text=None,
    )
    assert "CONTACT_OPENING" not in _ids(issues)


# Verbatim from the two no-contact failures solved for this change. Both print
# *generic* contact tolerance text, so only the pair banner distinguishes them.
NO_CONTACT_FAILING_MSG = """
     SOFT CONTACT CONSTRAINT COMPATIBILITY TOLERANCE FOR P>P0          5.000E-03
     SOFT CONTACT CONSTRAINT COMPATIBILITY TOLERANCE FOR P=0.0         0.100
     CONTACT FORCE ERROR TOLERANCE FOR CONVERT SDI=YES                 1.00
     MAXIMUM CONTACT AUGMENTATIONS FOR *SURFACE BEHAVIOR,AUGMENTED LAGRANGE   50

 ***WARNING: SOLVER PROBLEM. NUMERICAL SINGULARITY WHEN PROCESSING NODE
             N18 D.O.F. 3 RATIO = 10.E+12     .

***ERROR: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT
"""

TIE_ONLY_DECK = """
*Surface, type=ELEMENT, name=MASTER
LOWER, S2
*Surface, type=ELEMENT, name=SLAVE
UPPER, S1
*Tie, name=TIE1, adjust=NO
SLAVE, MASTER
"""


def test_tie_only_singular_failure_is_not_attributed_to_contact():
    """Measured: a *Tie model failing with 75 singularities shows no contact."""
    issues = diagnose_solver_artifacts(
        msg_text=NO_CONTACT_FAILING_MSG,
        sta_text=FAILED_STA,
        dat_text=DAT_WITHOUT_CONTACT,
        job_status="FAILED",
        inp_text=TIE_ONLY_DECK,
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

    # REQ-4.13: confirmation cannot authorize writing contact stabilization.
    # The parameters stay on an unapplied proposal.
    proposals = [
        item for item in updated.metadata["proposed_remediations"]
        if item["category"] == "CONTACT_STABILIZATION"
    ]
    assert proposals
    assert proposals[-1]["applied"] is False
    assert proposals[-1]["parameters"]["contact_damping"] is True
    assert proposals[-1]["parameters"]["stabilization_magnitude"] == 1e-4
    assert proposals[-1]["parameters"]["max_dissipation_ratio"] == 0.05
    assert "contact_stabilization" not in updated.metadata
    assert "contact_damping" not in updated.metadata.get("step_controls", {})
    assert "stabilization_energy_threshold" not in updated.metadata
