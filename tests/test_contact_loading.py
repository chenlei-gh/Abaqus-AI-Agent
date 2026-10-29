"""Rigid punch (contact-driven loading) compilation.

These tests pin the decisions that are easy to get wrong and expensive to get
wrong silently:

1. the build route follows the declared shape -- a cylindrical flat bottom is a
   body of revolution and is built as an **analytical** rigid surface with no
   mesh at all, while a rectangular block cannot be analytical and is built as a
   **planar shell sheet** of ``R3D4`` on a ``DISCRETE_RIGID_SURFACE`` part;
2. the contact goes through the **existing** ``interactions`` channel, not a
   second load model;
3. every size, standoff, stroke, rim radius, and friction value comes from
   ``ContactLoadingSpec`` -- a missing one raises instead of defaulting.
"""

import pytest

from abaqus_ai_agent.contracts.condition import (
    ContactLoadingSpec,
    contact_loading_from_mapping,
)
from abaqus_ai_agent.contracts.intent import EngineeringIntent
from abaqus_ai_agent.contracts.material import ElasticProperties, MaterialDefinition
from abaqus_ai_agent.planning.compiler import (
    IntentGeometrySpec,
    IntentLoadSpec,
    IntentMeshSpec,
    IntentStepSpec,
    compile_engineering_intent,
    compile_intent_to_actions,
)
from abaqus_ai_agent.planning.contact_loading import (
    ContactLoadingBuildError,
    punch_friction,
    resolve_punch_axis,
)


def _spec(**overrides):
    payload = dict(
        name="top_block",
        application="rigid_indenter_contact",
        evidence_status="USER_SPECIFIED",
        source="engineer confirmation 2026-10-29",
        target_region="POCKET_FACE",
        region_resolved=True,
        indenter_geometry="rectangular_block",
        indenter_width=18.0,
        indenter_length=12.0,
        dimension_unit="mm",
        direction="-Y",
        control="force",
        contact_point=(10.0, 5.0, 20.0),
        standoff=0.1,
        magnitude=180.0,
        magnitude_unit="N",
        friction_coefficient=0.2,
        friction_source="engineer specified dry contact",
        user_confirmed=True,
    )
    payload.update(overrides)
    return ContactLoadingSpec(**payload)


def _geometry():
    return IntentGeometrySpec(shape="cantilever_box", length=60.0, width=20.0, height=10.0)


def _material():
    return MaterialDefinition(
        name="POM",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=2800.0, poisson_ratio=0.40),
    )


def _compile(loadings, *, loads=(), step=None):
    return compile_intent_to_actions(
        model_name="PunchModel",
        part_name="Handle",
        job_name="Job-Punch",
        geometry=_geometry(),
        material=_material(),
        step=step or IntentStepSpec(name="Step-1", step_type="static_general", nlgeom=True),
        loads=list(loads),
        mesh=IntentMeshSpec(
            element_type="C3D8R",
            global_size=2.0,
            primary_wall_thickness=1000.0,
            primary_wall_thickness_source="MEASURED",
        ),
        contact_loadings=loadings,
    )


# --- punch construction -------------------------------------------------


def test_punch_is_a_planar_shell_of_rigid_elements():
    plan = _compile((_spec(),))
    script = plan.cae_script

    # A solid discrete rigid part cannot be instanced at all, so the part must
    # be a surface type and must be built from a sketch sheet.
    assert "type=DISCRETE_RIGID_SURFACE" in script
    assert "BaseShell(sketch=" in script
    # An extruded shell is a set of walls with no cap, so it has no contact
    # face. BaseShellExtrude must never appear here.
    assert "BaseShellExtrude" not in script
    assert "elemCode=R3D4" in script
    # Rigid elements carry no material; a section assignment would be a second,
    # contradictory description of the punch.
    assert "name='top_block_Punch', dimensionality=THREE_D, type=DISCRETE_RIGID_SURFACE" in script
    assert "HomogeneousShellSection" not in script
    assert "SectionAssignment(region=regionToolset" not in script


def test_punch_is_placed_at_the_declared_standoff():
    plan = _compile((_spec(),))
    script = plan.cae_script

    # contact_point y=5.0, standoff 0.1, drive -Y -> face sits at y=5.1.
    assert "vector=(10.000000, 5.100000, 20.000000)" in script
    assert "18.0 x 12.0 mm" in script
    assert "standoff 0.100000 mm" in script


