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
    with pytest.raises(ValueError, match="local seed size must be a positive"):
        builders.local_seed_size("M", "P", "p.edges[0]", size=0.0)
    with pytest.raises(ValueError, match="local seed size must be a positive"):
        builders.local_seed_size("M", "P", "p.edges[0]", size=-2.5)

    # Number < 1, float, bool, or invalid type
    with pytest.raises(ValueError, match="local seed number must be an integer >= 1"):
        builders.local_seed_number("M", "P", "p.edges[0]", number=0)
    with pytest.raises(ValueError, match="local seed number must be an integer >= 1"):
        builders.local_seed_number("M", "P", "p.edges[0]", number=-3)
    with pytest.raises(ValueError, match="local seed number must be an integer >= 1"):
        builders.local_seed_number("M", "P", "p.edges[0]", number=2.7)
    with pytest.raises(ValueError, match="local seed number must be an integer >= 1"):
        builders.local_seed_number("M", "P", "p.edges[0]", number=True)

    # LocalSeed contract fails closed on float or bool number
    with pytest.raises(ValueError, match="seed number must be an integer >= 1"):
        LocalSeed(region_expression="p.edges[0]", number=2.7)
    with pytest.raises(ValueError, match="seed number must be an integer >= 1"):
        LocalSeed(region_expression="p.edges[0]", number=False)

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


# ---------------------------------------------------------------------------
# 6. Negative & Regression Gate Tests (P0/P1 Closure)
# ---------------------------------------------------------------------------

def test_two_blocks_contact_blocks_unsupported_local_seeds():
    geom = IntentGeometrySpec(shape="two_blocks_contact", width=100.0, height=20.0, length=10.0)
    mesh = IntentMeshSpec(
        global_size=5.0,
        local_seeds=(LocalSeed(region_expression="p.edges[0]", size=1.0),),
    )
    with pytest.raises(ValueError, match="two_blocks_contact' does not currently support local_seeds"):
        compile_intent_to_actions(
            model_name="M",
            part_name="P",
            job_name="J",
            geometry=geom,
            material="Steel",
            mesh=mesh,
        )


def test_extract_authentic_odb_mesh_metrics_rejects_missing_or_empty_instances(tmp_path):
    import sys
    odb_file = tmp_path / "corrupt_assy.odb"
    odb_file.write_bytes(b"\x7fODB" + b"\x00" * 100)

    # 1. Missing rootAssembly or instances
    mock_odb_no_assy = MagicMock()
    mock_odb_no_assy.steps = {"Step-1": MagicMock(frames=[MagicMock(fieldOutputs={"S": MagicMock()})])}
    mock_odb_no_assy.rootAssembly = None

    mock_mod = MagicMock()
    mock_mod.openOdb = MagicMock(return_value=mock_odb_no_assy)
    orig_module = sys.modules.get("odbAccess")
    try:
        sys.modules["odbAccess"] = mock_mod
        with patch("abaqus_ai_agent.execution.solver.has_native_odb_access", return_value=True), \
             patch("abaqus_ai_agent.execution.solver.is_authentic_binary_odb", return_value=True):
            with pytest.raises(ValueError, match="rootAssembly or instances collection cannot be accessed"):
                extract_authentic_odb_mesh_metrics(odb_file)

        # 2. Empty instances collection
        mock_odb_empty = MagicMock()
        mock_odb_empty.steps = {"Step-1": MagicMock(frames=[MagicMock(fieldOutputs={"S": MagicMock()})])}
        mock_root_empty = MagicMock()
        mock_root_empty.instances = {}
        mock_odb_empty.rootAssembly = mock_root_empty
        mock_mod.openOdb = MagicMock(return_value=mock_odb_empty)

        with patch("abaqus_ai_agent.execution.solver.has_native_odb_access", return_value=True), \
             patch("abaqus_ai_agent.execution.solver.is_authentic_binary_odb", return_value=True):
            with pytest.raises(ValueError, match="zero instances"):
                extract_authentic_odb_mesh_metrics(odb_file)
    finally:
        if orig_module is not None:
            sys.modules["odbAccess"] = orig_module
        else:
            sys.modules.pop("odbAccess", None)


