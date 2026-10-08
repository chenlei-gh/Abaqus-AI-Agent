"""Unit Tests and Empirical A/B Qualification for P0-2 Dynamic Tool Router.

Validates:
1. Tool Registry contract completeness (id, capability, phase, risk, schemas, dependencies).
2. Capability-based dynamic selection & automatic dependency closure.
3. Schema token minimization vs full static dumping.
4. Telemetry audit compliance (tools_available, tools_selected, schema_tokens).
5. A/B Comparative Qualification:
   - A: Static Tool Schema (all registered tools sent on every phase)
   - B: Dynamic Tool Router (phase & capability-scoped minimal toolset)
   - Verifies: 0 necessary tools omitted, 0 high-risk tools leaked, massive token savings.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.telemetry.contracts import EngineeringPhase
from abaqus_ai_agent.telemetry.tracker import _heuristic_count_tokens
from abaqus_ai_agent.tools.registry import (
    RiskLevel,
    ToolMetadata,
    ToolRegistry,
    build_default_cae_tool_registry,
)
from abaqus_ai_agent.tools.router import DynamicToolRouter


def test_tool_registry_registration_and_query():
    """Verify registry stores, indexes, and retrieves tool metadata correctly."""
    reg = ToolRegistry()
    tool = ToolMetadata(
        tool_id="test_tool_1",
        name="test_tool",
        capability="test_cap",
        phase=EngineeringPhase.PLANNING,
        risk_level=RiskLevel.LOW,
        description="A test tool",
        input_schema={"type": "object"},
        output_contract="TestContract",
        dependencies=("dep_1",),
        physics_domains=("structural",),
    )
    reg.register(tool)

    assert reg.get("test_tool_1") == tool
    assert reg.get_by_name("test_tool") == tool
    assert reg.get_by_capability("test_cap") == [tool]
    assert reg.get_by_phase(EngineeringPhase.PLANNING) == [tool]
    assert reg.count() == 1

    # Duplicate registration must fail
    with pytest.raises(ValueError, match="already registered"):
        reg.register(tool)


def test_automatic_dependency_resolution():
    """Verify that selecting a downstream tool automatically resolves its dependencies."""
    reg = ToolRegistry()

    t_ingest = ToolMetadata(
        tool_id="t_ingest",
        name="ingest_cad",
        capability="cad_ingest",
        phase=EngineeringPhase.INTENT,
        risk_level=RiskLevel.READ_ONLY,
        description="Ingests CAD",
        input_schema={},
        output_contract="BRep",
    )
    t_ground = ToolMetadata(
        tool_id="t_ground",
        name="ground_region",
        capability="grounding",
        phase=EngineeringPhase.PLANNING,
        risk_level=RiskLevel.READ_ONLY,
        description="Grounds region",
        input_schema={},
        output_contract="Region",
        dependencies=("t_ingest",),
    )
    t_bc = ToolMetadata(
        tool_id="t_bc",
        name="apply_bc",
        capability="load_apply",
        phase=EngineeringPhase.PLANNING,
        risk_level=RiskLevel.LOW,
        description="Applies BC",
        input_schema={},
        output_contract="BCAction",
        dependencies=("t_ground",),
    )

    reg.register(t_ingest)
    reg.register(t_ground)
    reg.register(t_bc)

    router = DynamicToolRouter(reg)
    # Request ONLY "load_apply" capability
    result = router.resolve_tools(
        phase=EngineeringPhase.PLANNING,
        required_capabilities=["load_apply"],
    )

    # Must resolve t_bc AND its recursive dependencies t_ground AND t_ingest
    selected_ids = {t.tool_id for t in result.selected_tools}
    assert "t_bc" in selected_ids
    assert "t_ground" in selected_ids
    assert "t_ingest" in selected_ids
    assert len(result.selected_tools) == 3


def test_dynamic_router_phase_scoping_and_minimization():
    """Verify router selects minimal tools per phase from default CAE registry."""
    router = DynamicToolRouter()
    reg = router.registry
    total_tools = reg.count()
    assert total_tools >= 15

    # 1. Verification Phase
    res_verify = router.resolve_tools(phase=EngineeringPhase.VERIFICATION)
    tool_names = res_verify.get_tool_names()

    # Must contain verification capabilities
    assert "query_result_hotspots" in tool_names
    assert "evaluate_deterministic_acceptance" in tool_names
    # Must NOT leak heavy execution or planning tools
    assert "submit_abaqus_job" not in tool_names
    assert "mesh_part_assembly" not in tool_names
    assert "create_static_general_step" not in tool_names

    # Must produce minimal telemetry
    telem = res_verify.to_telemetry_dict()
    assert telem["tools_available"] == total_tools
    assert telem["tools_selected"] == len(res_verify.selected_tools)
    assert telem["tools_selected"] < total_tools
    assert telem["schema_tokens"] < 1200


def test_ab_qualification_static_vs_dynamic(tmp_path: Path):
    """Rigorous A/B qualification: Static Schema vs Dynamic Router.

    Compares across all 5 engineering lifecycle phases:
    - Schema token savings
    - Tool count reduction
    - Zero omission of necessary tools
    - Zero pollution of high-risk tools into read-only phases
    """
    router = DynamicToolRouter()
    reg = router.registry
    all_tools = reg.list_all()
    static_full_schemas = [t.to_openai_schema(minimal=False) for t in all_tools]
    static_schema_tokens = _heuristic_count_tokens(json.dumps(static_full_schemas))

    phases = [
        (EngineeringPhase.INTENT, {"ingest_cad_brep", "inspect_geometry_health"}, {"submit_abaqus_job"}),
        (EngineeringPhase.PLANNING, {"ground_semantic_region", "define_linear_elastic_material"}, {"submit_abaqus_job"}),
        (EngineeringPhase.EXECUTION, {"mesh_part_assembly", "submit_abaqus_job"}, {"render_engineering_report"}),
        (EngineeringPhase.VERIFICATION, {"query_result_hotspots", "evaluate_deterministic_acceptance"}, {"submit_abaqus_job", "mesh_part_assembly"}),
        (EngineeringPhase.REPORTING, {"render_engineering_report"}, {"submit_abaqus_job"}),
    ]

    ab_report = {
        "static_tools_count": len(all_tools),
        "static_schema_tokens": static_schema_tokens,
        "phases_comparison": [],
    }

    tot_static_tokens = 0
    tot_dynamic_tokens = 0

    for phase, required_tools, forbidden_tools in phases:
        dynamic_res = router.resolve_tools(phase=phase)
        dyn_names = dynamic_res.get_tool_names()

        # Qualification Check 1: Zero omission of required tools
        for req in required_tools:
            assert req in dyn_names, f"Phase {phase.value} dynamically omitted required tool '{req}'!"

        # Qualification Check 2: Zero leakage of forbidden/risky tools
        for forb in forbidden_tools:
            assert forb not in dyn_names, f"Phase {phase.value} leaked high-risk/irrelevant tool '{forb}'!"

        # Token metrics
        dyn_tokens = dynamic_res.schema_tokens
        token_reduction = (static_schema_tokens - dyn_tokens) / static_schema_tokens * 100.0

        tot_static_tokens += static_schema_tokens
        tot_dynamic_tokens += dyn_tokens

        ab_report["phases_comparison"].append({
            "phase": phase.value,
            "static_tools": len(all_tools),
            "static_tokens": static_schema_tokens,
            "dynamic_tools": dynamic_res.tools_selected_count,
            "dynamic_tokens": dyn_tokens,
            "token_reduction_pct": round(token_reduction, 1),
            "required_tools_satisfied": list(required_tools),
            "forbidden_tools_blocked": list(forbidden_tools),
        })

    cumulative_reduction = (tot_static_tokens - tot_dynamic_tokens) / tot_static_tokens * 100.0
    ab_report["cumulative_static_tokens"] = tot_static_tokens
    ab_report["cumulative_dynamic_tokens"] = tot_dynamic_tokens
    ab_report["cumulative_reduction_pct"] = round(cumulative_reduction, 1)

    # Overall reduction must exceed 65%
    assert cumulative_reduction > 65.0, f"Expected >65% schema token reduction, got {cumulative_reduction:.1f}%"

    # Persist A/B qualification evidence
    evidence_file = tmp_path / "ab_tool_routing_evidence.json"
    evidence_file.write_text(json.dumps(ab_report, indent=2), encoding="utf-8")
    assert evidence_file.exists()
