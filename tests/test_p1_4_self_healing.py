"""Unit and regression tests for P1.4 Solver Failure Diagnostics & Controlled Self-Healing.

Validates:
1. Self-healing contracts: RemediationAction, HealingAttempt, SelfHealingResult immutability and serialization.
2. SolverRemediator remediation generation:
   - ZERO_PIVOT / NUMERICAL_SINGULARITY -> Encastre BC remediation
   - TIME_INCREMENT_LESS_THAN_MINIMUM / TOO_MANY_CUTBACKS -> Step cutback & stabilization
   - CONTACT_CHATTER -> Contact stabilization
   - LICENSE_DENIED / UNRESOLVED -> Mark unhealable / retry not allowed (fail-closed)
3. SelfHealingOrchestrator behavior:
   - Max attempts enforcement (bounded retry, no infinite loop)
   - Unrecoverable error early exit
   - Successful healing loop with RunDiff tracking and single-exit Acceptance
4. solve_requirement integration:
   - End-to-end self-healing flow when primary run fails
   - Report renderer integration (Chapter 14b Solver Diagnostics & Self-Healing Audit)
   - Fail-closed behavior when healing is disabled or fails
"""

import pytest
from typing import Any, Dict

from abaqus_ai_agent.contracts.diagnostics import (
    DiagnosticSeverity,
    RemediationCategory,
    RemediationRisk,
    RemediationAction,
    HealingAttempt,
    SelfHealingResult,
)
from abaqus_ai_agent.diagnostics.solver_patterns import (
    DiagnosticIssue,
    diagnose_solver_artifacts,
)
from abaqus_ai_agent.diagnostics.remediator import SolverRemediator
from abaqus_ai_agent.diagnostics.orchestrator import SelfHealingOrchestrator
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
from abaqus_ai_agent.planning.compiler import CompiledAgentPlan, IntentGeometrySpec
from abaqus_ai_agent.contracts.provenance import AnalysisProvenance
from abaqus_ai_agent.contracts.metrics import EngineeringMetric
from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
from abaqus_ai_agent.reporting.renderer import render_markdown
from abaqus_ai_agent.contracts.report import EngineeringReportData
from abaqus_ai_agent.contracts.task import EngineeringTaskResult, TaskStatus
from abaqus_ai_agent.contracts.capability import resolve_capability
from abaqus_ai_agent.execution.client import AbaqusExecutor
from abaqus_ai_agent.agent import AbaqusAIAgent


class MockExecutor(AbaqusExecutor):
    def execute(self, code, timeout=120):
        return {"status": "COMPLETED"}

    def monitor_job(self, name, timeout=3600, poll_seconds=2.0):
        return {"status": "COMPLETED"}

    def snapshot(self):
        return None


# ---------------------------------------------------------------------------
# 1. Contract tests
# ---------------------------------------------------------------------------

def test_remediation_action_contract():
    action = RemediationAction(
        action_id="act_bc_001",
        category=RemediationCategory.BOUNDARY_CONDITION,
        diagnosis_id="ZERO_PIVOT",
        description="Add missing encastre BC to eliminate zero pivot",
        parameters={"region": "BaseFace", "dofs": [1, 2, 3, 4, 5, 6]},
        rationale="Eliminates rigid body motion",
        risk_level=RemediationRisk.LOW,
    )
    d = action.to_dict()
    assert d["action_id"] == "act_bc_001"
    assert d["category"] == "BOUNDARY_CONDITION"
    assert d["diagnosis_id"] == "ZERO_PIVOT"
    assert d["risk_level"] == "LOW"
    assert d["parameters"]["region"] == "BaseFace"