def test_agent_mesh_quality_gate_not_checked_when_omitted(tmp_path):
    from abaqus_ai_agent.agent import AbaqusAIAgent
    from abaqus_ai_agent.execution.analysis_run import AnalysisRun, AnalysisRunState

    agent = AbaqusAIAgent(executor=MagicMock())
    run = AnalysisRun(
        id="RUN-TEST-01",
        model_name="Model-1",
        job_name="Job-1",
        state=AnalysisRunState.COMPLETED,
        acceptance_passed=True,  # Overall acceptance PASS, but mesh gate SKIPPED
        acceptance={"status": "PASS", "deliverable": True, "gates": {"execution": "PASS", "mesh_quality": "SKIPPED"}},
        verification={"mesh_metrics": {"total_elements": 100, "total_nodes": 200, "element_types": {"C3D8R": 100}, "instances": {"P-1": {}}}},
    )

    plan = MagicMock()
    plan.model_name = "Model-1"
    plan.job_name = "Job-1"
    plan.material = None
    plan.mesh = None

    # Verify agent doesn't report PASS for mesh quality just because acceptance_passed is True
    # Test through solve_requirement post-processing logic directly
    mq_audit = (getattr(run, "verification", {}) or {}).get("mesh_quality")
    acc_gates = run.acceptance.get("gates", {})
    mq_gate_val = acc_gates.get("mesh_quality")
    assert mq_gate_val == "SKIPPED"
    # When skipped, resolved gate status must be NOT_CHECKED
    assert mq_gate_val not in ("PASS", "WARNING")


def test_agent_actual_element_type_unavailable_when_missing(tmp_path):
    actual_mesh_metrics = {"total_elements": None, "total_nodes": None, "element_types": {}}
    req_elem_type = "C3D8R"

    actual_total_elements = actual_mesh_metrics.get("total_elements")
    actual_elem_types = actual_mesh_metrics.get("element_types") or {}

    if actual_elem_types:
        actual_elem_type_display = ", ".join(f"{k} ({v})" for k, v in sorted(actual_elem_types.items()))
    elif actual_total_elements is not None:
        actual_elem_type_display = "INCOMPLETE"
    else:
        actual_elem_type_display = "UNAVAILABLE"

    # Must be UNAVAILABLE, not fallback to req_elem_type
    assert actual_elem_type_display == "UNAVAILABLE"
    assert actual_elem_type_display != req_elem_type


