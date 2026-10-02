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
    ground_bc = next(a for a in actions if a.action_type == "displacement_bc" and "BC-Ground" in a.parameters["name"])
    assert ground_bc.parameters["u1"] == 0.0
    assert ground_bc.parameters["ur3"] == 0.0

    # Verify Job Creation
    job_act = next(a for a in actions if a.action_type == "create_job")
    assert job_act.parameters["name"] == "CrankSliderJob"


def test_fmbd5_crank_slider_compiler_contract():
    """FMBD-5: Declarative compiler contract test for a closed-loop rigid-flexible crank-slider mechanism.

    Topology:
      Ground (Two distinct physical anchor interfaces @ (0,0,0) and (400,0,0))
        |-- Revolute J_Pivot @ (0,0,0) --> Rigid Crank
        |-- Prismatic J_Guide @ (400,0,0) <-- Rigid Slider
      Rigid Crank
        |-- Revolute J_Elbow @ (100,0,0) --> Flexible Connecting Rod
      Flexible Connecting Rod (Elastic FE continuum, dual coupling interfaces)
        |-- Revolute J_Wrist @ (400,0,0) --> Rigid Slider
    """
    from abaqus_ai_agent.planning.mechanism import MechanismAnalysisSpec

    m = MechanismGraph("FMBD5_CrankSlider")

    # 1. Bodies
    # Ground body
    m.add_body("ground", body_type="ground")

    # Rigid Crank (Pivot at 0, Elbow at 100)
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

    # Flexible Connecting Rod (FE Continuum with two distinct interface ends)
    m.add_body(
        "flex_rod",
        body_type="flexible",
        part_name="FlexRodPart",
        instance_name="FlexRod-1",
        youngs_modulus=210000.0,
        poisson_ratio=0.3,
        density=7.85e-9,
        mesh_size=4.0,
        element_code="C3D8R",
        element_library="STANDARD",
        part_cells_set="Cells",
    )

    # Rigid Slider (Block at X=400)
    m.add_body(
        "slider",
        body_type="rigid",
        part_name="SliderPart",
        instance_name="Slider-1",
        ref_point_coords=(400.0, 0.0, 0.0),
        ref_point_name="RP_SLIDER",
        assembly_cells_set="SliderCells",
    )

    # 2. Dual Flexible Interfaces on the Flexible Connecting Rod
    # Interface A: Elbow end (connects to Crank)
    m.add_flexible_interface(
        name="Coupling_Elbow",
        body_name="flex_rod",
        interface_region="ElbowEndFace",
        ref_point_name="RP_FLEX_ELBOW",
        ref_point_coords=(100.0, 0.0, 0.0),
        role="revolute",
        coupling_type="KINEMATIC",
    )
    # Interface B: Wrist end (connects to Slider)
    m.add_flexible_interface(
        name="Coupling_Wrist",
        body_name="flex_rod",
        interface_region="WristEndFace",
        ref_point_name="RP_FLEX_WRIST",
        ref_point_coords=(400.0, 0.0, 0.0),
        role="revolute",
        coupling_type="KINEMATIC",
    )

    # 3. Kinematic Joints forming a Closed-Loop Kinematic Chain
    # Joint 1: Ground Pivot (Revolute @ (0,0,0))
    m.add_joint(
        "J_Pivot",
        joint_type="revolute",
        body_a="ground",
        body_b="crank",
        location=(0.0, 0.0, 0.0),
        point_a_name=None,  # Verify automatic Ground RP generation
        point_b_name="RP_CRANK_PIVOT",
    )

    # Joint 2: Crank-to-Rod Elbow (Revolute @ (100,0,0))
    m.add_joint(
        "J_Elbow",
        joint_type="revolute",
        body_a="crank",
        body_b="flex_rod",
        location=(100.0, 0.0, 0.0),
        point_a_name="RP_CRANK_ELBOW",
        point_b_name=None,  # Verify automatic distance-based resolution to RP_FLEX_ELBOW!
    )

    # Joint 3: Rod-to-Slider Wrist (Revolute @ (400,0,0))
    m.add_joint(
        "J_Wrist",
        joint_type="revolute",
        body_a="flex_rod",
        body_b="slider",
        location=(400.0, 0.0, 0.0),
        point_a_name=None,  # Verify automatic distance-based resolution to RP_FLEX_WRIST!
        point_b_name="RP_SLIDER",
    )

    # Joint 4: Slider Guide to Ground (Prismatic @ (400,0,0))
    m.add_joint(
        "J_SliderGuide",
        joint_type="prismatic",
        body_a="slider",
        body_b="ground",
        location=(400.0, 0.0, 0.0),
        point_a_name="RP_SLIDER",
        point_b_name=None,  # Verify automatic Ground RP generation at (400,0,0)!
    )

    # 4. Actuation and Loads
    m.add_load("Gravity", target_name="assembly", load_type="gravity", vector=(0.0, -9810.0, 0.0))

    # 5. Analysis Specification
    analysis = MechanismAnalysisSpec(
        step_name="FMBD5_Step",
        job_name="FMBD5_CrankSliderJob",
        time_period=1.5,
        initial_inc=0.002,
        max_inc=0.005,
        nlgeom=True,
    )

    # -------------------------------------------------------------------------
    # Audit 1: Structural DOF & Mobility Analysis
    # -------------------------------------------------------------------------
    report = m.validate_topology()
    assert report.is_valid is True
    assert report.num_bodies == 4          # Ground, Crank, FlexRod, Slider
    assert report.num_rigid_bodies == 2    # Crank, Slider
    assert report.num_flexible_bodies == 1 # FlexRod
    assert report.num_joints == 4          # Pivot, Elbow, Wrist, SliderGuide
    assert report.num_interfaces == 2      # Elbow, Wrist
    assert report.closed_loops_count == 1  # 4 joints - (3 moving bodies + 1 ground) + 1 = 1 loop
    # Grübler mobility: 3 moving bodies * 3 - (3 revolute * 2 + 1 prismatic * 2) = 9 - 8 = 1 DOF
    assert report.mobility_rigid_planar == 1
    assert report.joint_constraints_planar == 8
    # Spatial DOF: 3 moving bodies * 6 - (3 revolute * 5 + 1 prismatic * 5) = 18 - 20 = -2 (overconstrained in spatial 3D as classic 2D planar linkage)
    assert report.mobility_rigid_spatial == -2
    assert report.joint_constraints_spatial == 20

    # -------------------------------------------------------------------------
    # Audit 2: End-to-End Compilation & Strict CAE Dependency Ordering
    # -------------------------------------------------------------------------
    actions = m.compile_to_actions("FMBD5_Model", analysis=analysis)
    action_types = [a.action_type for a in actions]

    # Index lookups for topological dependency checks
    idx_first_material = min(i for i, a in enumerate(actions) if a.action_type == "material_elastic")
    idx_first_sec_assign = min(i for i, a in enumerate(actions) if a.action_type == "section_assignment")
    idx_first_mesh = min(i for i, a in enumerate(actions) if a.action_type in ("seed_part", "generate_mesh"))
    idx_first_rp = min(i for i, a in enumerate(actions) if a.action_type == "reference_point")
    idx_first_constraint = min(i for i, a in enumerate(actions) if a.action_type in ("rigid_body", "coupling_constraint"))
    idx_first_connector = min(i for i, a in enumerate(actions) if a.action_type in ("connector_section", "wire_connector"))
    idx_first_step = min(i for i, a in enumerate(actions) if a.action_type == "implicit_dynamic_step")
    idx_first_load = min(i for i, a in enumerate(actions) if a.action_type in ("gravity", "concentrated_force"))
    idx_first_output = min(i for i, a in enumerate(actions) if a.action_type in ("field_output", "history_output"))
    idx_job = actions.index(next(a for a in actions if a.action_type == "create_job"))

    # Dependency Order Invariant Checks:
    # 1. Part Materials precede Part Meshing
    assert idx_first_material < idx_first_mesh
    assert idx_first_sec_assign < idx_first_mesh
    # 2. Part Meshing precedes Assembly RPs and Assembly Constraints
    assert idx_first_mesh < idx_first_rp, "Part meshing must precede assembly reference points!"
    assert idx_first_mesh < idx_first_constraint, "Part meshing must precede kinematic coupling constraints!"
    # 3. Assembly RPs and Constraints precede Connectors
    assert idx_first_rp < idx_first_connector
    assert idx_first_constraint < idx_first_connector
    # 4. Connectors precede Step
    assert idx_first_connector < idx_first_step
    # 5. Step precedes Loads and Sensor Outputs
    assert idx_first_step < idx_first_load
    assert idx_first_step < idx_first_output
    # 6. Job is at the very end
    assert idx_job == len(actions) - 1

    # -------------------------------------------------------------------------
    # Audit 3: Multi-Ground Interface Resolution
    # -------------------------------------------------------------------------
    ground_rps = [a for a in actions if a.action_type == "reference_point" and "RP_GROUND" in a.parameters["name"]]
    assert len(ground_rps) == 2, "Expected 2 distinct Ground reference points for Pivot and Slider guide!"
    ground_rp_names = {a.parameters["name"] for a in ground_rps}
    assert "RP_GROUND_J_Pivot" in ground_rp_names
    assert "RP_GROUND_J_SliderGuide" in ground_rp_names

    pivot_rp = next(a for a in ground_rps if a.parameters["name"] == "RP_GROUND_J_Pivot")
    slider_rp = next(a for a in ground_rps if a.parameters["name"] == "RP_GROUND_J_SliderGuide")
    assert pivot_rp.parameters["coordinates"] == (0.0, 0.0, 0.0)
    assert slider_rp.parameters["coordinates"] == (400.0, 0.0, 0.0)

    # Verify both Ground anchors receive independent fixed BCs
    ground_bcs = [a for a in actions if a.action_type == "displacement_bc" and "BC-Ground" in a.parameters["name"]]
    assert len(ground_bcs) == 2
    bc_regions = {a.parameters["region_expression"] for a in ground_bcs}
    assert any("RP_GROUND_J_Pivot" in r for r in bc_regions)
    assert any("RP_GROUND_J_SliderGuide" in r for r in bc_regions)

    # -------------------------------------------------------------------------
    # Audit 4: Dual-Interface Flexible Body Automatic Resolution
    # -------------------------------------------------------------------------
    conn_elbow = next(a for a in actions if a.action_type == "wire_connector" and a.parameters["name"] == "Conn-J_Elbow")
    assert conn_elbow.parameters["point1_name"] == "RP_CRANK_ELBOW"
    assert conn_elbow.parameters["point2_name"] == "RP_FLEX_ELBOW", (
        "J_Elbow at location (100,0,0) must automatically resolve to RP_FLEX_ELBOW!"
    )

    conn_wrist = next(a for a in actions if a.action_type == "wire_connector" and a.parameters["name"] == "Conn-J_Wrist")
    assert conn_wrist.parameters["point1_name"] == "RP_FLEX_WRIST", (
        "J_Wrist at location (400,0,0) must automatically resolve to RP_FLEX_WRIST!"
    )
    assert conn_wrist.parameters["point2_name"] == "RP_SLIDER"