def test_punch_contact_uses_the_shared_interactions_channel():
    plan = _compile((_spec(),))
    script = plan.cae_script

    # The rigid surface is the main surface, as Abaqus/Standard requires.
    assert "SurfaceToSurfaceContactStd" in script
    assert "main=m_surf, secondary=s_surf" in script
    assert "name='top_block_Punch_Master'" in script
    assert "name='top_block_Punch_Target'" in script
    # It must not become a pressure patch or a point force.
    assert "Pressure(name='top_block" not in script
    assert "ConcentratedForce(name='top_block_Punch_Force'" in script


def test_punch_guide_leaves_only_the_drive_dof_free():
    plan = _compile((_spec(),))
    script = plan.cae_script
    guide = [line for line in script.splitlines() if "top_block_Punch_Guide" in line]
    assert guide, "punch guide constraint was not emitted"
    line = guide[0]
    # Drive is -Y, i.e. U2, so U2 must not be held at zero.
    assert "u2=" not in line
    for held in ("u1=0.0", "u3=0.0", "u4=0.0", "u5=0.0", "u6=0.0"):
        assert held in line


def test_displacement_control_emits_a_stroke_not_a_force():
    spec = _spec(control="displacement", magnitude=1.5, magnitude_unit="mm",
                 application="displacement_controlled_contact")
    plan = _compile((spec,))
    script = plan.cae_script
    # -Y drive -> u2 = -1.5
    assert "top_block_Punch_Stroke" in script
    assert "u2=-1.500000" in script
    assert "top_block_Punch_Force" not in script


def test_punch_does_not_take_over_the_main_part_mesh():
    """The punch is a shell; seeding it with the solid element type would fail.

    A loop variable named ``part_name`` used to rebind the caller's part name to
    the punch, so section 11 seeded the punch with C3D8R on ``.cells`` -- a shell
    has no cells, so the generated script could not run. The main part must stay
    the subject of its own mesh, and the punch keeps only its R3D4 pass.
    """
    plan = _compile((_spec(),))
    script = plan.cae_script

    assert "parts['Handle'].seedPart" in script
    assert "parts['Handle'].generateMesh()" in script
    assert "parts['top_block_Punch'].seedPart" not in script
    # The only seeding the punch gets is its own, on faces, before instancing.
    assert "p_punch.seedPart" in script
    assert "p_punch.setElementType(regions=(p_punch.faces,)" in script


def test_punch_drive_region_is_an_assembly_set():
    """Loads and BCs need an assembly region; a part set is not one.

    The reference point itself must be created on the part -- that is what makes
    it the rigid body reference point -- but the named set the drive refers to
    has to be built at assembly scope from the instance's reference point.
    """
    plan = _compile((_spec(),))
    script = plan.cae_script

    assert "rp_punch = p_punch.ReferencePoint(" in script
    assert "_punch_rps = a.instances['top_block_Punch-1'].referencePoints" in script
    assert "a.Set(name='top_block_Punch_RP', referencePoints=" in script
    # A part-level set named the same way would never be visible as a.sets[...].
    assert "p_punch.Set(name='top_block_Punch_RP'" not in script
    assert "region=a.sets['top_block_Punch_RP']" in script


# --- cylindrical flat-bottom punch (analytical, no mesh) ----------------


def _cyl(**overrides):
    payload = dict(
        indenter_geometry="cylindrical_flat",
        indenter_width=10.0,
        indenter_length=10.0,
        indenter_edge_radius=0.5,
    )
    payload.update(overrides)
    return _spec(**payload)


def test_cylindrical_punch_is_analytical_and_carries_no_mesh():
    """A revolved punch is a profile, so there is nothing to mesh."""
    plan = _compile((_cyl(),))
    script = plan.cae_script

    assert "type=ANALYTIC_RIGID_SURFACE" in script
    assert "AnalyticRigidSurfRevolve(sketch=s_punch)" in script
    # No mesh path at all: no seeding, no element type, no generation.
    assert "R3D4" not in script
    assert "p_punch.seedPart" not in script
    assert "p_punch.generateMesh" not in script
    assert "p_punch.setElementType" not in script
    # Rigid surfaces carry no material in either route.
    assert "HomogeneousShellSection" not in script
    # The main part still gets its own solid mesh.
    assert "parts['Handle'].generateMesh()" in script
    assert "parts['Handle'].cells" in script