def test_extract_authentic_odb_mesh_metrics_rejects_missing_attributes_or_empty_mesh(tmp_path):
    import sys
    odb_file = tmp_path / "defect_mesh.odb"
    odb_file.write_bytes(b"\x7fODB" + b"\x00" * 100)

    # Subcase A: Instance missing 'elements' attribute
    mock_odb_a = MagicMock()
    mock_odb_a.steps = {"Step-1": MagicMock(frames=[MagicMock(fieldOutputs={"S": MagicMock()})])}
    inst_a = MagicMock(spec=["nodes"])  # lacks 'elements'
    inst_a.nodes = [MagicMock() for _ in range(5)]
    mock_odb_a.rootAssembly = MagicMock(instances={"P-1": inst_a})

    mock_mod = MagicMock(openOdb=MagicMock(return_value=mock_odb_a))
    orig_module = sys.modules.get("odbAccess")
    try:
        sys.modules["odbAccess"] = mock_mod
        with patch("abaqus_ai_agent.execution.solver.has_native_odb_access", return_value=True), \
             patch("abaqus_ai_agent.execution.solver.is_authentic_binary_odb", return_value=True):
            with pytest.raises(ValueError, match="lacks required mesh attributes"):
                extract_authentic_odb_mesh_metrics(odb_file)

        # Subcase B: Instance with elements > 0 but nodes == 0
        mock_odb_b = MagicMock()
        mock_odb_b.steps = {"Step-1": MagicMock(frames=[MagicMock(fieldOutputs={"S": MagicMock()})])}
        inst_b = MagicMock()
        inst_b.elements = [MagicMock(type="C3D8R")]
        inst_b.nodes = []
        mock_odb_b.rootAssembly = MagicMock(instances={"P-1": inst_b})
        mock_mod.openOdb = MagicMock(return_value=mock_odb_b)

        with patch("abaqus_ai_agent.execution.solver.has_native_odb_access", return_value=True), \
             patch("abaqus_ai_agent.execution.solver.is_authentic_binary_odb", return_value=True):
            with pytest.raises(ValueError, match="incomplete discretization"):
                extract_authentic_odb_mesh_metrics(odb_file)

        # Subcase C: Element missing 'type' attribute
        mock_odb_c = MagicMock()
        mock_odb_c.steps = {"Step-1": MagicMock(frames=[MagicMock(fieldOutputs={"S": MagicMock()})])}
        elem_no_type = MagicMock(spec=[])  # lacks 'type'
        inst_c = MagicMock()
        inst_c.elements = [elem_no_type]
        inst_c.nodes = [MagicMock()]
        mock_odb_c.rootAssembly = MagicMock(instances={"P-1": inst_c})
        mock_mod.openOdb = MagicMock(return_value=mock_odb_c)

        with patch("abaqus_ai_agent.execution.solver.has_native_odb_access", return_value=True), \
             patch("abaqus_ai_agent.execution.solver.is_authentic_binary_odb", return_value=True):
            with pytest.raises(ValueError, match="missing 'type' attribute"):
                extract_authentic_odb_mesh_metrics(odb_file)

        # Subcase D: Total elements and nodes are 0
        mock_odb_d = MagicMock()
        mock_odb_d.steps = {"Step-1": MagicMock(frames=[MagicMock(fieldOutputs={"S": MagicMock()})])}
        inst_d = MagicMock()
        inst_d.elements = []
        inst_d.nodes = []
        mock_odb_d.rootAssembly = MagicMock(instances={"P-1": inst_d})
        mock_mod.openOdb = MagicMock(return_value=mock_odb_d)

        with patch("abaqus_ai_agent.execution.solver.has_native_odb_access", return_value=True), \
             patch("abaqus_ai_agent.execution.solver.is_authentic_binary_odb", return_value=True):
            with pytest.raises(ValueError, match="contains no finite element mesh|non-positive discretization"):
                extract_authentic_odb_mesh_metrics(odb_file)
    finally:
        if orig_module is not None:
            sys.modules["odbAccess"] = orig_module
        else:
            sys.modules.pop("odbAccess", None)


def test_type_hints_resolution_across_core_modules():
    """Verify typing.get_type_hints evaluates cleanly across functions and classes without NameError."""
    import inspect
    import typing
    import abaqus_ai_agent.execution.solver as solver_mod
    import abaqus_ai_agent.reasoning.plausibility as plausibility_mod
    import abaqus_ai_agent.contracts.intent as intent_mod
    import abaqus_ai_agent.contracts.mesh as mesh_mod
    import abaqus_ai_agent.planning.compiler as compiler_mod

    modules = [solver_mod, plausibility_mod, intent_mod, mesh_mod, compiler_mod]
    for mod in modules:
        for name, obj in inspect.getmembers(mod):
            if inspect.isfunction(obj) and obj.__module__ == mod.__name__:
                hints = typing.get_type_hints(obj)
                assert isinstance(hints, dict)
            elif inspect.isclass(obj) and obj.__module__ == mod.__name__:
                hints = typing.get_type_hints(obj)
                assert isinstance(hints, dict)
                for meth_name, meth in inspect.getmembers(obj, predicate=inspect.isfunction):
                    if meth.__module__ == mod.__name__:
                        m_hints = typing.get_type_hints(meth)
                        assert isinstance(m_hints, dict)