def test_joint_semantic_interface_resolution_and_error_handling():
    """Verify semantic interface priority, tolerance bounding, and deterministic error handling."""
    import pytest
    from abaqus_ai_agent.planning.mechanism import MechanismGraph, BodyType

    m = MechanismGraph("SemanticResolutionTest")
    m.add_body("ground", body_type="ground")
    m.add_body("crank", body_type="rigid", ref_point_name="RP_CRANK", ref_point_coords=(0.0, 0.0, 0.0))
    m.add_body("flex_rod", body_type="flexible", part_name="FlexPart", mesh_size=5.0)

    m.add_flexible_interface(
        name="Interface_Alpha",
        body_name="flex_rod",
        interface_region="FaceAlpha",
        ref_point_name="RP_ALPHA",
        ref_point_coords=(100.0, 0.0, 0.0),
    )
    m.add_flexible_interface(
        name="Interface_Beta",
        body_name="flex_rod",
        interface_region="FaceBeta",
        ref_point_name="RP_BETA",
        ref_point_coords=(300.0, 0.0, 0.0),
    )

    # 1. Exact semantic interface match without location
    m.add_joint(
        "J_SemanticMatch",
        joint_type="revolute",
        body_a="crank",
        body_b="flex_rod",
        interface_b_name="Interface_Beta",
    )
    actions = m.compile_to_actions("TestModel")
    wire = next(a for a in actions if a.action_type == "wire_connector" and a.parameters["name"] == "Conn-J_SemanticMatch")
    assert wire.parameters["point2_name"] == "RP_BETA", "Semantic match failed!"

    # 2. Unknown semantic interface name throws ValueError
    m_bad = MechanismGraph("BadSemantic")
    m_bad.add_body("crank", body_type="rigid", ref_point_name="RP_CRANK")
    m_bad.add_body("flex_rod", body_type="flexible")
    m_bad.add_flexible_interface("I1", "flex_rod", "Face1", "RP_1", (0.0, 0.0, 0.0))
    m_bad.add_joint("J_Bad", body_a="crank", body_b="flex_rod", interface_b_name="NonExistentInterface")
    with pytest.raises(ValueError, match="no matching interface found"):
        m_bad.compile_to_actions("TestModel")

    # 3. Geometric tolerance exceeded (> 1.0 mm) throws ValueError
    m_far = MechanismGraph("FarLocation")
    m_far.add_body("crank", body_type="rigid", ref_point_name="RP_CRANK")
    m_far.add_body("flex_rod", body_type="flexible")
    m_far.add_flexible_interface("I1", "flex_rod", "Face1", "RP_1", (0.0, 0.0, 0.0))
    m_far.add_flexible_interface("I2", "flex_rod", "Face2", "RP_2", (100.0, 0.0, 0.0))
    m_far.add_joint("J_Far", body_a="crank", body_b="flex_rod", location=(50.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="No interface found within tolerance"):
        m_far.compile_to_actions("TestModel")

    # 4. Ambiguous equidistant interfaces throw ValueError
    m_ambig = MechanismGraph("AmbiguousLocation")
    m_ambig.add_body("crank", body_type="rigid", ref_point_name="RP_CRANK")
    m_ambig.add_body("flex_rod", body_type="flexible")
    m_ambig.add_flexible_interface("I1", "flex_rod", "Face1", "RP_1", (0.0, 0.0, 0.0))
    m_ambig.add_flexible_interface("I2", "flex_rod", "Face2", "RP_2", (0.0, 0.0, 0.0))
    m_ambig.add_joint("J_Ambig", body_a="crank", body_b="flex_rod", location=(0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="Ambiguous interfaces"):
        m_ambig.compile_to_actions("TestModel")


def test_mechanism_graph_flexible_to_flexible_direct_coupling():
    """Verify FMBD-6 topology and full-stack compilation for direct flexible-to-flexible joint."""
    from abaqus_ai_agent.planning.mechanism import MechanismAnalysisSpec

    m = MechanismGraph("FlexibleToFlexibleDoublePendulum")

    # 1. Ground body
    m.add_body("ground", body_type="ground", ref_point_name="RP_GROUND", ref_point_coords=(0.0, 0.0, 0.0))

    # 2. Two C3D8R flexible beam links without any intermediate rigid body
    m.add_body(
        name="flex_arm1",
        body_type="flexible",
        part_name="Part-Arm1",
        instance_name="Arm1-1",
        youngs_modulus=70000.0,
        poisson_ratio=0.33,
        density=2.7e-9,
        mesh_size=5.0,
        element_code="C3D8R",
        element_library="STANDARD",
        part_cells_set="Arm1Cells",
    )
    m.add_body(
        name="flex_arm2",
        body_type="flexible",
        part_name="Part-Arm2",
        instance_name="Arm2-1",
        youngs_modulus=70000.0,
        poisson_ratio=0.33,
        density=2.7e-9,
        mesh_size=5.0,
        element_code="C3D8R",
        element_library="STANDARD",
        part_cells_set="Arm2Cells",
    )

    # 3. Flexible Interfaces on both arms
    # Arm1: Root interface (to ground) and Tip interface (to Arm2)
    m.add_flexible_interface(
        name="Coupling_Arm1_Root",
        body_name="flex_arm1",
        interface_region="Arm1RootFace",
        ref_point_name="RP_ARM1_ROOT",
        ref_point_coords=(0.0, 0.0, 0.0),
        coupling_type="KINEMATIC",
    )
    m.add_flexible_interface(
        name="Coupling_Arm1_Tip",
        body_name="flex_arm1",
        interface_region="Arm1TipFace",
        ref_point_name="RP_ARM1_TIP",
        ref_point_coords=(200.0, 0.0, 0.0),
        coupling_type="KINEMATIC",
    )

    # Arm2: Root interface (to Arm1) and Tip free end / payload
    m.add_flexible_interface(
        name="Coupling_Arm2_Root",
        body_name="flex_arm2",
        interface_region="Arm2RootFace",
        ref_point_name="RP_ARM2_ROOT",
        ref_point_coords=(200.0, 0.0, 0.0),
        coupling_type="KINEMATIC",
    )

    # 4. Kinematic joints
    # J1: Ground to Arm1 Root (Rigid-Flexible)
    m.add_joint(
        name="J_Ground_Arm1",
        joint_type="revolute",
        body_a="ground",
        body_b="flex_arm1",
        location=(0.0, 0.0, 0.0),
        interface_b_name="Coupling_Arm1_Root",
    )

    # J2: Direct Flexible-to-Flexible joint linking Arm1 Tip and Arm2 Root
    m.add_joint(
        name="J_Arm1_Arm2",
        joint_type="revolute",
        body_a="flex_arm1",
        body_b="flex_arm2",
        location=(200.0, 0.0, 0.0),
        interface_a_name="Coupling_Arm1_Tip",
        interface_b_name="Coupling_Arm2_Root",
    )

    # 5. External gravity load
    m.add_load("Gravity", target_name="assembly", load_type="gravity", vector=(0.0, -9810.0, 0.0))

    # 6. Topological validation audit
    report = m.validate_topology()
    assert report.is_valid is True
    assert report.num_bodies == 3
    assert report.num_rigid_bodies == 0
    assert report.num_flexible_bodies == 2
    assert report.num_joints == 2
    assert report.num_interfaces == 3
    assert report.flexible_flexible_joints_count == 1
    assert report.rigid_flexible_joints_count == 1
    assert report.rigid_rigid_joints_count == 0
    assert report.mobility_rigid_spatial == 2
    assert report.mobility_rigid_planar == 2

    # 7. Compilation to strictly-ordered AbaqusActions
    analysis = MechanismAnalysisSpec(
        step_name="Step-Dynamic",
        job_name="FMBD6Job",
        time_period=0.5,
        initial_inc=0.005,
        max_inc=0.01,
        nlgeom=True,
    )
    actions = m.compile_to_actions("FMBD6Model", analysis=analysis)

    # Verify actions sequence and parameters
    action_types = [a.action_type for a in actions]
    assert action_types.count("material_elastic") == 2
    assert action_types.count("solid_section") == 2
    assert action_types.count("section_assignment") == 2
    assert action_types.count("seed_part") == 2
    assert action_types.count("element_type") == 2
    assert action_types.count("generate_mesh") == 2
    assert action_types.count("coupling_constraint") == 3
    assert action_types.count("connector_section") == 1
    assert action_types.count("wire_connector") == 2
    assert "implicit_dynamic_step" in action_types
    assert "gravity" in action_types

    # Specifically verify the direct flexible-to-flexible connector wire endpoints
    wire_ff = next(a for a in actions if a.action_type == "wire_connector" and a.parameters["name"] == "Conn-J_Arm1_Arm2")
    assert wire_ff.parameters["point1_name"] == "RP_ARM1_TIP"
    assert wire_ff.parameters["point2_name"] == "RP_ARM2_ROOT"


def test_fmbd7_dual_flexible_four_bar_closed_loop_compiler_contract():
    """FMBD-7: Declarative compiler contract test for a dual-flexible closed-loop 4-bar mechanism.

    Topology:
      Ground (Dual physical anchors @ A=(0,0,10) and D=(200,0,10))
        |-- Revolute J_Pivot @ (0,0,10) --> Rigid Crank
        |-- Revolute J_Anchor @ (200,0,10) <-- Flexible Rocker (Closed Loop Return)
      Rigid Crank
        |-- Revolute J_Elbow @ (0,100,10) --> Flexible Coupler
      Flexible Coupler (C3D8R Elastic Continuum, L=200mm)
        |-- DIRECT Revolute J_Knee @ (200,100,10) --> Flexible Rocker (Flexible-to-Flexible Direct Joint)
      Flexible Rocker (C3D8R Elastic Continuum, L=100mm)
        |-- Revolute J_Anchor @ (200,0,10) --> Ground D (Closes the 4-bar kinematic loop)

    Key topological attributes verified:
      - num_bodies = 4, num_rigid_bodies = 1, num_flexible_bodies = 2
      - num_joints = 4, closed_loops_count = 1, is_closed_loop = True
      - num_interfaces = 4 (2 on Coupler, 2 on Rocker)
      - num_rigid_rigid_joints = 1 (J_Pivot)
      - num_rigid_flexible_joints = 2 (J_Elbow, J_Anchor)
      - num_flexible_flexible_joints = 1 (J_Knee)
      - 100% compiled to AbaqusActions without any external modeling bypass.
    """
    from abaqus_ai_agent.planning.mechanism import MechanismGraph, MechanismAnalysisSpec

    m = MechanismGraph("FMBD7_DualFlexibleClosedLoopFourBar")

    # 1. Ground body with dual physical anchors
    m.add_body("ground", body_type="ground", ref_point_name="RP_GROUND_A", ref_point_coords=(0.0, 0.0, 10.0))

    # 2. Rigid crank (A=(0,0,10) to B=(0,100,10), length=100mm)
    m.add_body(
        "crank",
        body_type="rigid",
        ref_point_name="RP_CRANK_A",
        ref_point_coords=(0.0, 0.0, 10.0),
        tie_regions=["RP_CRANK_B"],
    )

    # 3. Flexible Coupler (B=(0,100,10) to C=(200,100,10), length=200mm, Aluminum)
    m.add_body(
        "flex_coupler",
        body_type="flexible",
        part_name="CouplerPart",
        instance_name="Coupler-1",
        youngs_modulus=70000.0,
        poisson_ratio=0.33,
        density=2.7e-9,
        mesh_size=10.0,
        element_code="C3D8R",
        part_cells_set="Cells",
    )

    # 4. Flexible Rocker (C=(200,100,10) to D=(200,0,10), length=100mm, Steel/Alloy)
    m.add_body(
        "flex_rocker",
        body_type="flexible",
        part_name="RockerPart",
        instance_name="Rocker-1",
        youngs_modulus=100000.0,
        poisson_ratio=0.30,
        density=4.5e-9,
        mesh_size=10.0,
        element_code="C3D8R",
        part_cells_set="Cells",
    )

    # 5. Flexible Interfaces (Coupling constraints)
    # Coupler interfaces: Root at B, Tip at C
    m.add_flexible_interface(
        name="IFace_Coupler_B",
        body_name="flex_coupler",
        interface_region="CouplerRootFace",
        ref_point_name="RP_COUPLER_B",
        ref_point_coords=(0.0, 100.0, 10.0),
        role="revolute",
        coupling_type="KINEMATIC",
    )
    m.add_flexible_interface(
        name="IFace_Coupler_C",
        body_name="flex_coupler",
        interface_region="CouplerTipFace",
        ref_point_name="RP_COUPLER_C",
        ref_point_coords=(200.0, 100.0, 10.0),
        role="revolute",
        coupling_type="KINEMATIC",
    )

    # Rocker interfaces: Top at C, Bottom at D
    m.add_flexible_interface(
        name="IFace_Rocker_C",
        body_name="flex_rocker",
        interface_region="RockerTopFace",
        ref_point_name="RP_ROCKER_C",
        ref_point_coords=(200.0, 100.0, 10.0),
        role="revolute",
        coupling_type="KINEMATIC",
    )
    m.add_flexible_interface(
        name="IFace_Rocker_D",
        body_name="flex_rocker",
        interface_region="RockerBottomFace",
        ref_point_name="RP_ROCKER_D",
        ref_point_coords=(200.0, 0.0, 10.0),
        role="revolute",
        coupling_type="KINEMATIC",
    )

    # 6. Four kinematic joints forming the closed loop
    # J1: Ground A <-> Crank (Rigid-Rigid)
    m.add_joint(
        "J_Pivot",
        joint_type="revolute",
        body_a="ground",
        body_b="crank",
        location=(0.0, 0.0, 10.0),
        point_b_name="RP_CRANK_A",
        orientation="Csys_HingeZ",
    )

    # J2: Crank <-> Coupler (Rigid-Flexible)
    m.add_joint(
        "J_Elbow",
        joint_type="revolute",
        body_a="crank",
        body_b="flex_coupler",
        location=(0.0, 100.0, 10.0),
        point_a_name="RP_CRANK_B",
        interface_b_name="IFace_Coupler_B",
        orientation="Csys_HingeZ",
    )

    # J3: Coupler <-> Rocker (DIRECT FLEXIBLE-TO-FLEXIBLE JOINT)
    m.add_joint(
        "J_Knee",
        joint_type="revolute",
        body_a="flex_coupler",
        body_b="flex_rocker",
        location=(200.0, 100.0, 10.0),
        interface_a_name="IFace_Coupler_C",
        interface_b_name="IFace_Rocker_C",
        orientation="Csys_HingeZ",
    )

    # J4: Rocker <-> Ground D (Flexible-Rigid / Closed-Loop Ground Anchor)
    m.add_joint(
        "J_Anchor",
        joint_type="revolute",
        body_a="flex_rocker",
        body_b="ground",
        location=(200.0, 0.0, 10.0),
        interface_a_name="IFace_Rocker_D",
        orientation="Csys_HingeZ",
    )

    # 7. Gravity load
    m.add_load("Gravity", target_name="assembly", load_type="gravity", vector=(981.0, -9810.0, 0.0))

    # 8. Topological validation audit
    report = m.validate_topology()
    assert report.is_valid is True, f"Topology invalid: {report.errors}"
    assert report.num_bodies == 4
    assert report.num_rigid_bodies == 1
    assert report.num_flexible_bodies == 2
    assert report.num_joints == 4
    assert report.num_interfaces == 4
    assert report.closed_loops_count == 1
    assert report.is_closed_loop is True
    assert report.num_rigid_rigid_joints == 1
    assert report.num_rigid_flexible_joints == 2
    assert report.num_flexible_flexible_joints == 1

    # 9. Full-stack compilation to Abaqus actions
    analysis = MechanismAnalysisSpec(
        step_name="Step-FMBD7",
        job_name="FMBD7GoldenJob",
        time_period=0.5,
        initial_inc=0.005,
        max_inc=0.01,
        nlgeom=True,
        application="MODERATE_DISSIPATION",
        nohaf=True,
    )
    actions = m.compile_to_actions("FMBD7Model", analysis=analysis)

    action_types = [a.action_type for a in actions]
    assert action_types.count("material_elastic") == 2
    assert action_types.count("solid_section") == 2
    assert action_types.count("section_assignment") == 2
    assert action_types.count("seed_part") == 2
    assert action_types.count("element_type") == 2
    assert action_types.count("generate_mesh") == 2

    # Verify reference points created
    rp_names = [a.parameters["name"] for a in actions if a.action_type == "reference_point"]
    assert "RP_GROUND_J_Pivot" in rp_names
    assert "RP_GROUND_J_Anchor" in rp_names
    assert "RP_CRANK_A" in rp_names
    assert "RP_CRANK_B" in rp_names
    assert "RP_COUPLER_B" in rp_names
    assert "RP_COUPLER_C" in rp_names
    assert "RP_ROCKER_C" in rp_names
    assert "RP_ROCKER_D" in rp_names

    # Verify RigidBody constraint on Crank
    rb_actions = [a for a in actions if a.action_type == "rigid_body"]
    assert len(rb_actions) == 1
    assert rb_actions[0].parameters["name"] == "RB-crank"
    assert "RP_CRANK_A" in rb_actions[0].parameters["ref_point_expression"]
    assert "RP_CRANK_B" in rb_actions[0].parameters["tie_region"]

    # Verify 4 Coupling constraints on 2 flexible bodies
    coupling_actions = [a for a in actions if a.action_type == "coupling_constraint"]
    assert len(coupling_actions) == 4
    coupling_names = {a.parameters["name"] for a in coupling_actions}
    assert coupling_names == {"IFace_Coupler_B", "IFace_Coupler_C", "IFace_Rocker_C", "IFace_Rocker_D"}

    # Verify 4 Wire Connectors
    wire_actions = [a for a in actions if a.action_type == "wire_connector"]
    assert len(wire_actions) == 4
    wires_by_name = {a.parameters["name"]: a for a in wire_actions}

    # Verify J_Pivot (Ground A <-> Crank)
    assert wires_by_name["Conn-J_Pivot"].parameters["point1_name"] == "RP_GROUND_J_Pivot"
    assert wires_by_name["Conn-J_Pivot"].parameters["point2_name"] == "RP_CRANK_A"

    # Verify J_Elbow (Crank <-> Coupler)
    assert wires_by_name["Conn-J_Elbow"].parameters["point1_name"] == "RP_CRANK_B"
    assert wires_by_name["Conn-J_Elbow"].parameters["point2_name"] == "RP_COUPLER_B"

    # Verify J_Knee (DIRECT FLEXIBLE-TO-FLEXIBLE)
    assert wires_by_name["Conn-J_Knee"].parameters["point1_name"] == "RP_COUPLER_C"
    assert wires_by_name["Conn-J_Knee"].parameters["point2_name"] == "RP_ROCKER_C"

    # Verify J_Anchor (Rocker <-> Ground D closed loop)
    assert wires_by_name["Conn-J_Anchor"].parameters["point1_name"] == "RP_ROCKER_D"
    assert wires_by_name["Conn-J_Anchor"].parameters["point2_name"] == "RP_GROUND_J_Anchor"

    # Verify Step and Job
    assert "implicit_dynamic_step" in action_types
    assert "create_job" in action_types

    # Topological Ordering Invariant Checks:
    idx_first_sec = min(i for i, a in enumerate(actions) if a.action_type in ("solid_section", "section_assignment"))
    idx_first_mesh = min(i for i, a in enumerate(actions) if a.action_type in ("seed_part", "generate_mesh"))
    idx_first_rp = min(i for i, a in enumerate(actions) if a.action_type == "reference_point")
    idx_first_coupling = min(i for i, a in enumerate(actions) if a.action_type == "coupling_constraint")
    idx_first_wire = min(i for i, a in enumerate(actions) if a.action_type == "wire_connector")
    idx_step = actions.index(next(a for a in actions if a.action_type == "implicit_dynamic_step"))
    idx_job = actions.index(next(a for a in actions if a.action_type == "create_job"))

    assert idx_first_sec < idx_first_mesh, "Materials/Sections must precede Meshing"
    assert idx_first_mesh < idx_first_coupling, "Meshing must precede Continuum Couplings"
    assert idx_first_rp < idx_first_coupling, "Reference points must precede Couplings"
    assert idx_first_coupling < idx_first_wire, "Couplings must precede Wire Connectors"
    assert idx_first_wire < idx_step, "Connector elements must precede Step creation"
    assert idx_step < idx_job, "Step must precede Job creation"
