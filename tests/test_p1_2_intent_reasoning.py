"""Tests for P1.2 Intent Reasoning, Engineering Plausibility & Tiered HITL."""

import pytest
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.intent_reasoning import (
    InferenceRiskLevel,
    PlausibilitySeverity,
    ReasoningStatus,
)
from abaqus_ai_agent.contracts.task import TaskStatus
from abaqus_ai_agent.planning.compiler import IntentGeometrySpec, IntentMeshSpec
from abaqus_ai_agent.reasoning.engine import IntentReasoningEngine
from abaqus_ai_agent.reasoning.material_catalog import (
    STANDARD_MATERIALS,
    match_engineering_material,
)
from abaqus_ai_agent.reasoning.mesh_inference import infer_mesh_specification
from abaqus_ai_agent.reasoning.plausibility import audit_engineering_plausibility


# =====================================================================
# 1. Material Catalog & Common-Sense Reasoning Tests
# =====================================================================

def test_material_catalog_coverage():
    """Verify common engineering materials are present in catalog."""
    names = {m.canonical_name for m in STANDARD_MATERIALS}
    assert "Q235" in names
    assert "Q345" in names
    assert "Stainless_Steel_304" in names
    assert "Aluminum_6061_T6" in names
    assert "Titanium_TC4" in names
    assert "PA66" in names
    assert "Rubber" in names


@pytest.mark.parametrize(
    "query,expected_name,expected_e,expected_yield",
    [
        ("Q235", "Q235", 210000.0, 235.0),
        ("q235b", "Q235", 210000.0, 235.0),
        ("304不锈钢", "Stainless_Steel_304", 193000.0, 205.0),
        ("AL6061-T6", "Aluminum_6061_T6", 68900.0, 276.0),
        ("TC4", "Titanium_TC4", 113800.0, 880.0),
        ("45#", "Steel_45", 210000.0, 355.0),
        ("尼龙66", "PA66", 2800.0, 80.0),
    ],
)
def test_material_alias_matching(query, expected_name, expected_e, expected_yield):
    mat_dict, inf = match_engineering_material(query)
    assert mat_dict is not None
    assert mat_dict["name"] == expected_name
    assert mat_dict["elastic_modulus"] == expected_e
    assert mat_dict["yield_strength"] == expected_yield
    assert inf is not None
    assert inf.risk_level == InferenceRiskLevel.LOW


def test_material_unknown_fails_safely():
    mat_dict, inf = match_engineering_material("Unknown_Fictional_Metal_999")
    assert mat_dict is None
    assert inf is None


# =====================================================================
# 2. Geometric & Physics-Driven Mesh Inference Tests
# =====================================================================

def test_mesh_inference_from_bounding_box():
    intent = EngineeringIntent(
        id="T1", kind="linear_static", analysis_type="linear_static",
        description="Bracket",
    )
    # Bounding dimensions: 100 x 50 x 10 mm (smallest is 10mm)
    geom = {"box": [100.0, 50.0, 10.0]}
    spec, inf = infer_mesh_specification(intent, geometry=geom)
    assert spec is not None
    # h should be ~ 10 / 8 = 1.25 mm, bounded above 0.5 mm
    assert 1.0 <= spec.global_size <= 2.0
    assert spec.element_type == "C3D8R"
    assert inf is not None
    assert inf.risk_level == InferenceRiskLevel.MEDIUM
    assert "Derived global mesh size" in inf.rationale


def test_mesh_inference_large_scale_refuses_dumb_2_5mm():
    intent = EngineeringIntent(
        id="T2", kind="linear_static", analysis_type="linear_static",
        description="Large Bridge Girder",
    )
    # Bounding dimensions: 20000 x 2000 x 500 mm (smallest is 500mm)
    geom = {"box": [20000.0, 2000.0, 500.0]}
    spec, inf = infer_mesh_specification(intent, geometry=geom)
    # Should scale with dimensions instead of hardcoding 2.5mm
    assert spec.global_size > 20.0
    assert inf is not None


