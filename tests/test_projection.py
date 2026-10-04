import math
import pytest
from abaqus_ai_agent.contracts.geometry import ViewProjection, ImagePoint
from abaqus_ai_agent.grounding.projection import (
    Ray3D,
    PinholeCamera,
    project_parallel,
    project_perspective,
    project_point,
    unproject_point_to_ray,
    ray_intersects_aabb,
    ray_intersects_plane,
    ray_point_distance,
    select_geometry_by_ray,
    grounded_region_from_ray_selection,
)


def test_parallel_projection_center():
    view = ViewProjection("v", "PARALLEL", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0))
    p = project_point((0, 0, 0), view, 2.0, 2.0)
    assert p is not None
    assert p.x == pytest.approx(0.5)
    assert p.y == pytest.approx(0.5)


def test_parallel_projection_right_and_up():
    view = ViewProjection("v", "PARALLEL", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0))
    right = project_point((1, 0, 0), view, 2.0, 2.0)
    up = project_point((0, 1, 0), view, 2.0, 2.0)
    assert right is not None and up is not None
    assert right.x == pytest.approx(1.0)
    assert right.y == pytest.approx(0.5)
    assert up.x == pytest.approx(0.5)
    assert up.y == pytest.approx(0.0)


def test_view_offset_matches_abaqus_pan_direction():
    view = ViewProjection("v", "PARALLEL", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0))
    p = project_point((0, 0, 0), view, 2.0, 2.0,
                      view_offset_x=0.1, view_offset_y=0.2)
    assert p is not None
    assert p.x == pytest.approx(0.6)
    assert p.y == pytest.approx(0.3)


# --- GA-2A.1: Perspective Camera Model & Projection Matrix Calibration ---

def test_perspective_projection_center():
    view = ViewProjection("v", "PERSPECTIVE", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0))
    p = project_point((0, 0, 0), view, 2.0, 2.0)
    assert p is not None
    assert p.x == pytest.approx(0.5)
    assert p.y == pytest.approx(0.5)


def test_perspective_projection_right_and_up():
    view = ViewProjection("v", "PERSPECTIVE", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0))
    right = project_point((1, 0, 0), view, 2.0, 2.0)
    up = project_point((0, 1, 0), view, 2.0, 2.0)
    assert right is not None and up is not None
    assert right.x == pytest.approx(1.0)
    assert right.y == pytest.approx(0.5)
    assert up.x == pytest.approx(0.5)
    assert up.y == pytest.approx(0.0)


def test_perspective_foreshortening_with_depth():
    # Camera at (0, 0, 10), target at (0, 0, 0), distance d = 10
    # At z = 0 (z_c = 10), x = 1.0 projects to right edge (x = 1.0)
    # At z = 5 (z_c = 5, halfway to camera), x = 0.5 should project to the same right edge (x = 1.0)
    view = ViewProjection("v", "PERSPECTIVE", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0))
    p_halfway = project_point((0.5, 0, 5), view, 2.0, 2.0)
    assert p_halfway is not None
    assert p_halfway.x == pytest.approx(1.0)
    assert p_halfway.y == pytest.approx(0.5)


def test_perspective_point_behind_camera_clipped():
    # Point at (0, 0, 15) is behind camera at (0, 0, 10) looking toward (0, 0, 0)
    view = ViewProjection("v", "PERSPECTIVE", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0))
    p = project_point((0, 0, 15), view, 2.0, 2.0)
    assert p is None


def test_perspective_view_offsets():
    view = ViewProjection("v", "PERSPECTIVE", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0))
    p = project_point((0, 0, 0), view, 2.0, 2.0,
                      view_offset_x=0.1, view_offset_y=0.2)
    assert p is not None
    assert p.x == pytest.approx(0.6)
    assert p.y == pytest.approx(0.3)


