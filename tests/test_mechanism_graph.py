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