def test_mesh_inference_selects_c3d8i_for_contact():
    intent = EngineeringIntent(
        id="T3", kind="contact", analysis_type="contact",
        description="Contact pair assembly",
        contacts=({"master": "SurfaceA", "slave": "SurfaceB"},),
    )
    geom = {"box": [100.0, 50.0, 20.0]}
    spec, inf = infer_mesh_specification(intent, geometry=geom)
    assert spec.element_type == "C3D8I"
    assert "C3D8I" in inf.rationale


# =====================================================================
# 3. Engineering Plausibility & Physical Consistency Checks
# =====================================================================

def test_rigid_body_constraint_check_fails_on_zero_bcs():
    intent = EngineeringIntent(
        id="T4", kind="linear_static", analysis_type="linear_static",
        description="Free floating beam with force",
        boundary_conditions=(),  # Zero constraints!
        loads=({"type": "concentrated_force", "magnitude": 1000.0, "region": "Tip"},),
    )
    checks = audit_engineering_plausibility(intent)
    rb_check = next(c for c in checks if c.check_name == "rigid_body_constraint_check")
    assert not rb_check.passed
    assert rb_check.severity == PlausibilitySeverity.CRITICAL
    assert "ZERO boundary constraints" in rb_check.message


def test_grossly_unphysical_load_magnitude_flagged():
    intent = EngineeringIntent(
        id="T5", kind="linear_static", analysis_type="linear_static",
        description="Tensile bar with astronomical load",
        boundary_conditions=({"type": "encastre", "region": "Base"},),
        # 10^8 N on a 1000 mm2 area -> 100,000 MPa (exceeds Q235 235MPa by > 400x)
        loads=({"type": "concentrated_force", "magnitude": 100_000_000.0, "region": "Tip"},),
    )
    mat = {"name": "Q235", "yield_strength": 235.0}
    checks = audit_engineering_plausibility(intent, material=mat)
    stress_check = next(c for c in checks if c.check_name == "stress_magnitude_plausibility")
    assert not stress_check.passed
    assert stress_check.severity == PlausibilitySeverity.CRITICAL
    assert "exceeds 100x material yield strength" in stress_check.message


def test_unit_system_consistency_flags_si_pascal_in_mm_model():
    intent = EngineeringIntent(
        id="T6", kind="linear_static", analysis_type="linear_static",
        description="Model in MM_N_MPA with Youngs modulus in Pa",
        unit_system="MM_N_MPA",
        boundary_conditions=({"type": "encastre", "region": "Base"},),
        loads=({"type": "concentrated_force", "magnitude": 1000.0, "region": "Tip"},),
    )
    # Young's modulus 2.1e11 (Pa) in an MM_N_MPA model
    mat = {"name": "Steel", "elastic_modulus": 2.1e11}
    checks = audit_engineering_plausibility(intent, material=mat)
    unit_check = next(c for c in checks if c.check_name == "unit_system_consistency")
    assert not unit_check.passed
    assert unit_check.severity == PlausibilitySeverity.CRITICAL
    assert "resembles Pascals (SI)" in unit_check.message


# =====================================================================
# 4. Intent Reasoning Engine Orchestration & HITL Governance Tests
# =====================================================================

def test_engine_assists_incomplete_intent_safely():
    """Valid problem with missing mesh and simplified material string -> ASSISTED."""
    intent = EngineeringIntent(
        id="T7", kind="linear_static", analysis_type="linear_static",
        description="Analyze bracket",
        material=None,  # Not given in intent
        boundary_conditions=({"type": "encastre", "region": "FixedFace"},),
        loads=({"type": "concentrated_force", "magnitude": 5000.0, "region": "TipFace"},),
        metadata={"dimensions": [{"value": 100.0, "unit": "mm"}, {"value": 20.0, "unit": "mm"}]},
    )
    result = IntentReasoningEngine.reason(
        intent=intent,
        material="Q235B",  # Provided as string query
        geometry={"box": [100.0, 50.0, 20.0]},
    )
    assert result.is_executable
    assert result.status == ReasoningStatus.ASSISTED
    assert result.inferred_material is not None
    assert result.inferred_material["name"] == "Q235"
    assert result.inferred_mesh is not None
    assert len(result.inferences) >= 2