def test_perspective_angle_fov_inference():
    # If width/height omitted, perspective_angle in degrees infers view dimensions
    # d = 10, angle = 90 deg -> height = 2 * 10 * tan(45 deg) = 20.0
    view = ViewProjection("v", "PERSPECTIVE", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0),
                          perspective_angle=90.0)
    p = project_point((10, 0, 0), view)
    assert p is not None
    # x = 10 with width = 20 -> x_proj = 10/20 = 0.5 -> screen x = 0.5 + 0.5 = 1.0
    assert p.x == pytest.approx(1.0)


def test_pinhole_camera_matrices():
    cam = PinholeCamera(
        position=(0, 0, 10),
        target=(0, 0, 0),
        up_vector=(0, 1, 0),
        view_width=2.0,
        view_height=2.0,
        image_width=1000,
        image_height=1000,
    )
    assert cam.focal_distance == pytest.approx(10.0)

    f, r, u = cam.camera_basis()
    assert f == pytest.approx((0, 0, -1))
    assert r == pytest.approx((1, 0, 0))
    assert u == pytest.approx((0, 1, 0))

    ext = cam.extrinsic_matrix()
    # Check 4x4 matrix structure
    assert len(ext) == 4 and len(ext[0]) == 4
    assert ext[3] == (0.0, 0.0, 0.0, 1.0)

    intr = cam.intrinsic_matrix()
    assert len(intr) == 3 and len(intr[0]) == 3
    # fx = 1000 * 10 / 2 = 5000
    assert intr[0][0] == pytest.approx(5000.0)
    assert intr[1][1] == pytest.approx(5000.0)
    assert intr[0][2] == pytest.approx(500.0)  # principal point cx
    assert intr[1][2] == pytest.approx(500.0)  # principal point cy


# --- GA-2A.2: Perspective Raycasting & Spatial Selection ---

def test_ray3d_primitives():
    ray = Ray3D(origin=(0, 0, 10), direction=(0, 0, -2))
    # Direction should be auto-normalized to unit vector
    assert ray.direction == pytest.approx((0, 0, -1))
    pt = ray.point_at(10.0)
    assert pt == pytest.approx((0, 0, 0))


def test_unproject_point_to_ray_perspective():
    view = ViewProjection("v", "PERSPECTIVE", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0),
                          view_width=2.0, view_height=2.0)
    # Center click (0.5, 0.5) must produce a ray pointing directly at target (0, 0, 0)
    ray_center = unproject_point_to_ray(ImagePoint(0.5, 0.5), view)
    assert ray_center.origin == pytest.approx((0, 0, 10))
    assert ray_center.direction == pytest.approx((0, 0, -1))
    assert ray_center.point_at(10.0) == pytest.approx((0, 0, 0))

    # Right edge click (1.0, 0.5) must hit (1, 0, 0) at distance along optical axis
    ray_right = unproject_point_to_ray(ImagePoint(1.0, 0.5), view)
    # Ray origin is camera eye
    assert ray_right.origin == pytest.approx((0, 0, 10))
    # Vector from (0,0,10) to (1,0,0) is (1, 0, -10)
    expected_dir = (1.0 / math.sqrt(101.0), 0.0, -10.0 / math.sqrt(101.0))
    assert ray_right.direction == pytest.approx(expected_dir)


def test_unproject_point_to_ray_parallel():
    view = ViewProjection("v", "PARALLEL", 1000, 1000,
                          (0, 0, 10), (0, 0, 0), (0, 1, 0),
                          view_width=2.0, view_height=2.0)
    # For parallel projection, rays are all parallel to forward axis (0, 0, -1)
    # Center ray
    ray_center = unproject_point_to_ray(ImagePoint(0.5, 0.5), view)
    assert ray_center.origin == pytest.approx((0, 0, 10))
    assert ray_center.direction == pytest.approx((0, 0, -1))

    # Right edge ray
    ray_right = unproject_point_to_ray(ImagePoint(1.0, 0.5), view)
    assert ray_right.origin == pytest.approx((1.0, 0.0, 10))
    assert ray_right.direction == pytest.approx((0, 0, -1))


