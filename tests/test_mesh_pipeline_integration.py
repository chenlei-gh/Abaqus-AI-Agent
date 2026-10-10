"""Comprehensive test suite for grounded mesh strategy, local seeding, and ODB evidence pipeline."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from abaqus_ai_agent.actions import builders
from abaqus_ai_agent.actions.script import action_to_script
from abaqus_ai_agent.contracts.action import AbaqusAction
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.mesh import LocalSeed, MeshSpecification
from abaqus_ai_agent.contracts.mesh_strategy import GeometryMeshPlan, MeshRefinementRequest
from abaqus_ai_agent.execution.solver import extract_authentic_odb_mesh_metrics
from abaqus_ai_agent.planning.compiler import (
    IntentGeometrySpec,
    IntentMeshSpec,
    compile_engineering_intent,
    compile_intent_to_actions,
)
from abaqus_ai_agent.planning.mesh_strategy import (
    local_seeds_from_geometry_plan,
    mesh_specification_from_geometry_plan,
    plan_geometry_mesh,
)
from abaqus_ai_agent.reporting.pipeline import DeterministicReportPipeline
from abaqus_ai_agent.reporting.renderer import render_markdown, render_html


# ---------------------------------------------------------------------------
# 1. Builders validation & script generation
# ---------------------------------------------------------------------------

def test_local_seed_builders_valid_script():
    act_size = builders.local_seed_size(
        model="Model-1",
        part="Part-1",
        region_expression="p.edges[0:1]",
        size=1.25,
        constraint="FIXED",
    )
    script_size = action_to_script(act_size)
    assert "seedEdgeBySize" in script_size
    assert "edges=p.edges[0:1]" in script_size
    assert "size=1.25" in script_size
    assert "constraint=FIXED" in script_size

    act_num = builders.local_seed_number(
        model="Model-1",
        part="Part-1",
        region_expression="p.edges[2:3]",
        number=10,
        constraint="FREE",
    )
    script_num = action_to_script(act_num)
    assert "seedEdgeByNumber" in script_num
    assert "edges=p.edges[2:3]" in script_num
    assert "number=10" in script_num
    assert "constraint=FREE" in script_num


def test_local_seed_builders_fail_closed_validation():
    # Negative / zero size
    with pytest.raises(ValueError, match="local seed size must be positive"):
        builders.local_seed_size("M", "P", "p.edges[0]", size=0.0)
    with pytest.raises(ValueError, match="local seed size must be positive"):
        builders.local_seed_size("M", "P", "p.edges[0]", size=-2.5)

    # Number < 1
    with pytest.raises(ValueError, match="local seed number must be at least 1"):
        builders.local_seed_number("M", "P", "p.edges[0]", number=0)
    with pytest.raises(ValueError, match="local seed number must be at least 1"):
        builders.local_seed_number("M", "P", "p.edges[0]", number=-3)

    # Invalid constraint
    with pytest.raises(ValueError, match="local seed constraint must be FREE, FIXED, or FINISH"):
        builders.local_seed_size("M", "P", "p.edges[0]", size=1.0, constraint="INVALID")

    # Empty region expression
    with pytest.raises(ValueError, match="region_expression is required"):
        builders.local_seed_size("M", "P", "", size=1.0)


# ---------------------------------------------------------------------------
# 2. IntentMeshSpec contract & priority handling
# ---------------------------------------------------------------------------

def test_intent_mesh_spec_fail_closed():
    with pytest.raises(ValueError, match="global_size must be positive"):
        IntentMeshSpec(global_size=0.0)
    with pytest.raises(ValueError, match="global_size must be positive"):
        IntentMeshSpec(global_size=-1.0)
    with pytest.raises(ValueError, match="deviation_factor must be in"):
        IntentMeshSpec(deviation_factor=1.5)
    with pytest.raises(ValueError, match="element_library must be STANDARD or EXPLICIT"):
        IntentMeshSpec(element_library="OTHER")


def test_intent_mesh_spec_normalizes_local_seeds():
    spec = IntentMeshSpec(
        global_size=5.0,
        local_seeds=[
            {"region_expression": "p.edges[0]", "size": 1.0, "constraint": "FREE"},
            LocalSeed(region_expression="p.edges[1]", number=5),
        ],
    )
    assert len(spec.local_seeds) == 2
    assert isinstance(spec.local_seeds[0], LocalSeed)
    assert spec.local_seeds[0].size == 1.0
    assert spec.local_seeds[1].number == 5


def test_compile_intent_to_actions_integrates_local_seeds():
    geom = IntentGeometrySpec(shape="cantilever_box", width=20.0, height=20.0, length=100.0)
    mesh = IntentMeshSpec(
        global_size=4.0,
        local_seeds=(
            LocalSeed(region_expression="p.edges[0]", size=1.0, constraint="FIXED"),
            LocalSeed(region_expression="p.edges[1]", number=8, constraint="FREE"),
        ),
    )
    plan = compile_intent_to_actions(
        model_name="M",
        part_name="P",
        job_name="J",
        geometry=geom,
        material="Steel",
        mesh=mesh,
    )
    act_types = [a.action_type for a in plan.actions]
    assert "seed_part" in act_types
    assert "local_seed_size" in act_types
    assert "local_seed_number" in act_types
    # Verify sequence: seed_part occurs before local_seed_*
    idx_seed = act_types.index("seed_part")
    idx_local_size = act_types.index("local_seed_size")
    idx_local_num = act_types.index("local_seed_number")
    assert idx_seed < idx_local_size
    assert idx_seed < idx_local_num


# ---------------------------------------------------------------------------
# 3. Fail-Closed on Unpartitioned Refinements
# ---------------------------------------------------------------------------

def test_local_seeds_from_geometry_plan_strict_mode():
    plan = plan_geometry_mesh(
        {"faces": [], "edges": []},
        global_size=10.0,
        critical_regions=(
            {"target": "faces[0]", "entity_type": "Face", "target_size": 2.0},
        ),
    )
    # Default non-strict returns empty tuple for compatibility
    assert local_seeds_from_geometry_plan(plan, fail_on_unsupported=False) == ()

    # Strict mode raises ValueError
    with pytest.raises(ValueError, match="requires geometric partitioning"):
        local_seeds_from_geometry_plan(plan, fail_on_unsupported=True)

    with pytest.raises(ValueError, match="requires geometric partitioning"):
        mesh_specification_from_geometry_plan("P", plan, fail_on_unsupported=True)


def test_compile_engineering_intent_blocks_unpartitioned_plan():
    plan = plan_geometry_mesh(
        {"faces": [], "edges": []},
        global_size=10.0,
        critical_regions=(
            {"target": "faces[1]", "entity_type": "Face", "target_size": 2.0},
        ),
    )
    intent = EngineeringIntent(
        id="INT-BLOCK-01",
        kind="stress_analysis",
        description="Block unpartitioned refinement",
        material="Steel",
        metadata={
            "geometry": {"shape": "cantilever_box", "length": 100.0, "width": 10.0, "height": 10.0},
            "geometry_mesh_plan": plan,
        },
    )
    with pytest.raises(ValueError, match="requires unexecuted geometric partitioning"):
        compile_engineering_intent(intent)


def test_compile_engineering_intent_accepts_mesh_specification():
    ms = MeshSpecification(
        part="P",
        global_size=3.5,
        local_seeds=(LocalSeed(region_expression="p.edges[0]", size=1.0),),
    )
    intent = EngineeringIntent(
        id="INT-MS-01",
        kind="stress_analysis",
        description="Test MeshSpecification input",
        material="Steel",
        mesh_requirements=ms,
        metadata={"geometry": {"shape": "cantilever_box", "length": 100.0, "width": 10.0, "height": 10.0}},
    )
    compiled = compile_engineering_intent(intent)
    act_types = [a.action_type for a in compiled.actions]
    assert "local_seed_size" in act_types


# ---------------------------------------------------------------------------
# 4. Authentic ODB mesh metrics extraction
# ---------------------------------------------------------------------------

def test_extract_authentic_odb_mesh_metrics_nonexistent(tmp_path):
    non_existent = tmp_path / "missing.odb"
    with pytest.raises(FileNotFoundError):
        extract_authentic_odb_mesh_metrics(non_existent)


def test_extract_authentic_odb_mesh_metrics_mock_binary(tmp_path):
    mock_file = tmp_path / "mock.odb"
    mock_file.write_text("plain text not binary")
    with pytest.raises(ValueError, match="failed binary pre-filter"):
        extract_authentic_odb_mesh_metrics(mock_file)


def test_extract_authentic_odb_mesh_metrics_in_process_success(tmp_path):
    import sys
    odb_file = tmp_path / "test.odb"
    # Write valid binary header
    odb_file.write_bytes(b"\x7fODB" + b"\x00" * 100)

    # Mock in-process openOdb
    mock_odb = MagicMock()
    mock_odb.steps = {"Step-1": MagicMock(frames=[MagicMock(fieldOutputs={"S": MagicMock()})])}

    mock_inst = MagicMock()
    elem1 = MagicMock(type="C3D8R")
    elem2 = MagicMock(type="C3D8R")
    elem3 = MagicMock(type="C3D10")
    mock_inst.elements = [elem1, elem2, elem3]
    mock_inst.nodes = [MagicMock() for _ in range(12)]

    mock_root = MagicMock()
    mock_root.instances = {"Part-1-1": mock_inst}
    mock_odb.rootAssembly = mock_root

    mock_odb_module = MagicMock()
    mock_odb_module.openOdb = MagicMock(return_value=mock_odb)

    orig_module = sys.modules.get("odbAccess")
    try:
        sys.modules["odbAccess"] = mock_odb_module
        with patch("abaqus_ai_agent.execution.solver.has_native_odb_access", return_value=True), \
             patch("abaqus_ai_agent.execution.solver.is_authentic_binary_odb", return_value=True):
            metrics = extract_authentic_odb_mesh_metrics(odb_file)
            assert metrics["total_elements"] == 3
            assert metrics["total_nodes"] == 12
            assert metrics["element_types"] == {"C3D8R": 2, "C3D10": 1}
            assert "Part-1-1" in metrics["instances"]
    finally:
        if orig_module is not None:
            sys.modules["odbAccess"] = orig_module
        else:
            sys.modules.pop("odbAccess", None)


# ---------------------------------------------------------------------------
# 5. Report Section 7 Discretization Rendering
# ---------------------------------------------------------------------------

def test_report_pipeline_populates_section_7(tmp_path):
    pipeline = DeterministicReportPipeline()
    mesh_info = {
        "discretization": {
            "seed_size": 2.5,
            "total_elements": 1540,
            "total_nodes": 2180,
            "element_type": "C3D8R (1540)",
            "strategy": "局部种子约束 (Local Edge Refinement)",
            "local_refinements": 2,
        },
        "quality_audit": {
            "minimum_jacobian_ratio": 0.88,
            "maximum_aspect_ratio": 2.15,
            "severely_distorted_elements": 0,
        },
        "total_elements": 1540,
        "total_nodes": 2180,
        "element_type": "C3D8R",
        "seed_size": 2.5,
    }

    _, _, report_data = pipeline.build_and_render(
        output_dir=tmp_path,
        title="Mesh Qualification Report",
        case_id="Case-Mesh-1",
        run_id="RUN-MESH-001",
        model_info={"name": "Model-Mesh"},
        results_info=(),
        acceptance_info={"status": "PASS", "deliverable": True},
        mesh_info=mesh_info,
        require_deliverable=False,
    )

    assert report_data.mesh == mesh_info
    md = render_markdown(report_data)
    html = render_html(report_data)

    # Verify Section 7 contains authentic metrics
    assert "7. Mesh" in md
    assert "1540" in md
    assert "2180" in md
    assert "C3D8R" in md
    assert "7. Mesh" in html
    assert "1540" in html
    assert "2180" in html