def test_engine_blocks_rigid_body_mode():
    """Unconstrained model must be BLOCKED with clear engineering prompt."""
    intent = EngineeringIntent(
        id="T8", kind="linear_static", analysis_type="linear_static",
        description="Unconstrained beam",
        material="Structural_Steel",
        boundary_conditions=(),  # BLOCKED!
        loads=({"type": "concentrated_force", "magnitude": 500.0, "region": "Top"},),
    )
    result = IntentReasoningEngine.reason(intent=intent)
    assert not result.is_executable
    assert result.status == ReasoningStatus.BLOCKED
    assert any("rigid_body_constraint_check" in b for b in result.blockers)
    assert result.clarification_prompt is not None


# =====================================================================
# 5. Product Entry (solve_requirement) End-to-End Governance Tests
# =====================================================================

from abaqus_ai_agent.execution.client import AbaqusExecutor

class MockExecutor(AbaqusExecutor):
    def __init__(self):
        self.executed_commands = []

    def execute(self, code, timeout=120):
        self.executed_commands.append(code)
        if "mdb.jobs[" in code and "status" in code:
            return "COMPLETED"
        return {"status": "completed"}

    def inspect_odb(self, path):
        return {"status": "available", "steps": ["Step-1"]}


def test_solve_requirement_blocks_unconstrained_rigid_body():
    """solve_requirement must fail-closed before any solver dispatch if rigid body mode exists."""
    from abaqus_ai_agent.agent import AbaqusAIAgent

    agent = AbaqusAIAgent(executor=MockExecutor())

    # Intent with zero boundary conditions
    intent = EngineeringIntent(
        id="UNCONSTRAINED",
        kind="linear_static",
        analysis_type="linear_static",
        description="No constraint test",
        boundary_conditions=(),
        loads=({"type": "concentrated_force", "magnitude": 1000.0, "region": "Tip"},),
        material={"name": "Steel", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        metadata={"geometry": {"shape": "cantilever_box", "length": 100.0, "width": 10.0, "height": 10.0}},
    )

    res = agent.solve_requirement(intent, submit_job=False)
    assert res.status == TaskStatus.BLOCKED
    assert "rigid_body_constraint_check" in res.errors or any("rigid_body" in b for b in res.errors)
    assert res.summary_card.get("status") == "BLOCKED"


def test_solve_requirement_enriches_and_solves_assisted_requirement(monkeypatch):
    """solve_requirement seamlessly enriches geometry-based mesh and material query."""
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState
    from abaqus_ai_agent.acceptance import AcceptanceResult

    agent = AbaqusAIAgent(executor=MockExecutor())

    # Mock analysis_run to return valid mock run
    mock_run = AnalysisRun(
        id="RUN-P1-2",
        model_name="Model_TEST",
        job_name="Job_TEST",
        state=AnalysisRunState.ACCEPTED,
        engineering_status="ACCEPTED",
        acceptance_passed=True,
        acceptance=AcceptanceResult(passed=True, criteria=()),
        metrics=(),
    )
    monkeypatch.setattr(agent, "analysis_run", lambda *args, **kwargs: mock_run)

    prompt = "分析长宽高100x20x10mm的Q235钢悬臂梁，根部完全固定，自由端施加1000N向下的集中力，最大Mises应力小于200MPa"
    res = agent.solve_requirement(
        prompt,
        submit_job=False,
        geometry={"box": [100.0, 20.0, 10.0]},
    )
    # The requirement should pass through reasoning, enrich mesh, compile, and execute
    assert res.summary_card is not None
    assert "reasoning_status" in res.summary_card
    assert res.summary_card["reasoning_status"] in ("RESOLVED", "ASSISTED")
    assert len(res.summary_card.get("inferences", [])) >= 1
