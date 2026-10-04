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
    compile_engineering_intent,
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


def test_compile_multi_anchor_group_intent():
    """Verify GA-2.5 compilation of multi-anchor feature groups into native multi-findAt sets."""
    from abaqus_ai_agent.grounding.feature_grounding import GroundedRegion
    from abaqus_ai_agent.validation.preflight import preflight_plan

    geom = IntentGeometrySpec(shape="plate_with_hole", length=100.0, width=100.0, height=100.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=200000.0, poisson_ratio=0.3),
    )
    step = IntentStepSpec(name="StaticStep", step_type="static_general")
    bcs = [IntentBoundarySpec(name="FixAllBolts", bc_type="ENCASTRE", region="ALL_BOLTS")]
    loads = [IntentLoadSpec(name="BottomPressure", load_type="pressure", region="BOTTOM_FACE", magnitude=5.0)]
    mesh = IntentMeshSpec(element_type="C3D10", global_size=10.0)

    grounded = {
        "ALL_BOLTS": GroundedRegion(
            target_semantic="ALL_HOLES",
            entity_type="Face",
            entity_ids=("F_1", "F_2"),
            anchor_point=(15.0, 15.0, 10.0),
            anchor_points=((15.0, 15.0, 10.0), (85.0, 85.0, 10.0)),
            confidence=0.95,
        ),
        "BOTTOM_FACE": GroundedRegion(
            target_semantic="BOTTOM_SURFACE",
            entity_type="Face",
            entity_ids=("F_BOT",),
            anchor_point=(50.0, 50.0, 0.0),
            confidence=1.0,
        ),
    }

    plan = compile_intent_to_actions(
        model_name="GroupModel",
        part_name="GroupPart",
        job_name="GroupJob",
        geometry=geom,
        material=mat,
        step=step,
        bcs=bcs,
        loads=loads,
        mesh=mesh,
        grounded_regions=grounded,
    )

    script = plan.cae_script
    # Must contain both anchor points inside the findAt call for ALL_BOLTS
    assert "findAt(((15.0, 15.0, 10.0),), ((85.0, 85.0, 10.0),))" in script
    # Bottom face anchor
    assert "findAt(((50.0, 50.0, 0.0),))" in script
    assert "EncastreBC" in script
    assert "Pressure" in script

    pre = preflight_plan(plan.actions)
    assert pre.passed is True
    assert len(pre.blockers) == 0


def test_compile_multi_step_procedure_dag():
    """Verify GA-2.6.2 compilation of multi-step procedure DAG with state inheritance."""
    from abaqus_ai_agent.contracts.procedure import MultiStepProcedureSpec, StepDependency

    geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
    )
    proc = MultiStepProcedureSpec(
        steps=(
            StepDependency(name="Step-Preload", previous="Initial", procedure="static", time_period=1.0),
            StepDependency(name="Step-Service", previous="Step-Preload", procedure="static", time_period=1.0),
        )
    )
    bcs = [IntentBoundarySpec(name="FixRoot", bc_type="ENCASTRE", region="RootFace")]
    loads = [
        IntentLoadSpec(name="Preload", load_type="concentrated_force", region="TipFace", magnitude=1000.0, step="Step-Preload"),
        IntentLoadSpec(name="ServiceLoad", load_type="concentrated_force", region="TipFace", magnitude=500.0, step="Step-Service"),
    ]
    mesh = IntentMeshSpec(element_type="C3D8R", global_size=5.0)

    plan = compile_intent_to_actions(
        model_name="MultiStepModel",
        part_name="BeamPart",
        job_name="MultiStepJob",
        geometry=geom,
        material=mat,
        procedure=proc,
        bcs=bcs,
        loads=loads,
        mesh=mesh,
    )

    assert plan.intent_summary["steps_count"] == 2
    script = plan.cae_script

    # Verify both steps are defined with correct DAG previous relationship
    assert "StaticStep(name='Step-Preload', previous='Initial'" in script
    assert "StaticStep(name='Step-Service', previous='Step-Preload'" in script
    # Loads assigned to their respective steps
    assert "createStepName='Step-Preload'" in script
    assert "createStepName='Step-Service'" in script

    # Verify invalid DAG failure handling
    invalid_proc = MultiStepProcedureSpec(
        steps=(
            StepDependency(name="Step-2", previous="NonExistentStep", procedure="static"),
        )
    )
    with pytest.raises(ValueError, match="Invalid procedure DAG"):
        compile_intent_to_actions(
            model_name="BadModel",
            part_name="BeamPart",
            job_name="BadJob",
            geometry=geom,
            material=mat,
            procedure=invalid_proc,
            bcs=bcs,
            loads=loads,
            mesh=mesh,
        )


