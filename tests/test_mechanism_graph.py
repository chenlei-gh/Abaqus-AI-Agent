import pytest

from abaqus_ai_agent.planning.mechanism import (
    MechanismGraph,
    BodySpec,
    BodyType,
    JointSpec,
    JointType,
    FlexibleInterfaceSpec,
)


def test_mechanism_graph_rigid_double_pendulum():
    # 2-body open-chain rigid double pendulum
    m = MechanismGraph("RigidDoublePendulum")
    m.add_body("rod1", body_type="rigid", ref_point_coords=(0.0, 0.0, 0.0), ref_point_name="RP-Rod1")
    m.add_body("rod2", body_type="rigid", ref_point_coords=(0.0, -300.0, 0.0), ref_point_name="RP-Rod2")

    m.add_joint("J1", joint_type="revolute", body_a="ground", body_b="rod1", point_a_name="RP-Ground", point_b_name="RP-Rod1")
    m.add_joint("J2", joint_type="revolute", body_a="rod1", body_b="rod2", point_a_name="RP-Joint", point_b_name="RP-Rod2")
    m.add_load("Gravity", target_name="assembly", load_type="gravity", vector=(0.0, -9810.0, 0.0))

    report = m.validate_topology()
    assert report.is_valid is True
    assert report.num_bodies == 2
    assert report.num_rigid_bodies == 2
    assert report.num_flexible_bodies == 0
    assert report.num_joints == 2
    assert report.closed_loops_count == 0
    # In 2D, 2 bodies * 3 DOF - 2 joints * 2 constraints = 6 - 4 = 2 DOF
    assert report.estimated_dof_planar == 2

    actions = m.compile_to_actions("TestModel")
    types = [a.action_type for a in actions]
    assert "reference_point" in types
    assert "rigid_body" in types
    assert "connector_section" in types
    assert "wire_connector" in types
    assert "gravity" in types


def test_mechanism_graph_four_bar_closed_loop():
    # 4-bar planar mechanism: crank, coupler, rocker, connected to ground
    m = MechanismGraph("FourBarLinkage")
    m.add_body("ground", body_type="ground")
    m.add_body("crank", body_type="rigid", ref_point_coords=(0.0, 50.0, 0.0), ref_point_name="RP-Crank")
    m.add_body("coupler", body_type="rigid", ref_point_coords=(100.0, 100.0, 0.0), ref_point_name="RP-Coupler")
    m.add_body("rocker", body_type="rigid", ref_point_coords=(200.0, 50.0, 0.0), ref_point_name="RP-Rocker")

    m.add_joint("J_Ground_Crank", joint_type="revolute", body_a="ground", body_b="crank")
    m.add_joint("J_Crank_Coupler", joint_type="revolute", body_a="crank", body_b="coupler")
    m.add_joint("J_Coupler_Rocker", joint_type="revolute", body_a="coupler", body_b="rocker")
    m.add_joint("J_Rocker_Ground", joint_type="revolute", body_a="rocker", body_b="ground")

    report = m.validate_topology()
    assert report.is_valid is True
    assert report.num_bodies == 4
    assert report.num_joints == 4
    assert report.closed_loops_count == 1
    # 3 moving bodies * 3 DOF - 4 revolute joints * 2 constraints = 9 - 8 = 1 DOF (Grübler criterion for 4-bar)
    assert report.estimated_dof_planar == 1