def test_ray_intersects_aabb_hit_and_miss():
    ray = Ray3D(origin=(0, 0, 10), direction=(0, 0, -1))
    box_min = (-1.0, -1.0, -1.0)
    box_max = (1.0, 1.0, 1.0)

    # Direct hit: enters at z=1 (t=9), exits at z=-1 (t=11)
    hit = ray_intersects_aabb(ray, box_min, box_max)
    assert hit is not None
    assert hit[0] == pytest.approx(9.0)
    assert hit[1] == pytest.approx(11.0)

    # Miss: box shifted to x in [5, 6]
    miss = ray_intersects_aabb(ray, (5.0, -1.0, -1.0), (6.0, 1.0, 1.0))
    assert miss is None

    # Box behind ray: z in [15, 20]
    behind = ray_intersects_aabb(ray, (-1.0, -1.0, 15.0), (1.0, 1.0, 20.0))
    assert behind is None


def test_ray_intersects_plane_front_and_backface():
    ray = Ray3D(origin=(0, 0, 10), direction=(0, 0, -1))
    # Front-facing plane at z = 0 with normal pointing towards camera (0, 0, 1)
    t_front = ray_intersects_plane(ray, (0, 0, 0), (0, 0, 1), backface_cull=True)
    assert t_front is not None
    assert t_front == pytest.approx(10.0)

    # Back-facing plane with normal pointing away from camera (0, 0, -1)
    t_back = ray_intersects_plane(ray, (0, 0, 0), (0, 0, -1), backface_cull=True)
    assert t_back is None


def test_ray_point_distance():
    ray = Ray3D(origin=(0, 0, 10), direction=(0, 0, -1))
    # Point at (0.3, 0, 5) is 0.3 units away from ray at depth t = 5
    dist, t = ray_point_distance(ray, (0.3, 0.0, 5.0))
    assert dist == pytest.approx(0.3)
    assert t == pytest.approx(5.0)


# --- GA-2A.3 & GA-2A.4: Spatial Selection & GroundedRegion Bridge ---

def test_select_geometry_by_ray_z_buffer_depth_sorting():
    # Cast a ray along -Z
    ray = Ray3D(origin=(0, 0, 10), direction=(0, 0, -1))

    # Two candidate surfaces along the ray:
    # Face A at depth z = 4 (depth t = 6, nearer)
    # Face B at depth z = -2 (depth t = 12, occluded / farther)
    # Face C is back-facing (normal pointing away)
    candidates = [
        {
            "name": "Face_B_Far",
            "entity_type": "Face",
            "point": (0.05, 0.0, -2.0),
            "normal": (0.0, 0.0, 1.0),
            "index": 102,
        },
        {
            "name": "Face_A_Near",
            "entity_type": "Face",
            "point": (0.02, 0.0, 4.0),
            "normal": (0.0, 0.0, 1.0),
            "index": 101,
        },
        {
            "name": "Face_C_Backfacing",
            "entity_type": "Face",
            "point": (0.01, 0.0, 5.0),
            "normal": (0.0, 0.0, -1.0),  # Back-facing!
            "index": 103,
        },
    ]

    selected = select_geometry_by_ray(ray, candidates, max_distance=0.5, backface_cull=True)

    # Face C should be culled
    assert len(selected) == 2
    # Z-buffer sort: Face A (t=6) must precede Face B (t=12)
    assert selected[0]["name"] == "Face_A_Near"
    assert selected[0]["selected"] is True
    assert selected[1]["name"] == "Face_B_Far"
    assert selected[1].get("selected") is not True

    # Bridge to GroundedRegion
    region = grounded_region_from_ray_selection(selected[0], target_semantic="FIXED_FACE")
    assert region.status == "RESOLVED"
    assert region.target_semantic == "FIXED_FACE"
    assert region.entity_type == "Face"
    assert region.entity_ids == ("101",)
    assert region.anchor_point == (0.02, 0.0, 4.0)
    assert region.confidence > 0.9
    assert len(region.evidence) == 3