def test_compile_bolt_pretension_two_stage_lifecycle():
    """Verify GA-2.6.2 two-stage bolt pretension lifecycle compilation (APPLY_FORCE -> FIX_LENGTH)."""
    from abaqus_ai_agent.contracts.procedure import BoltPretensionLifecycleSpec

    geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
    )
    steps = [
        IntentStepSpec(name="Step-Preload", step_type="static_general", previous="Initial"),
        IntentStepSpec(name="Step-Service", step_type="static_general", previous="Step-Preload"),
    ]
    bcs = [IntentBoundarySpec(name="FixBottom", bc_type="ENCASTRE", region="RootFace")]
    bolt_spec = BoltPretensionLifecycleSpec(
        name="BoltPreload",
        region_expression="BoltCutFace",
        preload_magnitude=5000.0,
        preload_step="Step-Preload",
        service_step="Step-Service",
        direction_vector=(0.0, 0.0, 1.0),
    )

    plan = compile_intent_to_actions(
        model_name="BoltModel",
        part_name="BoltPart",
        job_name="BoltJob",
        geometry=geom,
        material=mat,
        steps=steps,
        bcs=bcs,
        bolt_pretensions=[bolt_spec],
    )

    assert plan.intent_summary["bolt_pretensions_count"] == 1
    script = plan.cae_script

    # DatumAxis created for direction
    assert "DatumAxisByTwoPoint" in script
    # Stage 1: BoltLoad with APPLY_FORCE in preload step
    assert "BoltLoad(name='BoltPreload', createStepName='Step-Preload'" in script
    assert "magnitude=5000.0" in script
    assert "boltMethod=APPLY_FORCE" in script
    # Stage 2: setValuesInStep with FIX_LENGTH in service step
    assert "loads['BoltPreload'].setValuesInStep(stepName='Step-Service', boltMethod=FIX_LENGTH)" in script

    # Check action types
    action_types = [a.action_type for a in plan.actions]
    assert "bolt_load" in action_types
    assert "bolt_load_set_values" in action_types


def test_compile_moment_rp_coupling_strategy():
    """Verify GA-2.6.2 Moment / Torque compilation with Reference Point & Kinematic Coupling."""
    from abaqus_ai_agent.contracts.procedure import MomentLoadSpec, MomentTransferStrategy

    geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=10.0, height=10.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
    )
    step = IntentStepSpec(name="Step-1", step_type="static_general")
    bcs = [IntentBoundarySpec(name="FixRoot", bc_type="ENCASTRE", region="RootFace")]
    moment_spec = MomentLoadSpec(
        name="TorqueLoad",
        region_expression="TipFace",
        magnitude=100000.0,
        axis="CM3",
        step="Step-1",
        strategy=MomentTransferStrategy.RP_COUPLING,
        rp_coordinates=(5.0, 5.0, 100.0),
    )

    plan = compile_intent_to_actions(
        model_name="TorqueModel",
        part_name="ShaftPart",
        job_name="TorqueJob",
        geometry=geom,
        material=mat,
        step=step,
        bcs=bcs,
        moments=[moment_spec],
    )

    assert plan.intent_summary["moments_count"] == 1
    script = plan.cae_script

    # Reference point & set created
    assert "ReferencePoint(point=(5.0, 5.0, 100.0))" in script
    assert "TorqueLoad_RP_Set" in script
    # Kinematic coupling created
    assert "Coupling(name='TorqueLoad_Coupling'" in script
    assert "couplingType=KINEMATIC" in script
    # Native Moment API used (not ConcentratedForce with cm3)
    assert "Moment(name='TorqueLoad', createStepName='Step-1', region=rp_set, cm1=0.0, cm2=0.0, cm3=100000.0)" in script

    # Check action types
    action_types = [a.action_type for a in plan.actions]
    assert "reference_point" in action_types
    assert "coupling_constraint" in action_types
    assert "concentrated_moment" in action_types


