"""Tests for R1: Agent-Native Action Chain Compiler."""

import pytest
from abaqus_ai_agent.contracts.material import MaterialDefinition, ElasticProperties
from abaqus_ai_agent.planning.compiler import (
    IntentGeometrySpec,
    IntentBoundarySpec,
    IntentLoadSpec,
    IntentStepSpec,
    IntentMeshSpec,
    compile_intent_to_actions,
)


def test_compile_intent_to_actions_end_to_end():
    geom = IntentGeometrySpec(shape="cantilever_box", length=120.0, width=12.0, height=8.0)
    mat = MaterialDefinition(
        name="Aluminum_6061",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=70000.0, poisson_ratio=0.33),
        density=2.7e-9,
    )
    step = IntentStepSpec(name="LoadingStep", step_type="static_general", nlgeom=False)
    bcs = [IntentBoundarySpec(name="FixedRoot", bc_type="ENCASTRE", region="RootFace")]
    loads = [IntentLoadSpec(name="VerticalTipLoad", load_type="concentrated_force", region="TipPoint", magnitude=-500.0, direction="CF2")]
    mesh = IntentMeshSpec(element_type="C3D8R", global_size=3.0)

    plan = compile_intent_to_actions(
        model_name="CompiledModel",
        part_name="BeamPart",
        job_name="CompiledJob",
        geometry=geom,
        material=mat,
        step=step,
        bcs=bcs,
        loads=loads,
        mesh=mesh,
    )

    assert plan.model_name == "CompiledModel"
    assert plan.part_name == "BeamPart"
    assert plan.job_name == "CompiledJob"
    assert len(plan.actions) >= 8

    # Verify action types present in the sequence
    action_types = [a.action_type for a in plan.actions]
    assert "material_elastic" in action_types
    assert "material_density" in action_types
    assert "solid_section" in action_types
    assert "static_step" in action_types
    assert "seed_part" in action_types

    # Verify rendered Python CAE script content
    script = plan.cae_script
    assert "ConstrainedSketch" in script
    assert "BaseSolidExtrude" in script
    assert "Elastic(table=" in script
    assert "70000" in script
    assert "0.33" in script
    assert "Density(table=" in script
    assert "StaticStep" in script
    assert "EncastreBC" in script
    assert "ConcentratedForce" in script
    assert "generateMesh" in script
    assert "mdb.Job(name='CompiledJob'" in script


def test_compile_grounded_intent_plate_with_hole():
    """Verify GA-2.3 compilation of plate_with_hole with GroundedRegions from feature grounding."""
    from abaqus_ai_agent.grounding.feature_grounding import GroundedRegion
    from abaqus_ai_agent.validation.preflight import preflight_plan

    geom = IntentGeometrySpec(
        shape="plate_with_hole",
        length=100.0,
        width=100.0,
        height=100.0,
        radius=10.0,
        thickness=20.0,
        step_file_path="tests/fixtures/step/plate_with_hole.step",
    )
    mat = MaterialDefinition(
        name="StructuralSteel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
        density=7.85e-9,
    )
    step = IntentStepSpec(name="StaticStep", step_type="static_general")
    bcs = [IntentBoundarySpec(name="FixInstallationHole", bc_type="ENCASTRE", region="INSTALLATION_HOLE")]
    loads = [IntentLoadSpec(name="TopDownwardLoad", load_type="concentrated_force", region="TOP_SURFACE", magnitude=-1000.0, direction="CF3")]
    mesh = IntentMeshSpec(element_type="C3D10", global_size=10.0)

    grounded = {
        "INSTALLATION_HOLE": GroundedRegion(
            target_semantic="INSTALLATION_HOLE",
            entity_type="Face",
            entity_ids=("F_277",),
            anchor_point=(60.0, 50.0, 10.0),
            confidence=1.0,
        ),
        "TOP_SURFACE": GroundedRegion(
            target_semantic="TOP_SURFACE",
            entity_type="Face",
            entity_ids=("F_278",),
            anchor_point=(25.0, 25.0, 20.0),
            confidence=1.0,
        ),
    }

    plan = compile_intent_to_actions(
        model_name="GA2_Model",
        part_name="PlatePart",
        job_name="GA2_Job",
        geometry=geom,
        material=mat,
        step=step,
        bcs=bcs,
        loads=loads,
        mesh=mesh,
        grounded_regions=grounded,
    )

    assert plan.model_name == "GA2_Model"
    assert plan.part_name == "PlatePart"
    assert plan.job_name == "GA2_Job"
    assert plan.intent_summary["geometry"]["shape"] == "plate_with_hole"
    assert plan.intent_summary["grounded_regions_count"] == 2

    # Verify script content
    script = plan.cae_script
    assert "CircleByCenterPerimeter" in script
    assert "elemShape=TET, technique=FREE" in script
    assert "elemCode=C3D10" in script
    # Anchor points used in findAt
    assert "findAt(((60.0, 50.0, 10.0),))" in script
    assert "findAt(((25.0, 25.0, 20.0),))" in script
    assert "EncastreBC" in script
    assert "Pressure" in script

    # Preflight verification
    pre_res = preflight_plan(plan.actions)
    assert pre_res.passed is True
    assert len(pre_res.blockers) == 0