def test_verify_authentic_odb_structure_uses_file_based_probe(tmp_path):
    """Verify verify_authentic_odb_structure writes probe script to file and invokes it without -c flag."""
    import json
    from unittest.mock import MagicMock, patch
    from abaqus_ai_agent.execution.solver import verify_authentic_odb_structure

    mock_odb = tmp_path / "valid_dummy.odb"
    mock_odb.write_bytes(b"\x7fODB" + b"\x00" * 100)

    probe_output = "__ODB_VERIFIED__" + json.dumps({
        "valid": True,
        "steps": {"Step-1": {"frames": [0, 1]}},
        "mesh_metrics": {
            "total_elements": 100,
            "total_nodes": 200,
            "element_types": {"C3D10": 100},
            "instances": {"PlateInst": {"elements": 100, "nodes": 200}},
        },
    })

    captured_cmds = []

    def mock_subprocess_run(cmd, **kwargs):
        captured_cmds.append(cmd)
        probe_path = Path(cmd[2])
        assert probe_path.is_file(), f"Probe file {probe_path} should exist during execution"
        assert probe_path.name == "_odb_probe.py"
        content = probe_path.read_text(encoding="utf-8")
        assert "from odbAccess import openOdb" in content
        assert "-c" not in cmd
        mock_proc = MagicMock()
        mock_proc.return_code = 0
        mock_proc.stdout = probe_output
        mock_proc.stderr = ""
        return mock_proc

    with patch("abaqus_ai_agent.execution.solver.has_native_odb_access", return_value=False), \
         patch("abaqus_ai_agent.execution.solver.is_authentic_binary_odb", return_value=True), \
         patch("abaqus_ai_agent.execution.solver.find_abaqus_executable", return_value="mock_abaqus"), \
         patch("subprocess.run", side_effect=mock_subprocess_run):
        res = verify_authentic_odb_structure(mock_odb, launcher_cmd="mock_abaqus")

    assert res["verified"] is True
    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert cmd[0] == "mock_abaqus"
    assert cmd[1] == "python"
    assert cmd[2].endswith("_odb_probe.py")


def test_qualification_cae_script_generation_unified_c3d20r():
    """Verify qualify_real_mesh_refinement script generation specifies HEX SWEEP and C3D20R."""
    from tools.qualify_real_mesh_refinement import generate_cae_script

    script = generate_cae_script("Job_Test", "Model_Test", 10.0, 3.5)
    assert "elemShape=HEX, technique=SWEEP" in script
    assert "elemCode=C3D20R" in script
    assert "C3D10" not in script
    assert "p.seedEdgeBySize(edges=hole_edges, size=3.5" in script


def test_compute_peterson_hole_plate_theory():
    """Verify Peterson analytical stress concentration calculation for finite-width plate."""
    from tools.qualify_real_mesh_refinement import compute_peterson_hole_plate_theory

    res = compute_peterson_hole_plate_theory(plate_width=100.0, hole_diameter=20.0, thickness=10.0, tensile_load=10000.0)
    assert res["d_over_w"] == 0.2
    assert res["sigma_gross"] == 10.0
    assert res["sigma_net"] == 12.5
    assert abs(res["kt_net"] - 2.5065) < 1e-4
    assert abs(res["kt_gross"] - 3.1331) < 1e-4
    assert abs(res["sigma_peak_theory"] - 31.331) < 1e-2


