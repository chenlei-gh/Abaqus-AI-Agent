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