def test_mechanism_graph_flexible_multibody_coupling():
    # FMBD: Rigid crank driving a flexible elastic connecting rod
    m = MechanismGraph("RigidFlexibleMechanism")
    m.add_body("crank", body_type="rigid", ref_point_coords=(0.0, 50.0, 0.0), ref_point_name="RP-Crank")
    m.add_body(
        "flex_rod",
        body_type="flexible",
        part_name="FlexRodPart",
        instance_name="FlexRod-1",
        youngs_modulus=210000.0,
        poisson_ratio=0.3,
        density=7.85e-9,
        mesh_size=2.0,
        element_code="C3D8R",
    )

    # Attach flexible interface coupling between connector RP and FE mesh region
    m.add_flexible_interface(
        name="Coupling-CrankRod",
        body_name="flex_rod",
        interface_region="FlexRod-1.RodEndFace",
        ref_point_name="RP-FlexInterface",
        ref_point_coords=(0.0, 100.0, 0.0),
        coupling_type="KINEMATIC",
    )

    m.add_joint("J_Ground_Crank", joint_type="revolute", body_a="ground", body_b="crank")
    m.add_joint(
        "J_Crank_Rod",
        joint_type="revolute",
        body_a="crank",
        body_b="flex_rod",
        point_a_name="RP-CrankPin",
        point_b_name="RP-FlexInterface",
    )

    report = m.validate_topology()
    assert report.is_valid is True
    assert report.num_rigid_bodies == 1
    assert report.num_flexible_bodies == 1
    assert report.num_interfaces == 1

    actions = m.compile_to_actions("FMBDModel")
    types = [a.action_type for a in actions]
    assert "reference_point" in types
    assert "rigid_body" in types
    assert "coupling_constraint" in types
    assert "connector_section" in types
    assert "wire_connector" in types

    # Verify coupling action parameters
    coupling_act = next(a for a in actions if a.action_type == "coupling_constraint")
    assert coupling_act.parameters["name"] == "Coupling-CrankRod"
    assert coupling_act.parameters["control_point_name"] == "RP-FlexInterface"
    assert coupling_act.parameters["surface_name"] == "FlexRod-1.RodEndFace"
    assert coupling_act.parameters["coupling_type"] == "KINEMATIC"


def test_mechanism_graph_topology_validation_errors():
    m = MechanismGraph("BrokenMechanism")
    m.add_body("rod1", body_type="rigid")
    # Connect to non-existent body
    m.add_joint("J1", body_a="rod1", body_b="phantom_body")
    # Flexible interface on unknown body
    m.add_flexible_interface("I1", body_name="ghost", interface_region="surf", ref_point_name="RP", ref_point_coords=(0,0,0))

    report = m.validate_topology()
    assert report.is_valid is False
    assert any("phantom_body" in err for err in report.errors)
    assert any("ghost" in err for err in report.errors)

    with pytest.raises(ValueError, match="Cannot compile invalid mechanism topology"):
        m.compile_to_actions("Model-Err")


