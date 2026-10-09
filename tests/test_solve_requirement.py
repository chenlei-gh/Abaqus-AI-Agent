"""Tests for P1.0: End-to-End Engineering Requirement Solver (Agent Product Main Entry)."""

import os
import pytest
from abaqus_ai_agent.agent import AbaqusAIAgent
from abaqus_ai_agent.contracts.capability import CapabilityStatus
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
from abaqus_ai_agent.contracts.task import EngineeringTaskResult, TaskStatus
from abaqus_ai_agent.execution.client import AbaqusExecutor
from abaqus_ai_agent.planning.compiler import IntentGeometrySpec


class OdbBackedExecutor(AbaqusExecutor):
    """Deterministic in-memory AbaqusExecutor simulating live ODB result extraction."""

    def __init__(self):
        self.executed_scripts = []
        self.workdir = None

    def execute(self, code, timeout=120):
        self.executed_scripts.append(code)
        if self.workdir and os.path.isdir(self.workdir):
            import re
            m = re.search(r"Job_[a-zA-Z0-9_]+", code)
            job_prefix = m.group(0) if m else "Job_REQ_E2E_STATIC"
            for ext in ("inp", "odb", "sta", "msg", "dat", "log"):
                p = os.path.join(self.workdir, f"{job_prefix}.{ext}")
                if not os.path.exists(p):
                    if ext == "odb":
                        with open(p, "wb") as f:
                            f.write(b"\x7fABAQUS_BINARY_ODB_MOCK\x00\x01\x02\x03" * 32)
                    else:
                        with open(p, "w", encoding="utf-8") as f:
                            f.write(f"Mock {ext}\n")
        if "rootAssembly" in code:
            return {"steps": ["Step-1"], "instances": ["Part-1-1"], "step_frames": {"Step-1": 1}}
        if "odb.steps.keys()" in code:
            return "Step-1"
        if "fo=" in code:
            return {"values": [{"value": 120.0}]}
        return {"status": "COMPLETED", "output": "COMPLETED"}

    def monitor_job(self, name, timeout=3600, poll_seconds=2.0):
        return {"status": "COMPLETED", "output": "COMPLETED"}

    def snapshot(self):
        return None


def test_solve_requirement_natural_language_needs_clarification():
    """Verify that ambiguous natural language prompt fails closed and asks for clarification."""
    agent = AbaqusAIAgent(OdbBackedExecutor())
    result = agent.solve_requirement("请帮我分析这个支架的受力情况")

    assert isinstance(result, EngineeringTaskResult)
    assert result.status == TaskStatus.NEEDS_CLARIFICATION
    assert result.needs_clarification is True
    assert result.is_completed is False
    assert result.clarification_prompt is not None
    assert "Missing prerequisites" in result.clarification_prompt
    assert "missing_geometry_dimensions" in result.metadata["missing_requirements"]
    assert result.summary_card["status"] == "NEEDS_CLARIFICATION"


def test_solve_requirement_unsupported_physics_fail_closed():
    """Verify that unsupported physics domains (e.g. CFD/Aerodynamics) fail closed as UNSUPPORTED."""
    agent = AbaqusAIAgent(OdbBackedExecutor())
    intent = EngineeringIntent(
        id="INTENT-CFD-01",
        kind="cfd_aerodynamics",
        description="Airfoil external aerodynamics simulation",
    )

    result = agent.solve_requirement(intent)

    assert result.status == TaskStatus.UNSUPPORTED
    assert result.capability is not None
    assert result.capability.status == CapabilityStatus.UNSUPPORTED
    assert "outside the 20 L4 verified" in result.errors[0]
    assert result.summary_card["status"] == "UNSUPPORTED"


