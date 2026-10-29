"""S1: a missing mesh size is blocked, not rewritten as 2.5 mm.

These tests cover the production entries that used to invent a seed. An
explicit positive size is a user specification. Reading Abaqus DEFAULT_SIZE
is not part of this offline check.
"""

import pytest

from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.mesh_quality import tet_mesh_script
from abaqus_ai_agent.planning.compiler import (
    IntentGeometrySpec,
    IntentMeshSpec,
    compile_engineering_intent,
    compile_intent_to_actions,
)
from abaqus_ai_agent.reasoning.mesh_inference import (
    MeshBaselineBlocked,
    infer_mesh_specification,
)


def test_empty_intent_mesh_spec_has_no_implicit_size():
    spec = IntentMeshSpec(primary_wall_thickness=1000.0, primary_wall_thickness_source='MEASURED')
    assert spec.global_size is None
    assert spec.size_source is None


def test_explicit_positive_size_is_marked_user_specified():
    spec = IntentMeshSpec(global_size=3.0, primary_wall_thickness=1000.0, primary_wall_thickness_source='MEASURED')
    assert spec.global_size == 3.0
    assert spec.size_source == "USER_SPECIFIED"


def test_size_source_without_size_is_rejected():
    with pytest.raises(ValueError, match="size_source requires a positive finite global_size"):
        IntentMeshSpec(size_source="ABAQUS_DEFAULT_SIZE", primary_wall_thickness=1000.0, primary_wall_thickness_source='MEASURED')


def test_tet_mesh_script_rejects_missing_size():
    with pytest.raises(ValueError, match="refusing the implicit 2.5 mm default"):
        tet_mesh_script("p", None)


def test_tet_mesh_script_does_not_reseed_during_local_remesh():
    script = tet_mesh_script("p", 2.5)
    assert "shortEdgeThreshold=0.5" in script
    assert script.count("seedPart(") == 0
    assert "deviationFactor=0.05" not in script


def test_retired_premesh_heuristic_is_not_a_production_entry():
    """The 5 percent characteristic-length planner is deleted, not bypassed."""
    import abaqus_ai_agent.geometry as geometry
    import abaqus_ai_agent.planning as planning

    assert not hasattr(geometry, "assess_meshability")
    assert not hasattr(planning, "plan_geometry_mesh")


def test_compile_intent_without_mesh_does_not_emit_implicit_seed():
    with pytest.raises(ValueError, match="refuses the implicit 2.5 mm default"):
        compile_intent_to_actions(
            model_name="M",
            part_name="P",
            job_name="J",
            geometry=IntentGeometrySpec(shape="cantilever_box"),
            material={"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        )


def test_compile_engineering_intent_dict_without_size_does_not_emit_seed():
    intent = EngineeringIntent(
        id="S1-NO-SIZE",
        kind="linear_static",
        description="Missing mesh size",
        material={"name": "Q235", "elastic_modulus": 210000.0, "poisson_ratio": 0.3},
        metadata={"dimensions": {"shape": "cantilever_box", "length": 100.0, "width": 10.0, "height": 10.0}},
        mesh_requirements={"element_type": "C3D8R"},
    )
    with pytest.raises(ValueError, match="refusing the 2.5 mm fallback"):
        compile_engineering_intent(intent)


def test_user_size_in_mesh_requirements_is_traced():
    intent = EngineeringIntent(
        id="S1-USER-SIZE",
        kind="linear_static",
        description="Explicit mesh size",
        mesh_requirements={"global_size": 3.0},
    )
    spec, inference = infer_mesh_specification(intent)
    assert spec.global_size == 3.0
    assert spec.size_source == "USER_SPECIFIED"
    assert inference is None


def test_bounding_box_does_not_invent_a_seed():
    intent = EngineeringIntent(
        id="S1-BOX",
        kind="linear_static",
        description="Box without a seed",
    )
    with pytest.raises(MeshBaselineBlocked, match="Refusing the 2.5 mm fallback"):
        infer_mesh_specification(intent, geometry={"box": [100.0, 50.0, 10.0]})
