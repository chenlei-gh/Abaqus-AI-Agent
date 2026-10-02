from tools.h5_solver_failure_diagnostics_e2e import run_h5_solver_failure_diagnostics


def test_h5_solver_failure_diagnostics_e2e():
    evidence = run_h5_solver_failure_diagnostics()
    assert evidence["status"] == "PASS"
    assert evidence["diagnosed_issues_count"] >= 2
    assert "NUMERICAL_SINGULARITY" in evidence["diagnosed_ids"]
    assert len(evidence["remediation_actions"]) >= 2
    assert evidence["run_transition_verified"]["from_acceptance"]["passed"] is False
    assert evidence["run_transition_verified"]["to_acceptance"]["passed"] is True