def test_ga2a_viewport_click_to_compiler_action_plan_e2e():
    """Verify GA-2A full chain: screen click -> raycast -> GroundedRegion -> compiler ActionPlan."""
    from abaqus_ai_agent.contracts.geometry import resolve_region
    from abaqus_ai_agent.planning.compiler import (
        compile_intent_to_actions,
        IntentGeometrySpec,
        IntentStepSpec,
        IntentBoundarySpec,
        IntentLoadSpec,
        IntentMeshSpec,
    )
    from abaqus_ai_agent.contracts.material import MaterialDefinition, ElasticProperties
    from abaqus_ai_agent.validation.preflight import preflight_action, preflight_plan

    # 1. Viewport camera looking down Z towards model
    view = ViewProjection(
        viewport_id="Viewport: 1",
        projection_type="PERSPECTIVE",
        image_width=1000,
        image_height=1000,
        camera_position=(50.0, 10.0, 200.0),
        camera_target=(50.0, 10.0, 50.0),
        up_vector=(0.0, 1.0, 0.0),
        view_width=100.0,
        view_height=100.0,
    )

    # 2. Simulated user clicks center of screen on Root Face at (50, 10, 0)
    click = ImagePoint(0.5, 0.5)
    ray = unproject_point_to_ray(click, view)
    assert ray.direction == pytest.approx((0, 0, -1))

    # Candidate faces
    candidates = [
        {
            "name": "RootFace",
            "entity_type": "Face",
            "point": (50.0, 10.0, 0.0),
            "normal": (0.0, 0.0, 1.0),
            "index": 1,
        },
        {
            "name": "SideFace",
            "entity_type": "Face",
            "point": (0.0, 10.0, 50.0),
            "normal": (-1.0, 0.0, 0.0),
            "index": 2,
        },
    ]

    selected = select_geometry_by_ray(ray, candidates, max_distance=10.0)
    assert len(selected) > 0
    assert selected[0]["name"] == "RootFace"
    assert selected[0]["selected"] is True

    # 3. Create GroundedRegion
    grounded_region = grounded_region_from_ray_selection(selected[0], target_semantic="FIXED_ROOT")
    assert grounded_region.status == "RESOLVED"
    assert grounded_region.anchor_point == (50.0, 10.0, 0.0)

    # 4. Resolve canonical region reference
    region_ref = resolve_region(grounded_region, instance_name="BeamPart-1")
    assert region_ref.kind == "grounded_region"
    assert "findAt(((50.0, 10.0, 0.0),))" in region_ref.expression

    # 5. Compile into ActionPlan
    geom = IntentGeometrySpec(shape="cantilever_box", length=100.0, width=20.0, height=10.0)
    mat = MaterialDefinition(
        name="Steel",
        unit_system="MM_N_MPA",
        elastic=ElasticProperties(youngs_modulus=210e3, poisson_ratio=0.3),
    )
    step = IntentStepSpec(name="StaticLoad", time_period=1.0)
    bcs = [IntentBoundarySpec(name="EncastreRoot", bc_type="ENCASTRE", region="FIXED_ROOT")]
    loads = [IntentLoadSpec(name="TipPressure", load_type="pressure", magnitude=5.0, region="FIXED_ROOT")]

    plan = compile_intent_to_actions(
        model_name="RaycastModel",
        part_name="BeamPart",
        job_name="RaycastJob",
        geometry=geom,
        material=mat,
        step=step,
        bcs=bcs,
        loads=loads,
        mesh=IntentMeshSpec(global_size=5.0),
        grounded_regions={"FIXED_ROOT": grounded_region},
    )

    assert plan.model_name == "RaycastModel"
    assert plan.job_name == "RaycastJob"
    assert "findAt(((50.0, 10.0, 0.0),))" in plan.cae_script
    assert "EncastreBC" in plan.cae_script
    assert "Pressure" in plan.cae_script

    # 6. Verify preflight checks on all generated actions
    for action in plan.actions:
        pf = preflight_action(action)
        assert pf.passed is True, f"Preflight failed on action {action.action_type}: {pf.blockers}"