def test_self_healing_result_contract():
    action = RemediationAction(
        action_id="act_step_001",
        category=RemediationCategory.STEP_CONTROLS,
        diagnosis_id="TOO_MANY_CUTBACKS",
        description="Reduce initial increment",
        parameters={"initial_inc": 0.01},
        risk_level=RemediationRisk.LOW,
    )
    attempt = HealingAttempt(
        attempt_number=1,
        trigger_issues=("TOO_MANY_CUTBACKS",),
        actions_applied=(action,),
        pre_run_id="run_orig",
        post_run_id="run_attempt_1",
        outcome="ACCEPTED",
    )
    res = SelfHealingResult(
        healed=True,
        total_attempts=1,
        initial_status="FAILED",
        final_status="ACCEPTED",
        remediations_applied=(action,),
        attempts=(attempt,),
    )
    d = res.to_dict()
    assert d["healed"] is True
    assert d["total_attempts"] == 1
    assert len(d["attempts"]) == 1
    assert d["attempts"][0]["actions_applied"][0]["action_id"] == "act_step_001"


# ---------------------------------------------------------------------------
# 2. SolverRemediator tests
# ---------------------------------------------------------------------------

def test_remediator_zero_pivot_singularity():
    remediator = SolverRemediator()
    intent = EngineeringIntent(
        id="intent_test_1",
        kind="static_analysis",
        description="Bracket analysis",
        analysis_type="linear_static",
        boundary_conditions=(),  # empty BCs causing singularity
    )
    issue = DiagnosticIssue(
        diagnosis_id="NUMERICAL_SINGULARITY",
        severity="ERROR",
        supporting_evidence=("***WARNING: NUMERICAL SINGULARITY DETECTED",),
        likely_cause="Unconstrained rigid body motion; degrees of freedom unconstrained.",
        suggested_remediation="Add encastre BC on bottom/fixed region.",
    )
    actions = remediator.generate_remediations([issue], intent)
    assert len(actions) >= 1
    assert any(a.category == RemediationCategory.BOUNDARY_CONDITION for a in actions)

    # Apply remediation
    remediated_intent = remediator.apply_remediations(intent, actions)
    assert len(remediated_intent.boundary_conditions) >= 1
    bc = remediated_intent.boundary_conditions[0]
    if isinstance(bc, dict):
        assert bc["type"] == "ENCASTRE"
    else:
        assert bc.bc_type == "ENCASTRE"


def test_remediator_cutbacks_and_stabilization():
    remediator = SolverRemediator()
    intent = EngineeringIntent(
        id="intent_test_2",
        kind="static_analysis",
        description="Block compression",
        analysis_type="linear_static",
    )
    issues = [
        DiagnosticIssue(
            diagnosis_id="TIME_INCREMENT_LESS_THAN_MINIMUM",
            severity="ERROR",
            supporting_evidence=("***ERROR: TIME INCREMENT LESS THAN MINIMUM",),
            likely_cause="Severe nonlinearity or contact discontinuity.",
            suggested_remediation="Reduce min_inc and increase max_num_inc.",
        ),
        DiagnosticIssue(
            diagnosis_id="TOO_MANY_CUTBACKS",
            severity="ERROR",
            supporting_evidence=("***ERROR: TOO MANY CUTBACKS MADE FOR THIS INCREMENT",),
            likely_cause="Convergence failure during iteration.",
            suggested_remediation="Add stabilization damping.",
        ),
    ]
    actions = remediator.generate_remediations(issues, intent)
    assert len(actions) >= 1

    remediated_intent = remediator.apply_remediations(intent, actions)
    step_controls = remediated_intent.metadata.get("step_controls", {})
    assert step_controls.get("max_num_inc", 0) >= 200
    assert step_controls.get("stabilization_method") == "DAMPING_FACTOR"
    assert step_controls.get("stabilization_magnitude", 0.0) > 0.0


def test_remediator_license_denied_blocks_healing():
    remediator = SolverRemediator()
    intent = EngineeringIntent(
        id="intent_test_3",
        kind="static_analysis",
        description="Block model",
        analysis_type="linear_static",
    )
    issue = DiagnosticIssue(
        diagnosis_id="LICENSE_DENIED",
        severity="FATAL",
        supporting_evidence=("Abaqus license tokens unavailable",),
        likely_cause="Abaqus license tokens unavailable.",
        suggested_remediation="Wait for license server or contact administrator.",
    )
    actions = remediator.generate_remediations([issue], intent)
    # Must produce UNRESOLVED remediation with retry_allowed=False
    assert len(actions) >= 1
    assert any(a.category == RemediationCategory.UNRESOLVED for a in actions)
    assert any(a.parameters.get("retry_allowed") is False for a in actions)