def test_mechanism_graph_full_stack_fmbd_compilation():
    """Verify end-to-end full-stack compilation of an FMBD mechanism into complete Abaqus actions."""
    from abaqus_ai_agent.planning.mechanism import MechanismAnalysisSpec

    m = MechanismGraph("CrankSliderFMBD")
    # 1. Ground body
    m.add_body("ground", body_type="ground", ref_point_coords=(0.0, 0.0, 0.0), ref_point_name="RP_GROUND")

    # 2. Rigid crank with inertia and tie regions
    m.add_body(
        "crank",
        body_type="rigid",
        part_name="CrankPart",
        instance_name="Crank-1",
        ref_point_coords=(0.0, 0.0, 0.0),
        ref_point_name="RP_CRANK_PIVOT",
        assembly_cells_set="CrankCells",
        tie_regions=("RP_CRANK_ELBOW",),
    )

    # 3. Flexible connecting link with continuum FE properties
    m.add_body(
        "flex_rod",
        body_type="flexible",
        part_name="FlexRodPart",
        instance_name="FlexRod-1",
        youngs_modulus=210000.0,
        poisson_ratio=0.3,
        density=7.85e-9,
        mesh_size=5.0,
        element_code="C3D8R",
        element_library="STANDARD",
        part_cells_set="Cells",
    )

    # 4. Flexible Interface: Kinematic Coupling on rod top face
    m.add_flexible_interface(
        name="Coupling_Elbow_FlexRod",
        body_name="flex_rod",
        interface_region="TopEndFace",
        ref_point_name="RP_FLEX_INTERFACE",
        ref_point_coords=(100.0, 100.0, 0.0),
        coupling_type="KINEMATIC",
    )

    # 5. Joints
    # Joint 1: Ground to Crank Pivot
    m.add_joint(
        "J_Pivot",
        joint_type="revolute",
        body_a="ground",
        body_b="crank",
        point_a_name="RP_GROUND",
        point_b_name="RP_CRANK_PIVOT",
        orientation="Csys_Z",
    )

    # Joint 2: Crank to FlexRod (Testing automatic point resolution for flexible body!)
    m.add_joint(
        "J_Elbow",
        joint_type="revolute",
        body_a="crank",
        body_b="flex_rod",
        point_a_name="RP_CRANK_ELBOW",
        # Notice: point_b_name is intentionally omitted to verify automatic interface resolution!
        point_b_name=None,
        orientation="Csys_Z",
    )

    # 6. Gravity load
    m.add_load("Gravity", target_name="assembly", load_type="gravity", vector=(0.0, -9810.0, 0.0))

    # 7. Analysis Specification
    analysis = MechanismAnalysisSpec(
        step_name="DynamicStep",
        job_name="CrankSliderJob",
        time_period=0.8,
        initial_inc=0.005,
        max_inc=0.01,
        nlgeom=True,
    )

    # Topology validation & DOF distinction audit
    report = m.validate_topology()
    assert report.is_valid is True
    assert report.num_bodies == 3
    assert report.num_rigid_bodies == 1
    assert report.num_flexible_bodies == 1
    assert report.has_ground is True
    assert report.num_joints == 2
    assert report.num_interfaces == 1
    assert report.rigid_mobility_dof_spatial == 2  # 2 moving bodies * 6 - 2 revolute * 5 = 12 - 10 = 2
    assert "Rigid mobility DOFs apply strictly" in report.flexible_continuum_note

    # Compile to Actions
    actions = m.compile_to_actions("CrankSliderModel", analysis=analysis)
    action_types = [a.action_type for a in actions]

    # Verify complete pipeline presence
    expected_types = [
        "material_elastic",
        "material_density",
        "solid_section",
        "section_assignment",
        "reference_point",
        "displacement_bc",
        "rigid_body",
        "coupling_constraint",
        "connector_section",
        "wire_connector",
        "implicit_dynamic_step",
        "field_output",
        "history_output",
        "gravity",
        "seed_part",
        "element_type",
        "generate_mesh",
        "create_job",
    ]
    for exp in expected_types:
        assert exp in action_types, f"Expected action type '{exp}' missing from compiled actions"

    # Verify automatic interface RP resolution for Joint 2
    conn_elbow = next(a for a in actions if a.action_type == "wire_connector" and a.parameters["name"] == "Conn-J_Elbow")
    assert conn_elbow.parameters["point1_name"] == "RP_CRANK_ELBOW"
    assert conn_elbow.parameters["point2_name"] == "RP_FLEX_INTERFACE", (
        "Compiler failed to resolve flexible body interface RP!"
    )

    # Verify coupling constraint surface expression formatting
    coupling_act = next(a for a in actions if a.action_type == "coupling_constraint")
    assert coupling_act.parameters["control_point_name"] == "RP_FLEX_INTERFACE"
    assert coupling_act.parameters["surface_expression"] == "a.instances['FlexRod-1'].surfaces['TopEndFace']"

    # Verify Ground BC anchor
    ground_bc = next(a for a in actions if a.action_type == "displacement_bc" and a.parameters["name"] == "BC-GroundAnchor")
    assert ground_bc.parameters["u1"] == 0.0
    assert ground_bc.parameters["ur3"] == 0.0

    # Verify Job Creation
    job_act = next(a for a in actions if a.action_type == "create_job")
    assert job_act.parameters["name"] == "CrankSliderJob"