def test_solve_requirement_missing_geometry_compilation_blocked():
    """Verify that intent missing geometry specification fails closed at compilation gate."""
    agent = AbaqusAIAgent(OdbBackedExecutor())
    intent = EngineeringIntent(
        id="INTENT-NO-GEOM",
        kind="linear_static",
        description="Cantilever without geometry",
        material={"name": "Steel", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
    )

    result = agent.solve_requirement(intent)

    assert result.status == TaskStatus.BLOCKED
    assert len(result.errors) > 0
    assert "missing geometry specification" in result.errors[0]
    assert result.summary_card["status"] == "COMPILATION_BLOCKED"


def test_solve_requirement_external_results_fail_closed_suspicious():
    """Verify RC1 rule: external injected results cannot be ACCEPTED (must be RESULT_SUSPICIOUS)."""
    agent = AbaqusAIAgent(OdbBackedExecutor())
    geom = IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0)
    mat = MaterialDefinition(
        name="Steel_Q235",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    intent = EngineeringIntent(
        id="REQ-SUSPICIOUS-CHECK",
        kind="linear_static",
        description="Cantilever with injected external results",
        material={"name": "Steel_Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3, "unit": "MPa"},
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},),
        acceptance_criteria=({"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 250.0, "unit": "MPa"},),
        metadata={"dimensions": {"shape": "cantilever_box", "length": 120.0, "width": 12.0, "height": 8.0}},
    )

    # Injected external result values without ODB backing
    result = agent.solve_requirement(
        requirement=intent,
        geometry=geom,
        material=mat,
        result_values={"max_mises": 120.0, "max_displacement": 0.4, "reaction_force": 1000.0},
    )

    # Must fail closed: cannot produce ACCEPTED from external_input
    assert result.status == TaskStatus.FAILED
    assert result.is_completed is False
    assert result.run.engineering_status == "RESULT_SUSPICIOUS"
    assert result.run.acceptance_passed is False


def test_solve_requirement_end_to_end_completed():
    """Verify complete end-to-end execution: Intent -> Capability -> Plan -> Preflight -> Runner -> Report."""
    executor = OdbBackedExecutor()
    agent = AbaqusAIAgent(executor)

    geom = IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0)
    mat = MaterialDefinition(
        name="Steel_Q235",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )

    intent = EngineeringIntent(
        id="REQ-E2E-STATIC",
        kind="linear_static",
        description="Cantilever beam under vertical 1kN tip load",
        material={
            "name": "Steel_Q235",
            "elastic_modulus": 210000.0,
            "poisson_ratio": 0.3,
            "unit": "MPa",
        },
        boundary_conditions=(
            {"type": "encastre", "region": "RootFace"},
        ),
        loads=(
            {"type": "concentrated_force", "region": "TipFace", "magnitude": 1000.0, "direction": "-Y"},
        ),
        acceptance_criteria=(
            {"name": "mises_limit", "value_key": "max_mises", "operator": "<=", "limit": 250.0, "unit": "MPa"},
        ),
        metadata={
            "dimensions": {"shape": "cantilever_box", "length": 120.0, "width": 12.0, "height": 8.0},
        },
    )

    result = agent.solve_requirement(
        requirement=intent,
        geometry=geom,
        material=mat,
    )

    # 1. Lifecycle status
    assert result.status == TaskStatus.COMPLETED
    assert result.is_completed is True

    # 2. Capability resolution
    assert result.capability is not None
    assert result.capability.capability_id == "linear_static"
    assert result.capability.physics_domain == "static"
    assert result.capability.qualification_level == "L4"

    # 3. Plan & Preflight
    assert result.plan is not None
    assert len(result.plan.actions) >= 8
    assert "EncastreBC" in result.plan.cae_script
    assert "cf2=-1000.0" in result.plan.cae_script

    # 4. Executor received actions
    assert len(executor.executed_scripts) >= len(result.plan.actions)

    # 5. AnalysisRun & Single Acceptance Outlet
    assert result.run is not None
    assert result.run.engineering_status == "RESULT_VALID"
    assert result.run.acceptance_passed is True

    # 6. Summary Card
    card = result.summary_card
    assert card["status"] == "COMPLETED"
    assert card["capability_id"] == "linear_static"
    assert card["engineering_status"] == "RESULT_VALID"
    assert card["acceptance_passed"] is True
    assert card["metrics"]["max_mises"] == 120.0

    # 7. Structured Markdown Report
    assert result.report_markdown is not None
    assert "# Engineering Analysis Report" in result.report_markdown
    assert "120.0" in result.report_markdown
    assert "Verification Dimension" in result.report_markdown


def test_solve_requirement_natural_language_completed():
    """Verify natural language requirement end-to-end: prompt -> JEV -> Plan -> Preflight -> Runner -> Report."""
    executor = OdbBackedExecutor()
    agent = AbaqusAIAgent(executor)
    prompt = (
        "对长120mm宽12mm高8mm的悬臂梁端部施加1000N垂直载荷，"
        "材料为结构钢，固定根部，校核最大Mises应力不超过250MPa。"
    )
    result = agent.solve_requirement(prompt)

    assert result.status == TaskStatus.COMPLETED
    assert result.is_completed is True
    assert result.capability.capability_id == "linear_static"
    assert result.capability.physics_domain == "static"
    assert result.plan is not None
    assert len(result.plan.actions) >= 8
    assert result.run is not None
    assert result.run.engineering_status == "RESULT_VALID"
    assert result.report_markdown is not None
    assert "# Engineering Analysis Report" in result.report_markdown