from abaqus_ai_agent.acceptance import AcceptanceResult
# ---------------------------------------------------------------------------

def test_orchestrator_max_attempts_cutoff():
    agent = AbaqusAIAgent(executor=MockExecutor())
    capability = resolve_capability("linear_static")

    call_count = 0

    def mock_analysis_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return AnalysisRun(
            id=f"run_attempt_{call_count}",
            model_name="TestModel",
            job_name="TestJob",
            state=AnalysisRunState.FAILED,
            acceptance_passed=False,
            diagnostics=({"diagnosis_id": "NUMERICAL_SINGULARITY", "severity": "ERROR"},),
        )

    agent.analysis_run = mock_analysis_run

    initial_run = AnalysisRun(
        id="run_init",
        model_name="TestModel",
        job_name="TestJob",
        state=AnalysisRunState.FAILED,
        engineering_status="SOLVER_SINGULARITY",
        acceptance_passed=False,
        diagnostics=({"diagnosis_id": "NUMERICAL_SINGULARITY", "severity": "ERROR"},),
    )
    geom = IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0)
    mat = MaterialDefinition(
        name="Steel_Q235",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    initial_intent = EngineeringIntent(
        id="intent_test_4",
        kind="linear_static",
        description="Test requirement",
        analysis_type="linear_static",
        boundary_conditions=({"type": "displacement", "region": "FixedFace", "u1": 0.0},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        metadata={"dimensions": {"shape": "cantilever_box", "length": 120.0, "width": 12.0, "height": 8.0}},
    )
    initial_plan = CompiledAgentPlan(
        model_name="TestModel",
        part_name="TestPart",
        job_name="TestJob",
        actions=(),
        cae_script="",
        intent_summary={},
    )

    final_run, result = SelfHealingOrchestrator.attempt_healing(
        agent=agent,
        failed_run=initial_run,
        intent=initial_intent,
        capability=capability,
        plan=initial_plan,
        geometry=geom,
        material=mat,
        max_attempts=2,
    )

    assert result.healed is False
    assert result.total_attempts == 2
    assert len(result.attempts) == 2
    assert call_count == 2
    assert final_run.state == AnalysisRunState.FAILED


def test_orchestrator_success_on_first_remediation():
    agent = AbaqusAIAgent(executor=MockExecutor())
    capability = resolve_capability("linear_static")

    call_count = 0

    def mock_analysis_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        acc = AcceptanceResult(
            passed=True,
            criteria=(),
            status="PASS",
            result_validity="VALID",
            evidence_status="VALID",
        )
        return AnalysisRun(
            id=f"run_attempt_{call_count}",
            model_name="TestModel",
            job_name="TestJob",
            state=AnalysisRunState.ACCEPTED,
            engineering_status="RESULT_VALID",
            acceptance_passed=True,
            acceptance=acc,
            metrics=(EngineeringMetric(name="reaction_force_y", value=1000.0, unit="N"),),
        )

    agent.analysis_run = mock_analysis_run

    initial_run = AnalysisRun(
        id="run_init",
        model_name="TestModel",
        job_name="TestJob",
        state=AnalysisRunState.FAILED,
        engineering_status="SOLVER_SINGULARITY",
        acceptance_passed=False,
        diagnostics=({"diagnosis_id": "NUMERICAL_SINGULARITY", "severity": "ERROR"},),
    )
    geom = IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0)
    mat = MaterialDefinition(
        name="Steel_Q235",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    initial_intent = EngineeringIntent(
        id="intent_test_5",
        kind="linear_static",
        description="Test requirement",
        analysis_type="linear_static",
        boundary_conditions=({"type": "displacement", "region": "FixedFace", "u1": 0.0},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        metadata={"dimensions": {"shape": "cantilever_box", "length": 120.0, "width": 12.0, "height": 8.0}},
    )
    initial_plan = CompiledAgentPlan(
        model_name="TestModel",
        part_name="TestPart",
        job_name="TestJob",
        actions=(),
        cae_script="",
        intent_summary={},
    )

    final_run, result = SelfHealingOrchestrator.attempt_healing(
        agent=agent,
        failed_run=initial_run,
        intent=initial_intent,
        capability=capability,
        plan=initial_plan,
        geometry=geom,
        material=mat,
        max_attempts=2,
    )

    assert result.healed is True
    assert result.total_attempts == 1
    assert final_run.state == AnalysisRunState.ACCEPTED
    assert final_run.acceptance_passed is True
    assert len(result.attempts) == 1
    assert result.attempts[0].post_run_id == "run_attempt_1"


# ---------------------------------------------------------------------------
# 4. solve_requirement integration with self-healing
# ---------------------------------------------------------------------------

def test_solve_requirement_self_healing_end_to_end():
    agent = AbaqusAIAgent(executor=MockExecutor())

    run_invocations = 0

    def fake_analysis_run(*args, **kwargs):
        nonlocal run_invocations
        run_invocations += 1
        if run_invocations == 1:
            # First attempt fails with NUMERICAL_SINGULARITY
            return AnalysisRun(
                id="run_fail_1",
                model_name="BracketModel",
                job_name="BracketJob",
                state=AnalysisRunState.FAILED,
                engineering_status="SOLVER_SINGULARITY",
                acceptance_passed=False,
                diagnostics=({
                    "diagnosis_id": "NUMERICAL_SINGULARITY",
                    "severity": "ERROR",
                    "likely_cause": "Underconstrained boundary conditions.",
                    "suggested_remediation": "Add encastre boundary condition.",
                },),
            )
        else:
            # Second attempt (after self-healing remediation) succeeds
            acc = AcceptanceResult(
                passed=True,
                criteria=(),
                status="PASS",
                result_validity="VALID",
                evidence_status="VALID",
            )
            return AnalysisRun(
                id="run_healed_2",
                model_name="BracketModel",
                job_name="BracketJob_Healed",
                state=AnalysisRunState.ACCEPTED,
                engineering_status="RESULT_VALID",
                acceptance_passed=True,
                acceptance=acc,
                metrics=(
                    EngineeringMetric(name="max_mises", value=210.0, unit="MPa"),
                    EngineeringMetric(name="reaction_force", value=1000.0, unit="N"),
                ),
            )

    agent.analysis_run = fake_analysis_run

    geom = IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0)
    mat = MaterialDefinition(
        name="Steel_Q235",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    intent = EngineeringIntent(
        id="REQ-HEAL-001",
        kind="linear_static",
        description="Bracket with missing boundary condition causing singularity",
        material={"name": "Steel_Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        boundary_conditions=({"type": "displacement", "region": "FixedFace", "u1": 0.0},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        metadata={"dimensions": {"shape": "cantilever_box", "length": 120.0, "width": 12.0, "height": 8.0}},
    )

    result = agent.solve_requirement(
        requirement=intent,
        geometry=geom,
        material=mat,
        enable_self_healing=True,
        max_healing_attempts=2,
    )

    # Assertions on final result
    assert result.status == TaskStatus.COMPLETED
    assert result.run.state == AnalysisRunState.ACCEPTED
    assert result.run.acceptance_passed is True
    assert result.acceptance.passed is True

    # Audit metadata verifies healing happened
    healing_data = result.metadata.get("self_healing")
    assert healing_data is not None
    assert healing_data.get("healed") is True
    assert healing_data.get("total_attempts") == 1
    assert result.summary_card.get("self_healing", {}).get("healed") is True
    assert result.summary_card.get("self_healing", {}).get("total_attempts") == 1

    # Report verification: Chapter 14b must be rendered
    assert result.report_markdown is not None
    assert "14b. Solver Diagnostics & Self-Healing Audit" in result.report_markdown


def test_solve_requirement_self_healing_disabled():
    agent = AbaqusAIAgent(executor=MockExecutor())

    run_invocations = 0

    def fake_analysis_run(*args, **kwargs):
        nonlocal run_invocations
        run_invocations += 1
        return AnalysisRun(
            id="run_fail_no_heal",
            model_name="BracketModel",
            job_name="BracketJob",
            state=AnalysisRunState.FAILED,
            acceptance_passed=False,
            diagnostics=({
                "diagnosis_id": "NUMERICAL_SINGULARITY",
                "severity": "ERROR",
            },),
        )

    agent.analysis_run = fake_analysis_run

    geom = IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0)
    mat = MaterialDefinition(
        name="Steel_Q235",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    intent = EngineeringIntent(
        id="REQ-HEAL-FAIL-001",
        kind="linear_static",
        description="Bracket failing without self-healing",
        material={"name": "Steel_Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        boundary_conditions=({"type": "displacement", "region": "FixedFace", "u1": 0.0},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        metadata={"dimensions": {"shape": "cantilever_box", "length": 120.0, "width": 12.0, "height": 8.0}},
    )

    result = agent.solve_requirement(
        requirement=intent,
        geometry=geom,
        material=mat,
        enable_self_healing=False,  # Explicitly disabled
    )

    assert result.status == TaskStatus.FAILED
    assert run_invocations == 1
    assert result.metadata.get("self_healing") is None


def test_remediator_contact_chatter_stabilization():
    remediator = SolverRemediator()
    intent = EngineeringIntent(
        id="intent_contact_1",
        kind="contact_analysis",
        description="Contact chatter problem",
        analysis_type="general_contact",
    )
    issue = DiagnosticIssue(
        diagnosis_id="CONTACT_CHATTER",
        severity="WARNING",
        supporting_evidence=("***WARNING: SEVERE DISCONTINUITY ITERATION OR CONTACT CHATTER",),
        likely_cause="Contact chatter opening and closing oscillation.",
        suggested_remediation="Add contact stabilization damping.",
    )
    actions = remediator.generate_remediations([issue], intent)
    assert len(actions) >= 1
    assert any(a.category == RemediationCategory.CONTACT_STABILIZATION for a in actions)

    remediated = remediator.apply_remediations(intent, actions)
    step_controls = remediated.metadata.get("step_controls", {})
    assert step_controls.get("contact_damping") is True
    assert step_controls.get("stabilization_magnitude", 0.0) > 0.0


def test_remediator_negative_eigenvalue():
    remediator = SolverRemediator()
    intent = EngineeringIntent(
        id="intent_eigen_1",
        kind="linear_static",
        description="Pre-buckling instability",
        analysis_type="linear_static",
    )
    issue = DiagnosticIssue(
        diagnosis_id="NEGATIVE_EIGENVALUE",
        severity="WARNING",
        supporting_evidence=("***WARNING: NEGATIVE EIGENVALUE DETECTED IN STIFFNESS MATRIX",),
        likely_cause="Local geometric instability or negative tangent stiffness.",
        suggested_remediation="Add automatic stabilization damping.",
    )
    actions = remediator.generate_remediations([issue], intent)
    assert len(actions) >= 1
    assert any(a.category == RemediationCategory.DAMPING for a in actions)


def test_orchestrator_unhealable_license_denied_aborts_immediately():
    agent = AbaqusAIAgent(executor=MockExecutor())
    capability = resolve_capability("linear_static")

    call_count = 0

    def mock_analysis_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return AnalysisRun(
            id=f"run_attempt_{call_count}",
            model_name="TestModel",
            job_name="TestJob",
            state=AnalysisRunState.FAILED,
            acceptance_passed=False,
        )

    agent.analysis_run = mock_analysis_run

    initial_run = AnalysisRun(
        id="run_license_fail",
        model_name="TestModel",
        job_name="TestJob",
        state=AnalysisRunState.FAILED,
        engineering_status="LICENSE_UNAVAILABLE",
        acceptance_passed=False,
        diagnostics=({
            "diagnosis_id": "LICENSE_DENIED",
            "severity": "FATAL",
            "supporting_evidence": ("Abaqus license tokens unavailable",),
        },),
    )
    geom = IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0)
    mat = MaterialDefinition(
        name="Steel_Q235",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    initial_intent = EngineeringIntent(
        id="intent_lic",
        kind="linear_static",
        description="License denial test",
        analysis_type="linear_static",
    )
    initial_plan = CompiledAgentPlan(
        model_name="TestModel",
        part_name="TestPart",
        job_name="TestJob",
        actions=(),
        cae_script="",
        intent_summary={},
    )

    final_run, result = SelfHealingOrchestrator.attempt_healing(
        agent=agent,
        failed_run=initial_run,
        intent=initial_intent,
        capability=capability,
        plan=initial_plan,
        geometry=geom,
        material=mat,
        max_attempts=3,
    )

    # Must abort on attempt 1 without executing new runs
    assert result.healed is False
    assert result.total_attempts == 0
    assert call_count == 0
    assert final_run.state == AnalysisRunState.FAILED


def test_self_healing_result_run_diff_tracking():
    action = RemediationAction(
        action_id="act_bc_fixed",
        category=RemediationCategory.BOUNDARY_CONDITION,
        diagnosis_id="ZERO_PIVOT",
        description="Add full fixity",
        risk_level=RemediationRisk.LOW,
    )
    attempt = HealingAttempt(
        attempt_number=1,
        trigger_issues=("ZERO_PIVOT",),
        actions_applied=(action,),
        pre_run_id="run_0",
        post_run_id="run_1",
        run_diff={
            "baseline_id": "run_0",
            "candidate_id": "run_1",
            "acceptance_diff": {"baseline": {"passed": False}, "candidate": {"passed": True}},
        },
        outcome="ACCEPTED",
    )
    res = SelfHealingResult(
        healed=True,
        total_attempts=1,
        initial_status="SOLVER_SINGULARITY",
        final_status="RESULT_VALID",
        remediations_applied=(action,),
        attempts=(attempt,),
        final_run_diff=attempt.run_diff,
    )
    d = res.to_dict()
    assert d["healed"] is True
    assert d["final_run_diff"]["candidate_id"] == "run_1"
    assert d["attempts"][0]["run_diff"]["acceptance_diff"]["candidate"]["passed"] is True


def test_renderer_chapter_14b_format():
    action = RemediationAction(
        action_id="act_bc_fixed",
        category=RemediationCategory.BOUNDARY_CONDITION,
        diagnosis_id="ZERO_PIVOT",
        description="Add full fixity on root region",
        risk_level=RemediationRisk.LOW,
    )
    attempt = HealingAttempt(
        attempt_number=1,
        trigger_issues=("ZERO_PIVOT",),
        actions_applied=(action,),
        pre_run_id="run_0",
        post_run_id="run_1",
        run_diff={
            "baseline_id": "run_0",
            "candidate_id": "run_1",
            "acceptance_diff": {"baseline": {"passed": False}, "candidate": {"passed": True}},
        },
        outcome="ACCEPTED",
    )
    res = SelfHealingResult(
        healed=True,
        total_attempts=1,
        initial_status="SOLVER_SINGULARITY",
        final_status="RESULT_VALID",
        diagnosed_issues=(
            DiagnosticIssue(
                diagnosis_id="ZERO_PIVOT",
                severity="ERROR",
                supporting_evidence=("***WARNING: SOLVER PROBLEM. ZERO PIVOT",),
                likely_cause="Zero pivot at node 101 DOF 1",
                suggested_remediation="Add encastre BC",
            ),
        ),
        remediations_applied=(action,),
        attempts=(attempt,),
        final_run_diff=attempt.run_diff,
    )

    report_data = EngineeringReportData(
        title="Diagnostic Self-Healing Test Report",
        model={"model_name": "TestModel"},
        self_healing=res,
    )

    md = render_markdown(report_data)
    assert "14b. Solver Diagnostics & Self-Healing Audit" in md
    assert "ZERO_PIVOT" in md
    assert "Add full fixity on root region" in md
    assert "run_0" in md and "run_1" in md
    assert "YES (Self-Healed)" in md


def test_false_healing_semantic_preservation_mechanism_not_locked():
    """Verify semantic preservation guard: mechanisms/connectors/FMBD must never be blindly locked with ENCASTRE."""
    remediator = SolverRemediator()

    # Case A: Intent with connector components
    intent_connector = EngineeringIntent(
        id="intent_mech_1",
        kind="dynamic_kinematics",
        description="Four-bar linkage mechanism with revolute connectors",
        connectors=(
            {"name": "Conn_Hinge_1", "type": "HINGE", "region1": "P1", "region2": "P2"},
        ),
    )
    issue = DiagnosticIssue(
        diagnosis_id="ZERO_PIVOT",
        severity="ERROR",
        supporting_evidence=("***WARNING: ZERO PIVOT WHEN PROCESSING NODE 12 D.O.F. 6",),
        likely_cause="Free rotation along revolute axis.",
        suggested_remediation="Add encastre BC",
    )
    actions = remediator.generate_remediations([issue], intent=intent_connector)

    assert len(actions) == 1
    action = actions[0]
    # Must NOT be BOUNDARY_CONDITION
    assert action.category == RemediationCategory.UNRESOLVED
    assert action.risk_level == RemediationRisk.HIGH
    assert action.parameters.get("false_healing_blocked") is True
    assert action.parameters.get("retry_allowed") is False
    assert "cannot be resolved by applying blanket ENCASTRE" in action.description

    # Case B: Intent with description indicating mechanism
    intent_mech_desc = EngineeringIntent(
        id="intent_mech_2",
        kind="static_analysis",
        description="Slider-crank mechanism undergoing motion analysis",
    )
    singularity_issue = DiagnosticIssue(
        diagnosis_id="NUMERICAL_SINGULARITY",
        severity="ERROR",
        supporting_evidence=("***WARNING: NUMERICAL SINGULARITY DETECTED",),
        likely_cause="Unconstrained degree of freedom",
        suggested_remediation="Add encastre BC",
    )
    actions_desc = remediator.generate_remediations([singularity_issue], intent=intent_mech_desc)
    assert len(actions_desc) == 1
    assert actions_desc[0].category == RemediationCategory.UNRESOLVED
    assert actions_desc[0].parameters.get("false_healing_blocked") is True


def test_stabilization_dissipation_energy_threshold():
    """Verify artificial stabilization remediations enforce the <= 5% dissipation energy ratio guard."""
    remediator = SolverRemediator()
    intent = EngineeringIntent(
        id="intent_stab_1",
        kind="static_analysis",
        description="Contact problem with cutbacks",
    )
    issues = [
        DiagnosticIssue(
            diagnosis_id="TOO_MANY_CUTBACKS",
            severity="ERROR",
            supporting_evidence=("***ERROR: TOO MANY CUTBACKS",),
            likely_cause="Convergence difficulty",
            suggested_remediation="Stabilize",
        ),
        DiagnosticIssue(
            diagnosis_id="CONTACT_CHATTER",
            severity="WARNING",
            supporting_evidence=("***WARNING: CONTACT CHATTER",),
            likely_cause="Opening/closing chatter",
            suggested_remediation="Damp",
        ),
    ]
    actions = remediator.generate_remediations(issues, intent=intent)
    assert len(actions) >= 2
    for act in actions:
        if act.category in (RemediationCategory.STEP_CONTROLS, RemediationCategory.CONTACT_STABILIZATION, RemediationCategory.DAMPING):
            assert "max_dissipation_ratio" in act.parameters
            assert act.parameters["max_dissipation_ratio"] <= 0.05