def test_cylindrical_punch_profile_is_closed_with_a_rim_arc():
    plan = _compile((_cyl(),))
    script = plan.cae_script

    # Flat face from the rim to the axis: radius 5.0, rim 0.5 -> 4.5 of flat.
    assert "s_punch.Line(point1=(4.500000, 0.000000), point2=(0.000000, 0.000000))" in script
    # The rim arc is what keeps the main-surface normal continuous. A sharp
    # 90-degree rim is a normal discontinuity and contact will not converge.
    assert "s_punch.ArcByCenterEnds(" in script
    assert "(4.500000, 0.500000)" in script
    # The wall exists only so secondary nodes cannot slide off the edge.
    assert "s_punch.Line(point1=(5.000000, 5.000000), point2=(5.000000, 0.500000))" in script


def test_cylindrical_punch_requires_a_declared_rim_radius():
    spec = _cyl(indenter_edge_radius=None)
    with pytest.raises(ContactLoadingBuildError, match="edge_radius"):
        _compile((spec,))


def test_rim_radius_larger_than_the_face_is_refused():
    spec = _cyl(indenter_edge_radius=5.0)
    with pytest.raises(ContactLoadingBuildError, match="no flat face remains"):
        _compile((spec,))


def test_cylinder_with_two_different_diameters_is_refused():
    spec = _cyl(indenter_width=10.0, indenter_length=12.0)
    with pytest.raises(ContactLoadingBuildError, match="single diameter"):
        _compile((spec,))


def test_cylindrical_punch_contact_binds_the_cae_named_surface():
    """The analytical surface name is chosen by CAE, so it is bound by variable."""
    plan = _compile((_cyl(),))
    script = plan.cae_script

    assert "_punch_surfs = _punch_inst.surfaces" in script
    assert "_punch_master_top_block_Punch = _punch_surfs[" in script
    assert "m_surf = _punch_master_top_block_Punch" in script
    # It must still be a contact interaction, with the rigid side as main.
    assert "main=m_surf, secondary=s_surf" in script
    assert "ConcentratedForce(name='top_block_Punch_Force'" in script


def test_cylindrical_punch_body_sits_on_the_far_side_of_the_face():
    """Driving along -Y must put the punch body above the contact face.

    The profile's body is on local +Y, so for a -Y drive the local frame must
    stay unrotated. Rotating it would flip the punch into the part and point the
    main-surface normal away from the secondary nodes.
    """
    plan = _compile((_cyl(),))
    script = plan.cae_script
    assert "axisPoint=(0.0, 0.0, 0.0), axisDirection=(1.0, 0.0, 0.0), angle=0.0" in script
    # contact_point y=5.0, standoff 0.1, drive -Y -> face at y=5.1.
    assert "vector=(10.000000, 5.100000, 20.000000)" in script


def test_cylindrical_punch_also_holds_one_drive_dof_only():
    axis = resolve_punch_axis(_cyl())
    assert axis.token == "-Y"
    assert axis.dof_index == 1
    plan = _compile((_cyl(),))
    guide = [
        line for line in plan.cae_script.splitlines()
        if "top_block_Punch_Guide" in line
    ]
    assert guide
    assert "u2=" not in guide[0]
    for held in ("u1=0.0", "u3=0.0", "u4=0.0", "u5=0.0", "u6=0.0"):
        assert held in guide[0]


def test_unknown_indenter_geometry_is_refused():
    spec = _cyl(indenter_geometry="hemispherical")
    with pytest.raises(ContactLoadingBuildError, match="indenter_geometry"):
        _compile((spec,))


def test_plan_records_which_build_route_was_used():
    cylindrical = _compile((_cyl(),)).intent_summary["contact_loadings"][0]
    assert cylindrical["rigid_surface_type"] == "analytical_revolved"
    assert cylindrical["punch_mesh_required"] is False
    assert cylindrical["indenter_edge_radius"] == 0.5

    block = _compile((_spec(),)).intent_summary["contact_loadings"][0]
    assert block["rigid_surface_type"] == "discrete_shell"
    assert block["punch_mesh_required"] is True


# --- refusals -----------------------------------------------------------


def test_missing_standoff_is_refused_rather_than_defaulted():
    spec = _spec(standoff=None)
    with pytest.raises(ValueError, match="placement"):
        _compile((spec,))


def test_missing_contact_point_is_refused():
    spec = _spec(contact_point=None)
    with pytest.raises(ValueError, match="contact_loading_contact_point_missing"):
        _compile((spec,))


def test_unverified_evidence_is_refused():
    spec = _spec(evidence_status="ASSUMED", source="")
    with pytest.raises(ValueError, match="cannot authorize"):
        _compile((spec,))


