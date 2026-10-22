"""Solid-element distortion must not be healed by contact stabilization.

The fixture follows the real Abaqus/Standard failure combination:

  THE STRAIN INCREMENT HAS EXCEEDED FIFTY TIMES THE STRAIN TO CAUSE FIRST YIELD
  EXCESSIVE DISTORTION AT A TOTAL OF N INTEGRATION POINTS
  TOO MANY ATTEMPTS MADE FOR THIS INCREMENT

A falling distorted-point count is cutback history, not recovery.
"""

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.diagnostics.remediator import (
    RemediationCategory,
    SolverRemediator,
)
from abaqus_ai_agent.diagnostics.solver_patterns import diagnose_solver_artifacts


COMBINED_MSG = """
                        S T E P       1     S T A T I C   A N A L Y S I S

  INCREMENT    12 STARTS. ATTEMPT NUMBER  1, TIME INCREMENT  1.250E-02
***WARNING: THE STRAIN INCREMENT HAS EXCEEDED FIFTY TIMES THE STRAIN TO CAUSE
FIRST YIELD
***WARNING: EXCESSIVE DISTORTION AT A TOTAL OF 1056 INTEGRATION POINTS IN SOLID
***WARNING: THE STRAIN INCREMENT HAS EXCEEDED FIFTY TIMES THE STRAIN TO CAUSE
FIRST YIELD
***WARNING: EXCESSIVE DISTORTION AT A TOTAL OF 220 INTEGRATION POINTS IN SOLID
***ERROR: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT
"""


def _ids(issues):
    return {issue.diagnosis_id for issue in issues}


def test_combined_solid_distortion_is_one_convergence_failure():
    issues = diagnose_solver_artifacts(msg_text=COMBINED_MSG, job_status="SOLVER_FAILED")
    assert "SOLID_DISTORTION_CONVERGENCE" in _ids(issues)
    issue = next(item for item in issues if item.diagnosis_id == "SOLID_DISTORTION_CONVERGENCE")
    assert issue.severity == "ERROR"
    assert issue.metadata["distorted_point_counts"] == [1056, 220]
    assert issue.metadata["count_decrease_is_recovery"] is False
    assert issue.metadata["automatic_contact_stabilization_allowed"] is False
    assert issue.metadata["failed_increment"] == 12
    assert issue.metadata["failed_step"] == 1


def test_warning_alone_does_not_create_the_combined_diagnosis():
    warning_only = """
    ***WARNING: THE STRAIN INCREMENT HAS EXCEEDED FIFTY TIMES THE STRAIN TO CAUSE
    FIRST YIELD
    ***WARNING: EXCESSIVE DISTORTION AT A TOTAL OF 1056 INTEGRATION POINTS IN SOLID
    """
    issues = diagnose_solver_artifacts(msg_text=warning_only)
    assert "SOLID_DISTORTION_CONVERGENCE" not in _ids(issues)
    assert "STRAIN_INCREMENT_EXCEEDS_YIELD" in _ids(issues)
    assert "EXCESSIVE_DISTORTION" in _ids(issues)


def test_cutback_error_alone_does_not_create_the_combined_diagnosis():
    issues = diagnose_solver_artifacts(
        msg_text="***ERROR: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT\n"
    )
    assert "SOLID_DISTORTION_CONVERGENCE" not in _ids(issues)
    assert "TOO_MANY_CUTBACKS" in _ids(issues)


def test_combined_failure_forbids_contact_stabilization_and_damping():
    issues = diagnose_solver_artifacts(msg_text=COMBINED_MSG, job_status="SOLVER_FAILED")
    intent = EngineeringIntent(
        id="intent_distort",
        kind="static_analysis",
        description="Compressed solid with contact",
        analysis_type="nonlinear_static",
    )
    actions = SolverRemediator.generate_remediations(issues, intent)
    assert len(actions) == 1
    action = actions[0]
    assert action.category == RemediationCategory.UNRESOLVED
    assert action.diagnosis_id == "SOLID_DISTORTION_CONVERGENCE"
    assert action.parameters["retry_allowed"] is False
    assert action.parameters["automatic_contact_stabilization_allowed"] is False
    assert "local_mesh_refinement" in action.parameters["proposals_requiring_confirmation"]
    assert "CONTACT_STABILIZATION" not in {item.category.value for item in actions}
    assert "stabilization_method" not in action.parameters