def test_compile_spatial_load_field():
    """Verify GA-2.6.2 SpatialLoadField compilation and field expression validation."""
    from abaqus_ai_agent.contracts.procedure import SpatialLoadField

    geom = IntentGeometrySpec(shape="cantilever_box", length=50.0, width=20.0, height=10.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
    )
    step = IntentStepSpec(name="Step-1", step_type="static_general")
    bcs = [IntentBoundarySpec(name="FixRoot", bc_type="ENCASTRE", region="RootFace")]
    field_spec = SpatialLoadField(name="LinearYField", expression="1.0 + 0.02 * Y")
    loads = [
        IntentLoadSpec(
            name="SpatialPressure",
            load_type="pressure",
            region="TopFace",
            magnitude=10.0,
            field="LinearYField",
        )
    ]

    plan = compile_intent_to_actions(
        model_name="FieldModel",
        part_name="PlatePart",
        job_name="FieldJob",
        geometry=geom,
        material=mat,
        step=step,
        bcs=bcs,
        loads=loads,
        fields=[field_spec],
    )

    assert plan.intent_summary["fields_count"] == 1
    script = plan.cae_script

    # ExpressionField defined in CAE script
    assert "ExpressionField(name='LinearYField', expression='1.0 + 0.02 * Y')" in script
    # Pressure load references field
    assert "Pressure(name='SpatialPressure', createStepName='Step-1'" in script
    assert "distributionType=FIELD" in script
    assert "field='LinearYField'" in script

    # Check action types
    action_types = [a.action_type for a in plan.actions]
    assert "expression_field" in action_types
    assert "pressure_load" in action_types

    # Disallowed expression syntax check in SpatialLoadField
    with pytest.raises(ValueError, match="Invalid field expression"):
        SpatialLoadField(name="BadField", expression="__import__('os').system('ls')")


def test_compile_symmetry_bc_all_planes():
    """Verify GA-2.6.2 Symmetry BC compilation for XSYMM, YSYMM, ZSYMM and SYMMETRY_PLANE grounding."""
    from abaqus_ai_agent.grounding.feature_grounding import GroundedRegion

    geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=50.0, height=20.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210000.0, poisson_ratio=0.3),
    )
    step = IntentStepSpec(name="Step-1", step_type="static_general")
    bcs = [
        IntentBoundarySpec(name="SymmX", bc_type="XSYMM", region="SYMM_X_FACE"),
        IntentBoundarySpec(name="SymmY", bc_type="YSYMM", region="SYMM_Y_FACE"),
        IntentBoundarySpec(name="SymmZ", bc_type="ZSYMM", region="SYMM_Z_FACE"),
    ]
    grounded = {
        "SYMM_X_FACE": GroundedRegion(
            target_semantic="SYMMETRY_PLANE_X",
            entity_type="Face",
            entity_ids=("F_X",),
            anchor_point=(0.0, 25.0, 10.0),
            confidence=1.0,
        ),
        "SYMM_Y_FACE": GroundedRegion(
            target_semantic="SYMMETRY_PLANE_Y",
            entity_type="Face",
            entity_ids=("F_Y",),
            anchor_point=(25.0, 0.0, 10.0),
            confidence=1.0,
        ),
        "SYMM_Z_FACE": GroundedRegion(
            target_semantic="SYMMETRY_PLANE_Z",
            entity_type="Face",
            entity_ids=("F_Z",),
            anchor_point=(25.0, 25.0, 0.0),
            confidence=1.0,
        ),
    }

    plan = compile_intent_to_actions(
        model_name="SymmModel",
        part_name="SymmPart",
        job_name="SymmJob",
        geometry=geom,
        material=mat,
        step=step,
        bcs=bcs,
        grounded_regions=grounded,
    )

    script = plan.cae_script
    assert "XsymmBC(name='SymmX', createStepName='Initial'" in script
    assert "YsymmBC(name='SymmY', createStepName='Initial'" in script
    assert "ZsymmBC(name='SymmZ', createStepName='Initial'" in script

    # Check symmetry_bc action types
    symm_actions = [a for a in plan.actions if a.action_type == "symmetry_bc"]
    assert len(symm_actions) == 3
    planes = [a.parameters["plane"] for a in symm_actions]
    assert planes == ["X", "Y", "Z"]


