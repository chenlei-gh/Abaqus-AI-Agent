import json
from tools.mesh_convergence_e2e import build_mesh_convergence_script, _extract_report
from abaqus_ai_agent.contracts.convergence import (
    MeshConvergencePoint, MeshConvergencePolicy, evaluate_mesh_convergence,
)
from abaqus_ai_agent.contracts.mesh_quality import MeshQualityResult
from abaqus_ai_agent.numerical_verification import verify_richardson
from abaqus_ai_agent.acceptance import evaluate_result_acceptance


def test_mesh_convergence_script_uses_existing_pipeline():
    script = build_mesh_convergence_script()
    for marker in (
        "build_static_plan(",
        "AnalysisRunner(executor).run(",
        "extract_field(",
        "reaction_balance_from_field_evidence(",
        "verify_richardson(",
        "evaluate_mesh_convergence(",
        "evaluate_result_acceptance(",
        "seed_part(",
        "generate_mesh(",
        "create_job(",
    ):
        assert marker in script


def test_mesh_convergence_script_has_no_direct_process_solver_bypass():
    script = build_mesh_convergence_script()
    assert "subprocess" not in script
    assert "run_input(" not in script
    assert "run_nogui(" not in script


def test_mesh_convergence_report_parser():
    report = {"status": "pass", "runs": [{"case": "coarse"}, {"case": "medium"}, {"case": "fine"}]}
    stdout = (
        "noise\n"
        "AIAgent_MESH_CONVERGENCE_RESULT_BEGIN\n"
        + json.dumps(report)
        + "\nAIAgent_MESH_CONVERGENCE_RESULT_END\n"
    )
    assert _extract_report(stdout) == report


def test_mesh_convergence_report_parser_rejects_missing_markers():
    assert _extract_report("{}") is None


def test_mesh_convergence_acceptance_sensitivity():
    # Synthetic converging series with ratio=2.0
    # Values: coarse=2.00, medium=2.06, fine=2.075
    displacements = (2.00, 2.06, 2.075)
    points = (
        MeshConvergencePoint(5.0, 2.00, quantity="tip_displacement", source="coarse.odb", quality_status="pass"),
        MeshConvergencePoint(2.5, 2.06, quantity="tip_displacement", source="medium.odb", quality_status="pass"),
        MeshConvergencePoint(1.25, 2.075, quantity="tip_displacement", source="fine.odb", quality_status="pass"),
    )

    # Standard tolerance: passes
    richardson_std = verify_richardson("tip_displacement", displacements, 2.0, tolerance=0.10)
    assert richardson_std.passed is True

    policy_std = MeshConvergencePolicy(tolerance=0.05, minimum_points=3, relative=True, require_quality_pass=True)
    conv_std = evaluate_mesh_convergence(points, policy_std)
    assert conv_std.converged is True

    quality_gate = MeshQualityResult(status="pass")

    acceptance_std = evaluate_result_acceptance(
        result_status="completed",
        numerical=richardson_std,
        convergence=conv_std,
        mesh_quality=quality_gate,
        values={"tip_displacement": 2.075},
        criteria=({"name": "tip", "value_key": "tip_displacement", "operator": ">=", "limit": 1.0},),
    )
    assert acceptance_std.passed is True

    # Strict tolerance: explicitly fails
    richardson_strict = verify_richardson("tip_displacement", displacements, 2.0, tolerance=1e-6)
    assert richardson_strict.passed is False

    policy_strict = MeshConvergencePolicy(tolerance=1e-6, minimum_points=3, relative=True, require_quality_pass=True)
    conv_strict = evaluate_mesh_convergence(points, policy_strict)
    assert conv_strict.converged is False

    acceptance_strict = evaluate_result_acceptance(
        result_status="completed",
        numerical=richardson_strict,
        convergence=conv_strict,
        mesh_quality=quality_gate,
        values={"tip_displacement": 2.075},
        criteria=({"name": "tip", "value_key": "tip_displacement", "operator": ">=", "limit": 1.0},),
    )
    assert acceptance_strict.passed is False
    assert "numerical_verification_failed" in acceptance_strict.failures
    assert "mesh_convergence_failed" in acceptance_strict.failures