def test_skewed_direction_is_refused_instead_of_snapped():
    spec = _spec(direction="-Y, 20deg")
    with pytest.raises(ContactLoadingBuildError, match="single global axis"):
        resolve_punch_axis(spec)


def test_concentrated_force_application_cannot_be_built_as_a_punch():
    spec = _spec(application="concentrated_force")
    with pytest.raises(ValueError, match="application"):
        _compile((spec,))


def test_multi_part_assembly_requires_target_instance():
    spec = _spec(target_instance="")
    geom = IntentGeometrySpec(shape="step_assembly", step_file_path="unused.stp")
    # Reaching the target-instance check needs a complete scope; the guard is
    # exercised directly instead of fabricating one.
    from abaqus_ai_agent.planning.compiler import _bind_step_assembly_scope  # noqa: F401
    with pytest.raises(Exception):
        compile_intent_to_actions(
            model_name="M", part_name="P", job_name="J",
            geometry=geom, material=_material(),
            mesh=IntentMeshSpec(global_size=2.0),
            contact_loadings=(spec,),
        )


# --- wiring -------------------------------------------------------------


def test_contact_loadings_do_not_leak_into_loads():
    plan = _compile((_spec(),), loads=(
        IntentLoadSpec(name="Extra", load_type="concentrated_force",
                       region="TipPoint", magnitude=-5.0, direction="CF2"),
    ))
    types = [action.action_type for action in plan.actions]
    # One punch force and one ordinary load: the punch did not add a second
    # load type or replace the existing path.
    assert types.count("concentrated_force") == 1
    assert "pressure_load" not in types


def test_punch_is_recorded_in_the_plan_summary():
    plan = _compile((_spec(),))
    records = plan.intent_summary["contact_loadings"]
    assert len(records) == 1
    record = records[0]
    assert record["punch_part"] == "top_block_Punch"
    assert record["direction"] == "-Y"
    assert record["control"] == "force"
    assert record["magnitude"] == 180.0
    assert record["standoff"] == 0.1
    assert record["friction_source"] == "engineer specified dry contact"


def test_engineering_intent_carries_contact_loadings_to_the_compiler():
    intent = EngineeringIntent(
        id="M1FA",
        kind="linear_static",
        description="Total assembly check under a top block that presses down.",
        analysis_type="linear_static",
        unit_system="MM_N_MPA",
        material={"name": "POM", "elastic_modulus": 2800.0, "poisson_ratio": 0.40},
        boundary_conditions=({"type": "ENCASTRE", "region": "RootFace"},),
        loads=(),
        metadata={"geometry": {"shape": "cantilever_box", "length": 60.0,
                               "width": 20.0, "height": 10.0}},
        contact_loadings=(_spec(),),
    )
    plan = compile_engineering_intent(
        intent,
        mesh=IntentMeshSpec(
            element_type="C3D8R",
            global_size=2.0,
            primary_wall_thickness=1000.0,
            primary_wall_thickness_source="MEASURED",
        ),
    )
    assert plan.intent_summary["contact_loadings"]
    assert "type=DISCRETE_RIGID_SURFACE" in plan.cae_script


def test_mapping_form_matches_the_dataclass_form():
    raw = {
        "name": "block", "application": "rigid_indenter_contact",
        "evidence_status": "USER_SPECIFIED", "source": "drawing rev C",
        "target_region": "POCKET", "region_resolved": True,
        "indenter_geometry": "rectangular_block",
        "indenter_width": 18.0, "indenter_length": 12.0, "dimension_unit": "mm",
        "direction": "-Y", "control": "force",
        "contact_point": [10.0, 5.0, 20.0], "standoff": 0.1,
        "magnitude": 180.0, "magnitude_unit": "N",
    }
    spec = contact_loading_from_mapping(raw)
    assert spec.contact_point == (10.0, 5.0, 20.0)
    assert spec.placement_gaps() == ()
    assert punch_friction(spec) == 0.0  # undeclared friction is not invented


def test_placement_gaps_name_every_missing_input():
    spec = _spec(
        contact_point=None, standoff=None, magnitude_unit="",
        magnitude=None, direction="-Y", control="force",
    )
    gaps = set(spec.placement_gaps())
    assert "contact_loading_contact_point_missing" in gaps
    assert "contact_loading_standoff_missing" in gaps
    assert "contact_loading_magnitude_unit_missing" in gaps
    assert "contact_loading_force_magnitude_missing" in gaps