def test_compile_comprehensive_multi_physics_plan():
    """Verify comprehensive compilation of Multi-Step + Bolt + Moment + Field + Symmetry with Preflight validation."""
    from abaqus_ai_agent.contracts.procedure import (
        BoltPretensionLifecycleSpec,
        MomentLoadSpec,
        MomentTransferStrategy,
        MultiStepProcedureSpec,
        SpatialLoadField,
        StepDependency,
    )
    from abaqus_ai_agent.validation.preflight import preflight_plan

    geom = IntentGeometrySpec(shape="cantilever_box", length=120.0, width=20.0, height=20.0)
    mat = MaterialDefinition(
        name="Titanium",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=110000.0, poisson_ratio=0.34),
        density=4.5e-9,
    )
    proc = MultiStepProcedureSpec(
        steps=(
            StepDependency(name="Step-Preload", previous="Initial", procedure="static", time_period=1.0),
            StepDependency(name="Step-Service", previous="Step-Preload", procedure="static", time_period=1.0),
        )
    )
    bcs = [
        IntentBoundarySpec(name="FixRoot", bc_type="ENCASTRE", region="RootFace"),
        IntentBoundarySpec(name="SymmetryX", bc_type="XSYMM", region="SymmFace"),
    ]
    bolt_spec = BoltPretensionLifecycleSpec(
        name="MainBolt",
        region_expression="BoltCut",
        preload_magnitude=8000.0,
        preload_step="Step-Preload",
        service_step="Step-Service",
        direction_vector=(0.0, 0.0, 1.0),
    )
    moment_spec = MomentLoadSpec(
        name="TipTorque",
        region_expression="TipFace",
        magnitude=50000.0,
        axis="CM3",
        step="Step-Service",
        strategy=MomentTransferStrategy.RP_COUPLING,
        rp_coordinates=(10.0, 10.0, 120.0),
    )
    field_spec = SpatialLoadField(name="GradField", expression="2.0 + 0.05 * Y")
    loads = [
        IntentLoadSpec(
            name="GradPressure",
            load_type="pressure",
            region="TopFace",
            magnitude=5.0,
            step="Step-Service",
            field="GradField",
        )
    ]

    plan = compile_intent_to_actions(
        model_name="ComprehensiveModel",
        part_name="Part1",
        job_name="ComprehensiveJob",
        geometry=geom,
        material=mat,
        procedure=proc,
        bcs=bcs,
        loads=loads,
        fields=[field_spec],
        bolt_pretensions=[bolt_spec],
        moments=[moment_spec],
    )

    # Summary asserts
    summary = plan.intent_summary
    assert summary["steps_count"] == 2
    assert summary["fields_count"] == 1
    assert summary["bolt_pretensions_count"] == 1
    assert summary["moments_count"] == 1
    assert summary["actions_count"] > 15

    # Script asserts
    script = plan.cae_script
    assert "ExpressionField(name='GradField'" in script
    assert "BoltLoad(name='MainBolt'" in script
    assert "FIX_LENGTH" in script
    assert "Coupling(name='TipTorque_Coupling'" in script
    assert "Moment(name='TipTorque'" in script
    assert "XsymmBC(name='SymmetryX'" in script

    # Preflight verification
    pre = preflight_plan(plan.actions)
    assert pre.passed is True
    assert len(pre.blockers) == 0


