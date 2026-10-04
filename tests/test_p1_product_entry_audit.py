"""P1.0 Product Main Entry (solve_requirement) Audit and Fail-Closed Verification.

Validates the architectural integrity, capability routing across all 20 L4 domains,
fail-closed boundary gates, and anti-fabrication single-exit acceptance.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock
import pytest

from abaqus_ai_agent import AbaqusAIAgent
from abaqus_ai_agent.acceptance import AcceptanceResult
from abaqus_ai_agent.contracts.capability import (
    CapabilityStatus,
    resolve_capability,
    ALL_L4_CAPABILITIES,
)
from abaqus_ai_agent.execution.analysis_run import (
    AnalysisRun,
    AnalysisRunState,
)
from abaqus_ai_agent.contracts.metrics import EngineeringMetric
from abaqus_ai_agent.contracts.fatigue import IntentFatigueSpec
from abaqus_ai_agent.contracts.fmbd import IntentFMBDSpec, RigidBodySpec
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.task import EngineeringTaskResult, TaskStatus
from abaqus_ai_agent.execution.client import AbaqusExecutor
from abaqus_ai_agent.planning.compiler import (
    IntentBoundarySpec,
    IntentGeometrySpec,
    IntentLoadSpec,
    IntentMeshSpec,
    IntentStepSpec,
    compile_engineering_intent,
)
from abaqus_ai_agent.validation.preflight import PreflightResult


class MockExecutor(AbaqusExecutor):
    """Mock executor implementing AbaqusExecutor contract for non-solver unit audits."""
    def __init__(self):
        self.executed_commands = []

    def execute(self, code, timeout=120):
        self.executed_commands.append(code)
        if "mdb.jobs[" in code and "status" in code:
            return "COMPLETED"
        return {"status": "completed"}

    def inspect_odb(self, path):
        return {"status": "available", "steps": ["Step-1"]}


@dataclass(frozen=True)
class MockBlocker:
    action_type: str
    message: str


class TestP1ProductEntryAudit:
    """Audit suite covering P1.0 code contracts, capability mappings, and fail-closed gates."""

    @pytest.fixture
    def agent(self):
        """AbaqusAIAgent instance backed by MockExecutor."""
        agent_inst = AbaqusAIAgent(MockExecutor())
        agent_inst.apply_plan = MagicMock(return_value=[])
        return agent_inst

    def test_p1_01_nl_clarification_gate(self, agent):
        """Prompt lacking critical dimensions and material must fail closed to NEEDS_CLARIFICATION."""
        prompt = "对支架进行受力分析，看看应力大不大。"
        res = agent.solve_requirement(prompt)
        assert res.status == TaskStatus.NEEDS_CLARIFICATION
        assert res.clarification_prompt is not None
        missing = res.metadata.get("missing_requirements", ())
        assert any("material" in item for item in missing) or any("dimensions" in item for item in missing)
        assert res.run is None  # Zero solver dispatch

    def test_p1_02_unsupported_domain_gate(self, agent):
        """Unsupported domains such as CFD or aerodynamics must yield UNSUPPORTED and halt."""
        intent = EngineeringIntent(
            id="intent-cfd-01",
            kind="aerodynamics",
            description="Wing Airflow Analysis",
            analysis_type="aerodynamics_cfd",
            unit_system="MM_N_MPA",
        )
        res = agent.solve_requirement(intent)
        assert res.status == TaskStatus.UNSUPPORTED
        assert "outside the 20 L4 verified Abaqus FEA" in res.errors[0]
        assert res.plan is None
        assert res.run is None

    def test_p1_03_missing_geometry_compilation_blocked(self, agent):
        """Intent with material and loads but missing geometry must block compilation fail-closed."""
        intent = EngineeringIntent(
            id="intent-no-geom-01",
            kind="linear_static",
            description="No-Geometry Intent",
            analysis_type="linear_static",
            unit_system="MM_N_MPA",
            material={
                "name": "Steel",
                "youngs_modulus": 210000.0,
                "poisson_ratio": 0.3,
            },
            loads=(IntentLoadSpec(name="TipLoad", load_type="concentrated_force", region="TipFace", magnitude=1000.0),),
        )
        res = agent.solve_requirement(intent)
        assert res.status == TaskStatus.BLOCKED
        assert any("missing geometry specification" in err for err in res.errors)

    def test_p1_04_missing_material_compilation_blocked(self, agent):
        """Intent with geometry and loads but missing material must block compilation fail-closed."""
        intent = EngineeringIntent(
            id="intent-no-mat-01",
            kind="linear_static",
            description="No-Material Intent",
            analysis_type="linear_static",
            unit_system="MM_N_MPA",
            metadata={"geometry": IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)},
            loads=(IntentLoadSpec(name="TipLoad", load_type="concentrated_force", region="TipFace", magnitude=1000.0),),
        )
        res = agent.solve_requirement(intent)
        assert res.status == TaskStatus.BLOCKED
        assert any("missing material specification" in err for err in res.errors)

    def test_p1_05_external_input_anti_fabrication(self, agent):
        """External result injection must NEVER reach TaskStatus.COMPLETED or ACCEPTED."""
        intent = EngineeringIntent(
            id="intent-tamper-probe",
            kind="linear_static",
            description="External Input Tamper Probe",
            analysis_type="linear_static",
            unit_system="MM_N_MPA",
            material={
                "name": "Steel",
                "youngs_modulus": 210000.0,
                "poisson_ratio": 0.3,
            },
            metadata={"geometry": IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)},
        )
        # Attempt to pass fake external results
        res = agent.solve_requirement(
            intent,
            odb_path="dummy.odb",
            result_values={"max_mises": 150.0, "tip_deflection": 0.5},
            criteria=[
                {"name": "stress", "value_key": "max_mises", "operator": "<=", "limit": 100.0},
            ],
            submit_job=False,
        )
        # Must fail closed because result_source == 'external_input'
        assert res.status == TaskStatus.FAILED
        assert res.run is not None
        assert res.run.state != AnalysisRunState.ACCEPTED
        assert res.run.engineering_status != "RESULT_VALID"
        assert bool(res.run.acceptance_passed) is False

    def test_p1_06_preflight_blocker_interception(self, agent, monkeypatch):
        """Preflight gate blockers must halt execution before solver dispatch."""
        intent = EngineeringIntent(
            id="intent-preflight-probe",
            kind="linear_static",
            description="Preflight Blocker Probe",
            analysis_type="linear_static",
            unit_system="MM_N_MPA",
            material={
                "name": "Steel",
                "youngs_modulus": 210000.0,
                "poisson_ratio": 0.3,
            },
            metadata={"geometry": IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)},
        )
        # Mock preflight_plan to return a blocker
        def mock_preflight(actions):
            return PreflightResult(
                passed=False,
                checks=(),
                blockers=(MockBlocker(action_type="boundary_condition", message="Simulated unresolvable region"),),
            )
        monkeypatch.setattr("abaqus_ai_agent.validation.preflight.preflight_plan", mock_preflight)

        res = agent.solve_requirement(intent)
        assert res.status == TaskStatus.BLOCKED
        assert any("Simulated unresolvable region" in err for err in res.errors)

    def test_p1_07_specialized_physics_domain_routing(self):
        """Verify routing and profile binding for specialized L4 domains (Fatigue, FMBD, Connectors)."""
        # 1. Fatigue Intent
        fatigue_intent = EngineeringIntent(
            id="intent-fatigue-01",
            kind="fatigue",
            description="Cyclic Loading",
            analysis_type="high_cycle_fatigue",
            unit_system="MM_N_MPA",
            fatigue=IntentFatigueSpec(
                target_cycles=1e6,
                material_curve=((300.0, 1e5), (200.0, 1e7)),
                ultimate_strength=400.0,
            ),
        )
        cap_fatigue = resolve_capability(fatigue_intent)
        assert cap_fatigue.capability_id == "high_cycle_fatigue"
        assert "fatigue_life" in cap_fatigue.profile.required_metrics
        assert "fatigue" in cap_fatigue.profile.required_gates

        # 2. FMBD Intent
        fmbd_intent = EngineeringIntent(
            id="intent-fmbd-01",
            kind="flexible_multibody",
            description="Crank Mechanism",
            analysis_type="flexible_multibody",
            unit_system="MM_N_MPA",
            fmbd=IntentFMBDSpec(
                rigid_bodies=(RigidBodySpec(name="Crank", ref_point_name="RP_Crank", point_coords=(0.0, 0.0, 0.0), body_region="CrankFace"),),
                flexible_interfaces=(),
            ),
        )
        cap_fmbd = resolve_capability(fmbd_intent)
        assert cap_fmbd.capability_id == "flexible_multibody"
        assert "joint_drift" in cap_fmbd.profile.required_metrics
        assert "fmbd_dynamics" in cap_fmbd.profile.required_gates

        # 3. Bolt Pretension Intent
        bolt_intent = EngineeringIntent(
            id="intent-bolt-01",
            kind="bolt_pretension",
            description="Preloaded Flange",
            analysis_type="bolt_pretension",
            unit_system="MM_N_MPA",
            metadata={"bolt_pretensions": [{"bolt_name": "Bolt-1", "preload_force": 5000.0}]},
        )
        cap_bolt = resolve_capability(bolt_intent)
        assert cap_bolt.capability_id == "bolt_pretension"
        assert cap_bolt.physics_domain == "multi_step"

    def test_p1_08_successful_solve_contract_and_report(self, agent, monkeypatch):
        """Mocked authentic full pass proving EngineeringTaskResult structure and report output."""
        intent = EngineeringIntent(
            id="intent-pass-01",
            kind="linear_static",
            description="Cantilever Static Pass",
            analysis_type="linear_static",
            unit_system="MM_N_MPA",
            material={
                "name": "Steel",
                "youngs_modulus": 210000.0,
                "poisson_ratio": 0.3,
            },
            metadata={"geometry": IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)},
            boundary_conditions=(IntentBoundarySpec(name="FixedRoot", bc_type="ENCASTRE", region="RootFace"),),
            loads=(IntentLoadSpec(name="TipLoad", load_type="concentrated_force", region="TipFace", magnitude=-1000.0),),
        )

        mock_run = MagicMock(spec=AnalysisRun)
        mock_run.id = "run-p1-pass-001"
        mock_run.model_name = "Model_intent_pass_01"
        mock_run.job_name = "Job_intent_pass_01"
        mock_run.state = AnalysisRunState.ACCEPTED
        mock_run.engineering_status = "RESULT_VALID"
        mock_run.acceptance_passed = True
        mock_run.metrics = (
            EngineeringMetric(name="max_mises", value=528.9, unit="MPa"),
            EngineeringMetric(name="tip_deflection", value=0.00237, unit="mm"),
        )
        mock_run.acceptance = AcceptanceResult(
            passed=True,
            criteria=(),
            status="PASS",
        )

        def mock_analysis_run(*args, **kwargs):
            return mock_run

        monkeypatch.setattr(agent, "analysis_run", mock_analysis_run)

        task_res = agent.solve_requirement(intent, submit_job=False)
        assert task_res.status == TaskStatus.COMPLETED
        assert task_res.run.state == AnalysisRunState.ACCEPTED
        assert task_res.acceptance.passed is True
        assert task_res.summary_card["status"] == "COMPLETED"
        assert task_res.summary_card["metrics"]["max_mises"] == 528.9
        assert "Engineering Analysis Report" in task_res.report_markdown

    @pytest.mark.parametrize("capability_id", ALL_L4_CAPABILITIES)
    def test_p1_09_all_20_l4_capabilities_matrix_audit(self, capability_id, agent):
        """Automated parameterized matrix audit: all 20 L4 capabilities must resolve cleanly,

        bind valid PhysicsResultProfile contracts (fields, metrics, gates), and pass through
        solve_requirement() without capability ambiguity or unhandled exceptions.
        """
        # Synthesize capability-targeted EngineeringIntent
        intent_kwargs = {
            "id": f"intent-{capability_id}",
            "kind": capability_id,
            "description": f"Automated test for capability {capability_id}",
            "analysis_type": capability_id,
            "unit_system": "MM_N_MPA",
            "material": {
                "name": "Steel",
                "youngs_modulus": 210000.0,
                "poisson_ratio": 0.3,
            },
            "metadata": {
                "geometry": IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0),
            },
            "boundary_conditions": (IntentBoundarySpec(name="FixedRoot", bc_type="ENCASTRE", region="RootFace"),),
            "loads": (IntentLoadSpec(name="Load", load_type="concentrated_force", region="TipFace", magnitude=-1000.0),),
        }

        # Specialized domain requirements
        if capability_id == "high_cycle_fatigue":
            intent_kwargs["fatigue"] = IntentFatigueSpec(
                target_cycles=1e6,
                material_curve=((300.0, 1e5), (200.0, 1e7)),
                ultimate_strength=400.0,
            )
        elif capability_id == "flexible_multibody":
            intent_kwargs["fmbd"] = IntentFMBDSpec(
                rigid_bodies=(RigidBodySpec(name="Crank", ref_point_name="RP_Crank", point_coords=(0.0, 0.0, 0.0), body_region="CrankFace"),),
                flexible_interfaces=(),
            )
        elif capability_id == "bolt_pretension":
            from abaqus_ai_agent.contracts.procedure import BoltPretensionLifecycleSpec
            intent_kwargs["metadata"]["bolt_pretensions"] = [
                BoltPretensionLifecycleSpec(name="B1", region_expression="RootFace", preload_magnitude=5000.0)
            ]
        elif capability_id == "spatial_field_loading":
            from abaqus_ai_agent.contracts.procedure import SpatialLoadField
            intent_kwargs["metadata"]["fields"] = [
                SpatialLoadField(name="Field1", expression="100.0 * X")
            ]
        elif capability_id == "multi_step_procedure":
            intent_kwargs["metadata"]["steps"] = [
                IntentStepSpec(name="Step-1", step_type="static_general"),
                IntentStepSpec(name="Step-2", step_type="static_general", previous="Step-1"),
            ]

        intent = EngineeringIntent(**intent_kwargs)

        # 1. Capability Resolution Contract
        cap = resolve_capability(intent)
        assert cap.capability_id == capability_id, f"Resolved {cap.capability_id} != expected {capability_id}"
        assert cap.status == CapabilityStatus.SUPPORTED
        assert cap.qualification_level == "L4"
        assert cap.physics_domain is not None
        assert cap.reason != ""

        # 2. PhysicsResultProfile Contract
        prof = cap.profile
        assert prof is not None
        assert len(prof.required_fields) > 0, f"Capability {capability_id} has empty required_fields"
        assert len(prof.required_metrics) > 0, f"Capability {capability_id} has empty required_metrics"
        assert len(prof.required_gates) > 0, f"Capability {capability_id} has empty required_gates"
        assert "execution" in prof.required_gates or "criteria" in prof.required_gates

        # 3. Compiler Compatibility
        plan = compile_engineering_intent(intent, submit_job=False)
        assert plan.model_name is not None
        assert len(plan.actions) > 0

        # 4. solve_requirement Capability Binding
        # With mock executor and no solver run, preflight passes and it resolves capability correctly
        res = agent.solve_requirement(intent, submit_job=False, odb_path="dummy.odb")
        assert res.capability.capability_id == capability_id
        assert res.summary_card["capability_id"] == capability_id
        assert res.summary_card["physics_domain"] == cap.physics_domain

    def test_p1_10_forbidden_internal_injection_defense(self, agent):
        """Direct injection of internal verification objects must fail closed with INJECTION_BLOCKED."""
        intent = EngineeringIntent(
            id="intent-inject-probe",
            kind="linear_static",
            description="Injection Probe",
            analysis_type="linear_static",
            unit_system="MM_N_MPA",
            material={"name": "Steel", "youngs_modulus": 210000.0, "poisson_ratio": 0.3},
            metadata={"geometry": IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)},
        )

        # Attempt to pass internal verification objects at product entry
        res = agent.solve_requirement(
            intent,
            numerical_verification={"equilibrium": 0.0},
            contact_diagnostics={"penetration": 0.0},
        )
        assert res.status == TaskStatus.BLOCKED
        assert "INJECTION_BLOCKED" == res.summary_card["status"]
        assert "numerical_verification" in res.summary_card["forbidden_keys"]
        assert "contact_diagnostics" in res.summary_card["forbidden_keys"]
        assert any("Direct injection of internal verification objects" in err for err in res.errors)

    def test_p1_11_six_state_strong_equivalence_consistency(self, agent, monkeypatch):
        """Assert strict bidirectional state equivalence across TaskResult, AnalysisRun, and Acceptance.

        TaskStatus.COMPLETED <=> run.state == ACCEPTED <=> run.acceptance_passed == True
        <=> acceptance.passed == True <=> summary_card['status'] == COMPLETED
        <=> summary_card['acceptance_passed'] == True.
        """
        intent = EngineeringIntent(
            id="intent-equiv-01",
            kind="linear_static",
            description="Equivalence Probe",
            analysis_type="linear_static",
            unit_system="MM_N_MPA",
            material={"name": "Steel", "youngs_modulus": 210000.0, "poisson_ratio": 0.3},
            metadata={"geometry": IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)},
            boundary_conditions=(IntentBoundarySpec(name="FixedRoot", bc_type="ENCASTRE", region="RootFace"),),
            loads=(IntentLoadSpec(name="Load", load_type="concentrated_force", region="TipFace", magnitude=-1000.0),),
        )

        # Case A: Fully Authentic Success
        mock_run_pass = MagicMock(spec=AnalysisRun)
        mock_run_pass.state = AnalysisRunState.ACCEPTED
        mock_run_pass.engineering_status = "RESULT_VALID"
        mock_run_pass.acceptance_passed = True
        mock_run_pass.acceptance = AcceptanceResult(passed=True, criteria=(), status="PASS")
        mock_run_pass.metrics = ()
        monkeypatch.setattr(agent, "analysis_run", lambda *a, **kw: mock_run_pass)

        res_pass = agent.solve_requirement(intent, submit_job=False)
        is_completed = (res_pass.status == TaskStatus.COMPLETED)
        assert is_completed is True
        assert (res_pass.run.state == AnalysisRunState.ACCEPTED) == is_completed
        assert (getattr(res_pass.run, "acceptance_passed", False) is True) == is_completed
        assert (res_pass.acceptance.passed is True) == is_completed
        assert (res_pass.summary_card["status"] == "COMPLETED") == is_completed
        assert (res_pass.summary_card["acceptance_passed"] is True) == is_completed

        # Case B: Desynchronized Failure (acceptance_passed False while run_state claims ACCEPTED)
        mock_run_desync = MagicMock(spec=AnalysisRun)
        mock_run_desync.state = AnalysisRunState.ACCEPTED
        mock_run_desync.engineering_status = "RESULT_INVALID"
        mock_run_desync.acceptance_passed = False
        mock_run_desync.acceptance = AcceptanceResult(passed=False, criteria=(), status="FAIL")
        mock_run_desync.metrics = ()
        monkeypatch.setattr(agent, "analysis_run", lambda *a, **kw: mock_run_desync)

        res_desync = agent.solve_requirement(intent, submit_job=False)
        is_completed_desync = (res_desync.status == TaskStatus.COMPLETED)
        assert is_completed_desync is False
        assert (res_desync.summary_card["status"] == "FAILED")
        assert (res_desync.summary_card["acceptance_passed"] is False)
        # Verify no partial green lights can leak through
        assert res_desync.status != TaskStatus.COMPLETED
