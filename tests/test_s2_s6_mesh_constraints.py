"""S2-S6: local constraints are recorded, not treated as verified mesh evidence."""

import pytest

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.mesh import LocalSeed
from abaqus_ai_agent.planning.compiler import (
    IntentGeometrySpec,
    IntentMeshSpec,
    IntentStepSpec,
    compile_engineering_intent,
    compile_intent_to_actions,
)
from abaqus_ai_agent.reasoning.mesh_inference import (
    MeshConstraintBlocked,
    adaptive_remeshing_capability,
    decide_mesh_sizing,
)


def _intent(**metadata):
    return EngineeringIntent(
        id="S2-S6",
        kind="linear_static",
        description="Mesh constraint decision",
        material={"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        metadata=metadata,
    )


def _mesh_script(plan):
    return "\n".join(
        action.parameters.get("code", "")
        for action in plan.actions
        if action.action_type == "python"
    )


def test_hole_fillet_and_gap_without_intent_emit_no_seed():
    decision = decide_mesh_sizing(
        baseline_size=3.0,
        baseline_source="USER_SPECIFIED",
        features=(
            {"kind": "hole", "region_expression": "p.edges[0:4]", "size": 0.8},
            {"kind": "fillet", "region_expression": "p.edges[4:6]", "size": 0.4},
            {"kind": "gap", "region_expression": "p.edges[6:8]", "size": 0.2},
        ),
        primary_wall_thickness=10.0,
        primary_wall_source="MEASURED",
    )
    assert decision.status == "READY"
    assert decision.edge_constraints == ()
    assert decision.production_default == "NOT_SWITCHED"


def test_located_edge_with_intent_is_executable_but_not_covered():
    decision = decide_mesh_sizing(
        baseline_size=3.0,
        baseline_source="ABAQUS_DEFAULT_SIZE",
        analysis_intents=("hole_resolution",),
        features=({"kind": "hole", "region_expression": "p.edges[0:4]", "number": 12, "evidence": ("circle_edge",)},),
        primary_wall_thickness=10.0,
        primary_wall_source="MEASURED",
    )
    assert decision.status == "READY"
    assert decision.edge_constraints[0].execution == "seedEdgeByNumber"
    assert decision.edge_constraints[0].executed is False
    assert decision.edge_constraints[0].observed_edges == ()


def test_thickness_without_proven_partition_is_blocked():
    decision = decide_mesh_sizing(
        baseline_size=3.0,
        baseline_source="USER_SPECIFIED",
        features=({"kind": "thickness", "layers": 4},),
        element_family="C3D8R",
        primary_wall_thickness=10.0,
        primary_wall_source="MEASURED",
    )
    assert decision.status == "BLOCKED"
    assert decision.unsupported[0].feature == "thickness"
    assert "edge seed is not layer evidence" in decision.unsupported[0].reason


def test_compile_blocks_thickness_before_script_generation():
    intent = _intent(
        geometry={"shape": "cantilever_box", "length": 100.0, "width": 10.0, "height": 10.0},
        mesh_features=({"kind": "thickness", "layers": 4},),
    )
    with pytest.raises(MeshConstraintBlocked, match="through-thickness"):
        compile_engineering_intent(
            intent,
            mesh=IntentMeshSpec(
                global_size=3.0,
                primary_wall_thickness=10.0,
                primary_wall_thickness_source="MEASURED",
            ),
        )


def test_step_assembly_and_two_blocks_still_reject_local_seeds():
    mesh = IntentMeshSpec(
        global_size=4.0,
        local_seeds=(LocalSeed(region_expression="p.edges[0]", size=1.0),),
        primary_wall_thickness=10.0,
        primary_wall_thickness_source="MEASURED",
    )
    with pytest.raises(ValueError, match="two_blocks_contact' does not currently support local_seeds"):
        compile_intent_to_actions(
            model_name="M",
            part_name="P",
            job_name="J",
            geometry=IntentGeometrySpec(shape="two_blocks_contact", width=100.0, height=20.0, length=10.0),
            material={"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
            mesh=mesh,
        )


def test_simple_part_script_order_includes_readback_before_mesh():
    plan = compile_intent_to_actions(
        model_name="M",
        part_name="P",
        job_name="J",
        geometry=IntentGeometrySpec(shape="cantilever_box", width=20.0, height=20.0, length=100.0),
        material={"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        mesh=IntentMeshSpec(
            global_size=4.0,
            local_seeds=(LocalSeed(region_expression="p.edges[0]", size=1.0),),
            primary_wall_thickness=10.0,
            primary_wall_thickness_source="MEASURED",
        ),
    )
    script = _mesh_script(plan)
    assert script.index("seedPart(") < script.index("seedEdgeBySize(")
    assert script.index("seedEdgeBySize(") < script.index("getEdgeSeeds")
    assert script.index("getEdgeSeeds") < script.index("generateMesh(")
    assert "seedEdgeByBias" not in script
    assert plan.intent_summary["mesh_sizing"]["production_default"] == "NOT_SWITCHED"
    assert plan.intent_summary["mesh_sizing"]["edge_coverage"] == "PLANNED_ONLY"
    assert plan.intent_summary["mesh_sizing"]["job_submitted_for_mesh_stage"] is False


def test_s5_cannot_switch_and_s6_emits_no_action():
    with pytest.raises(ValueError, match="NOT_SWITCHED"):
        decide_mesh_sizing(
            baseline_size=3.0,
            baseline_source="USER_SPECIFIED",
        ).__class__(
            baseline_size=3.0,
            baseline_source="USER_SPECIFIED",
            status="READY",
            production_default="SWITCHED",
        )
    assert adaptive_remeshing_capability("STANDARD", "static", "C3D10") == "RESEARCH_ONLY"
    assert adaptive_remeshing_capability("EXPLICIT", "dynamic_explicit", "C3D10") == "EXCLUDED"
    assert adaptive_remeshing_capability("STANDARD", "static", "C3D8R") == "EXCLUDED"
    plan = compile_intent_to_actions(
        model_name="M",
        part_name="P",
        job_name="J",
        geometry=IntentGeometrySpec(shape="cantilever_box", width=20.0, height=20.0, length=100.0),
        material={"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        mesh=IntentMeshSpec(
            global_size=4.0,
            element_library="EXPLICIT",
            primary_wall_thickness=10.0,
            primary_wall_thickness_source="MEASURED",
        ),
        step=IntentStepSpec(name="Step-1", step_type="explicit_dynamic"),
    )
    assert "adaptivity" not in _mesh_script(plan).lower()
    assert plan.intent_summary["mesh_sizing"]["adaptive_remeshing"] == "EXCLUDED"


def test_missing_size_still_does_not_fall_back_to_2_5():
    intent = EngineeringIntent(
        id="S1-STILL-BLOCKED",
        kind="linear_static",
        description="Missing size remains blocked",
        material={"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        mesh_requirements={"element_type": "C3D8R"},
        metadata={"dimensions": {"shape": "cantilever_box", "length": 100.0, "width": 10.0, "height": 10.0}},
    )
    with pytest.raises(ValueError, match="2.5 mm"):
        compile_engineering_intent(intent)


def _box_compile(**mesh_kwargs):
    return compile_intent_to_actions(
        model_name="M",
        part_name="P",
        job_name="J",
        geometry=IntentGeometrySpec(shape="cantilever_box", width=20.0, height=20.0, length=100.0),
        material={"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        mesh=IntentMeshSpec(**mesh_kwargs),
    )


def test_missing_primary_wall_blocks_production_seed():
    from abaqus_ai_agent.reasoning.mesh_inference import PrimaryWallBlocked

    with pytest.raises(PrimaryWallBlocked, match="MISSING_PRIMARY_WALL|no USER_SPECIFIED or MEASURED"):
        _box_compile(global_size=7.0)


def test_invented_wall_values_are_not_measurements():
    decision = decide_mesh_sizing(
        baseline_size=7.0,
        baseline_source="USER_SPECIFIED",
        primary_wall_thickness=7.0,
        primary_wall_source="DEFAULT_SIZE",
    )
    assert decision.status == "INVALID"
    assert decision.unsupported[0].code == "INVALID_PRIMARY_WALL"
    assert decision.executable_baseline_size is None


def test_seed_coarser_than_measured_wall_is_capped_and_recorded():
    plan = _box_compile(
        global_size=8.0,
        primary_wall_thickness=3.0,
        primary_wall_thickness_source="MEASURED",
        local_seeds=(LocalSeed(region_expression="p.edges[0]", size=5.0),),
    )
    script = _mesh_script(plan)
    assert "seedPart(size=3.0" in script or "seedPart(size=3," in script
    assert "size=8" not in script
    assert "seedEdgeBySize" in script
    sizing = plan.intent_summary["mesh_sizing"]
    assert sizing["requested_baseline_size"] == 8.0
    assert sizing["executable_baseline_size"] == 3.0
    assert sizing["primary_wall_thickness_source"] == "MEASURED"
    assert sizing["seed_capped_to_primary_wall"] is True
    assert sizing["capped_local_seeds"][0]["executable"] == 3.0


def test_finer_seed_is_not_changed_by_a_thicker_wall():
    plan = _box_compile(
        global_size=2.0,
        primary_wall_thickness=3.0,
        primary_wall_thickness_source="USER_SPECIFIED",
    )
    script = _mesh_script(plan)
    assert "seedPart(size=2.0" in script or "seedPart(size=2," in script
    assert plan.intent_summary["mesh_sizing"]["seed_capped_to_primary_wall"] is False
    assert plan.intent_summary["mesh_sizing"]["executable_baseline_size"] == 2.0


def test_tet_production_path_still_uses_five_round_script_after_wall_cap():
    plan = _box_compile(
        element_type="C3D10",
        global_size=8.0,
        primary_wall_thickness=3.0,
        primary_wall_thickness_source="MEASURED",
    )
    script = _mesh_script(plan)
    assert "seedPart(size=3.0" in script or "seedPart(size=3," in script
    assert "_abqai_rounds" in script
    assert "_abqai_local_attempt = 2" in script
    assert "_abqai_local_attempt = 5" in script
    assert "_abqai_local_attempt = 6" not in script
    assert "generateMesh" in script