def test_compile_engineering_intent_from_dict_intent():
    """Verify compile_engineering_intent handles dictionary-based specifications (e.g. from JEV router)."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.validation.preflight import preflight_plan

    intent = EngineeringIntent(
        id="INTENT-STATIC-001",
        kind="linear_static",
        description="Cantilever beam under vertical tip load",
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
        metadata={
            "dimensions": {"shape": "cantilever_box", "length": 150.0, "width": 15.0, "height": 10.0},
        },
    )

    plan = compile_engineering_intent(intent)
    assert plan.model_name == "Model_INTENT_STATIC_001"
    assert plan.part_name == "MainPart"
    assert len(plan.actions) >= 8

    # Verify CAE script contains encastre and force in -Y (CF2=-1000.0)
    assert "EncastreBC" in plan.cae_script
    assert "cf2=-1000.0" in plan.cae_script
    assert "210000.0" in plan.cae_script

    pre = preflight_plan(plan.actions)
    assert pre.passed is True
    assert len(pre.blockers) == 0


def test_compile_engineering_intent_with_typed_specs():
    """Verify compile_engineering_intent with explicitly typed specs."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.validation.preflight import preflight_plan

    geom = IntentGeometrySpec(shape="cantilever_box", length=80.0, width=10.0, height=10.0)
    mat = MaterialDefinition(
        name="Alloy",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=72000.0, poisson_ratio=0.33),
    )
    bcs = (IntentBoundarySpec(name="FixedRoot", bc_type="ENCASTRE", region="RootFace"),)
    loads = (IntentLoadSpec(name="PressureLoad", load_type="pressure", region="TopFace", magnitude=2.5),)

    intent = EngineeringIntent(
        id="INTENT-TYPED-002",
        kind="linear_static",
        description="Typed specs test",
        boundary_conditions=bcs,
        loads=loads,
    )

    plan = compile_engineering_intent(intent, geometry=geom, material=mat)
    assert "Pressure" in plan.cae_script
    assert "72000.0" in plan.cae_script
    pre = preflight_plan(plan.actions)
    assert pre.passed is True
    assert len(pre.blockers) == 0


def test_compile_engineering_intent_advanced_l4_passthrough():
    """Verify compile_engineering_intent passes through advanced L4 domains (fatigue, connectors, fmbd)."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent
    from abaqus_ai_agent.contracts.fatigue import IntentFatigueSpec

    fatigue_spec = IntentFatigueSpec(
        target_cycles=1e6,
        allowable_damage=1.0,
        material_curve=((300.0, 1e4), (200.0, 1e6)),
        ultimate_strength=310.0,
    )

    intent = EngineeringIntent(
        id="INTENT-FATIGUE-003",
        kind="fatigue_damage",
        description="Fatigue evaluation",
        material={"name": "Al6061", "elastic_modulus": 70000.0, "poisson_ratio": 0.33},
        boundary_conditions=({"type": "encastre", "region": "RootFace"},),
        loads=({"type": "concentrated_force", "region": "TipFace", "magnitude": 500.0, "direction": "-Y"},),
        metadata={"dimensions": {"shape": "cantilever_box", "length": 100.0, "width": 10.0, "height": 10.0}},
        fatigue=fatigue_spec,
    )

    plan = compile_engineering_intent(intent)
    # Compiler ensures S field output is enabled in CAE script and fatigue is in intent summary
    assert "fatigue" in plan.intent_summary
    assert plan.intent_summary["fatigue"] is not None
    assert "variables=('S', 'U', 'RF')" in plan.cae_script


def test_compile_engineering_intent_fail_closed_missing_geometry():
    """Verify compile_engineering_intent fails closed with ValueError when geometry is omitted."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent

    intent = EngineeringIntent(
        id="INTENT-NOGEOM",
        kind="linear_static",
        description="Missing geometry test",
        material={"name": "Steel", "elastic_modulus": 200000.0, "poisson_ratio": 0.3},
    )

    with pytest.raises(ValueError, match="missing geometry specification"):
        compile_engineering_intent(intent)


def test_compile_engineering_intent_fail_closed_missing_material():
    """Verify compile_engineering_intent fails closed with ValueError when material is omitted."""
    from abaqus_ai_agent.contracts.intent import EngineeringIntent

    intent = EngineeringIntent(
        id="INTENT-NOMAT",
        kind="linear_static",
        description="Missing material test",
        metadata={"dimensions": {"shape": "cantilever_box", "length": 100.0, "width": 10.0, "height": 10.0}},
    )

    with pytest.raises(ValueError, match="missing material specification"):
        compile_engineering_intent(intent)