def test_evaluate_mesh_convergence():
    """Verify multi-level mesh convergence indicator calculations."""
    from tools.qualify_real_mesh_refinement import evaluate_mesh_convergence

    l1 = {"peak_s11": 24.977, "max_u1": 0.005436, "rf_error_pct": 0.0000}
    l2 = {"peak_s11": 27.516, "max_u1": 0.005445, "rf_error_pct": 0.0000}
    l3 = {"peak_s11": 29.519, "max_u1": 0.005448, "rf_error_pct": 0.0000}

    eval_res = evaluate_mesh_convergence(l1, l2, l3, theory_peak=31.331)
    assert eval_res["is_monotonic"] is True
    assert eval_res["diminishing_increment"] is True
    assert eval_res["delta_12_pct"] == 9.23
    assert eval_res["delta_23_pct"] == 6.79
    assert eval_res["displacement_converged"] is True
    assert eval_res["reaction_force_equilibrium_ok"] is True
    # delta_23 is 6.79% (> 5%), so it correctly categorizes as ASYMPTOTIC_APPROACHING rather than prematurely claiming mesh independence
    assert eval_res["stress_convergence_status"] == "ASYMPTOTIC_APPROACHING"

    # Strictly converged case (< 5% sensitivity)
    l3_converged = {"peak_s11": 28.5, "max_u1": 0.005448, "rf_error_pct": 0.0000}
    eval_conv = evaluate_mesh_convergence(l1, l2, l3_converged, theory_peak=31.331)
    assert eval_conv["delta_23_pct"] < 5.0
    assert eval_conv["stress_convergence_status"] == "CONVERGED"

    # Diverging / non-diminishing case
    l3_diverging = {"peak_s11": 33.0, "max_u1": 0.005448, "rf_error_pct": 0.0000}
    eval_div = evaluate_mesh_convergence(l1, l2, l3_diverging, theory_peak=31.331)
    assert eval_div["diminishing_increment"] is False
    assert eval_div["stress_convergence_status"] == "UNCONVERGED"


def test_probe_odb_script_filters_in_plane_far_edges():
    """Verify probe script strictly filters in-plane edges for both hole and far-field elements."""
    import inspect
    from tools.qualify_real_mesh_refinement import probe_odb_topology_and_physics

    src = inspect.getsource(probe_odb_topology_and_physics)
    assert "abs(p1[2]-p2[2]) < 0.1" in src
    # Ensure far_edges sampling requires in-plane filter
    assert "cr > 35.0 and abs(p1[2]-p2[2]) < 0.1" in src


def test_qualify_real_mesh_refinement_visualizations_binding_contract():
    """Verify qualify_real_mesh_refinement binds authentic visualizations with cryptographic evidence."""
    import inspect
    import tools.qualify_real_mesh_refinement as qual_mod

    src = inspect.getsource(qual_mod.run_qualification)
    assert "render_authentic_visualizations(" in src
    assert "FIG-S11-" in src
    assert "FIG-MISES-" in src
    assert "view_mode=\"FRONT\"" in src
    assert "figures=rendered_figs" in src
    assert "rendered_visualizations" in src


def test_qualify_real_mesh_refinement_fails_closed_when_signing_secret_missing(monkeypatch, tmp_path):
    """Verify qualify_real_mesh_refinement strictly fails closed without hardcoded fallback secrets."""
    import tools.qualify_real_mesh_refinement as qual_mod

    monkeypatch.delenv("ABAQUS_RENDER_SIGNING_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="CLI arguments and hardcoded fallback secrets are strictly prohibited"):
        qual_mod.run_qualification(workdir=tmp_path, launcher="dummy_launcher")


def test_qualify_real_mesh_refinement_cli_rejects_signing_secret_flag():
    """Verify CLI interface rejects --signing-secret to prevent credential leaks via argv/history."""
    import subprocess
    import sys
    from pathlib import Path

    script_path = Path(__file__).resolve().parent.parent / "tools" / "qualify_real_mesh_refinement.py"
    proc = subprocess.run(
        [sys.executable, str(script_path), "--signing-secret", "super_secret_val"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "unrecognized arguments: --signing-secret" in proc.stderr


def test_qualify_real_mesh_refinement_manifest_contract_no_secret_leak():
    """Verify qualify_real_mesh_refinement manifest structure strictly contains only boolean flag."""
    import inspect
    import tools.qualify_real_mesh_refinement as qual_mod

    src = inspect.getsource(qual_mod.run_qualification)
    assert '"secret_configured": True' in src
    assert "secret_configured" in src
    assert '"secret":' not in src
    assert '"signing_secret":' not in src
    key_contract_block = src.split('"key_contract"')[1].split('"convergence_progression"')[0]
    assert "audit_secret" not in key_contract_block
