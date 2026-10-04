import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..contracts.geometry import ImagePoint, ViewProjection
from .feature_grounding import GroundedRegion


def _normalize(v: Sequence[float]) -> Tuple[float, float, float]:
    n = math.sqrt(sum(x * x for x in v))
    if n == 0.0:
        raise ValueError("zero-length vector")
    return tuple(x / n for x in v)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _cross(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    return tuple(x - y for x, y in zip(a, b))


def _add(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    return tuple(x + y for x, y in zip(a, b))


def _scale(v: Sequence[float], s: float) -> Tuple[float, float, float]:
    return tuple(x * s for x in v)


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


@dataclass(frozen=True)
class Ray3D:
    """3D spatial ray defined by origin and unit direction vector."""
    origin: Tuple[float, float, float]
    direction: Tuple[float, float, float]

    def __post_init__(self):
        if len(self.origin) != 3 or len(self.direction) != 3:
            raise ValueError("origin and direction must be 3D coordinates")
        n = math.sqrt(sum(x * x for x in self.direction))
        if abs(n - 1.0) > 1e-4:
            if n == 0.0:
                raise ValueError("zero-length ray direction")
            object.__setattr__(
                self, "direction", tuple(x / n for x in self.direction)
            )

    def point_at(self, t: float) -> Tuple[float, float, float]:
        """Evaluate 3D coordinate along the ray at parametric distance t."""
        return (
            self.origin[0] + t * self.direction[0],
            self.origin[1] + t * self.direction[1],
            self.origin[2] + t * self.direction[2],
        )


def project_parallel(
    point: Tuple[float, float, float],
    camera_position: Tuple[float, float, float],
    camera_target: Tuple[float, float, float],
    up_vector: Tuple[float, float, float],
    width: float,
    height: float,
    view_offset_x: float = 0.0,
    view_offset_y: float = 0.0,
) -> Optional[ImagePoint]:
    """Project a model point using an Abaqus PARALLEL View.

    Returned coordinates use image convention: (0, 0) is top-left.
    Abaqus documents positive viewOffsetX as panning the model right and
    positive viewOffsetY as panning the model upward.
    """
    if width <= 0.0 or height <= 0.0:
        raise ValueError("projection width and height must be positive")

    forward = _normalize(
        tuple(t - p for p, t in zip(camera_position, camera_target))
    )
    up = _normalize(up_vector)
    right = _normalize(_cross(forward, up))
    up = _normalize(_cross(right, forward))
    delta = tuple(p - t for p, t in zip(point, camera_target))

    x = 0.5 + _dot(delta, right) / width + view_offset_x
    y_model = 0.5 + _dot(delta, up) / height + view_offset_y
    y = 1.0 - y_model

    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None
    return ImagePoint(x, y)


def project_perspective(
    point: Tuple[float, float, float],
    camera_position: Tuple[float, float, float],
    camera_target: Tuple[float, float, float],
    up_vector: Tuple[float, float, float],
    width: float,
    height: float,
    view_offset_x: float = 0.0,
    view_offset_y: float = 0.0,
    near_plane: float = 1e-4,
    far_plane: float = 1e6,
) -> Optional[ImagePoint]:
    """Project a model point using an Abaqus PERSPECTIVE View.

    Returned coordinates use image convention: (0, 0) is top-left, (1, 1) bottom-right.
    Abaqus documents positive viewOffsetX as panning the model right and
    positive viewOffsetY as panning the model upward.
    Points behind the camera (z_c <= near_plane) or beyond far_plane return None.
    """
    if width <= 0.0 or height <= 0.0:
        raise ValueError("projection width and height must be positive")

    d = _norm(_sub(camera_target, camera_position))
    if d == 0.0:
        raise ValueError("camera position and target cannot coincide")

    forward = _normalize(_sub(camera_target, camera_position))
    up_nom = _normalize(up_vector)
    right = _normalize(_cross(forward, up_nom))
    up = _normalize(_cross(right, forward))

    delta = _sub(point, camera_position)
    z_c = _dot(delta, forward)

    if z_c < near_plane or z_c > far_plane:
        return None

    x_c = _dot(delta, right)
    y_c = _dot(delta, up)

    scale = d / z_c
    x_proj = x_c * scale
    y_proj = y_c * scale

    x = 0.5 + x_proj / width + view_offset_x
    y_model = 0.5 + y_proj / height + view_offset_y
    y = 1.0 - y_model

    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None
    return ImagePoint(x, y)


@dataclass(frozen=True)
class PinholeCamera:
    """Calibrated pinhole perspective camera model for Abaqus CAE viewport.

    Coordinates:
    - position: camera optical center in model coordinates
    - target: camera focus / look-at target in model coordinates
    - up_vector: nominal camera upward vector
    - view_width: physical visible width at target distance
    - view_height: physical visible height at target distance
    - view_offset_x: normalized horizontal pan offset (positive pans model right)
    - view_offset_y: normalized vertical pan offset (positive pans model up)
    - perspective_angle: vertical field of view angle (degrees)
    - near_plane: near clipping plane distance along forward view axis
    - far_plane: far clipping plane distance along forward view axis
    """
    position: Tuple[float, float, float]
    target: Tuple[float, float, float]
    up_vector: Tuple[float, float, float]
    view_width: float
    view_height: float
    view_offset_x: float = 0.0
    view_offset_y: float = 0.0
    perspective_angle: Optional[float] = None
    near_plane: float = 1e-4
    far_plane: float = 1e6
    image_width: int = 1000
    image_height: int = 1000

    def __post_init__(self):
        if self.view_width <= 0.0 or self.view_height <= 0.0:
            raise ValueError("view width and height must be positive")
        if self.near_plane <= 0.0 or self.far_plane <= self.near_plane:
            raise ValueError("invalid clipping planes: near must be > 0 and < far")

    @property
    def focal_distance(self) -> float:
        """Distance from camera position to target."""
        return _norm(_sub(self.target, self.position))

    def camera_basis(self) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]:
        """Orthonormal camera coordinate axes: (forward, right, up)."""
        forward = _normalize(_sub(self.target, self.position))
        up_nom = _normalize(self.up_vector)
        right = _normalize(_cross(forward, up_nom))
        up = _normalize(_cross(right, forward))
        return forward, right, up

    def extrinsic_matrix(self) -> Tuple[Tuple[float, float, float, float], ...]:
        """4x4 world-to-camera extrinsic matrix [R | -R * position]."""
        f, r, u = self.camera_basis()
        t_r = -_dot(r, self.position)
        t_u = -_dot(u, self.position)
        t_f = -_dot(f, self.position)
        return (
            (r[0], r[1], r[2], t_r),
            (u[0], u[1], u[2], t_u),
            (f[0], f[1], f[2], t_f),
            (0.0, 0.0, 0.0, 1.0),
        )

    def intrinsic_matrix(self) -> Tuple[Tuple[float, float, float], ...]:
        """3x3 camera intrinsic matrix K mapping camera coordinates to pixel coordinates."""
        d = self.focal_distance
        fx = self.image_width * d / self.view_width
        fy = self.image_height * d / self.view_height
        cx = self.image_width * (0.5 + self.view_offset_x)
        cy = self.image_height * (0.5 - self.view_offset_y)
        return (
            (fx, 0.0, cx),
            (0.0, fy, cy),
            (0.0, 0.0, 1.0),
        )

    def project(self, point: Tuple[float, float, float]) -> Optional[ImagePoint]:
        """Project a 3D model point to normalized image coordinate (ImagePoint)."""
        return project_perspective(
            point=point,
            camera_position=self.position,
            camera_target=self.target,
            up_vector=self.up_vector,
            width=self.view_width,
            height=self.view_height,
            view_offset_x=self.view_offset_x,
            view_offset_y=self.view_offset_y,
            near_plane=self.near_plane,
            far_plane=self.far_plane,
        )

    def unproject(self, point: Union[ImagePoint, Tuple[float, float]]) -> Ray3D:
        """Unproject a 2D screen coordinate into a 3D Ray originating from camera optical center."""
        u = point.x if hasattr(point, "x") else point[0]
        v = point.y if hasattr(point, "y") else point[1]
        if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
            raise ValueError("screen coordinates must be in [0, 1]")

        f, r, u_axis = self.camera_basis()
        x_target = (u - 0.5 - self.view_offset_x) * self.view_width
        y_target = ((1.0 - v) - 0.5 - self.view_offset_y) * self.view_height

        p_focal = _add(
            self.target,
            _add(_scale(r, x_target), _scale(u_axis, y_target))
        )
        direction = _normalize(_sub(p_focal, self.position))
        return Ray3D(origin=self.position, direction=direction)


def project_point(
    point: Tuple[float, float, float],
    view: ViewProjection,
    width: Optional[float] = None,
    height: Optional[float] = None,
    view_offset_x: Optional[float] = None,
    view_offset_y: Optional[float] = None,
) -> Optional[ImagePoint]:
    """Project a point from an adapter ViewProjection.

    Supports both PARALLEL and calibrated PERSPECTIVE projections.
    """
    if not (view.camera_position and view.camera_target and view.up_vector):
        raise ValueError("camera metadata is incomplete")

    width = view.view_width if width is None else width
    height = view.view_height if height is None else height
    if (width is None or height is None) and view.perspective_angle:
        d = _norm(_sub(view.camera_target, view.camera_position))
        rad = math.radians(view.perspective_angle)
        height = 2.0 * d * math.tan(rad / 2.0)
        aspect = float(view.image_width) / float(view.image_height) if view.image_height else 1.0
        width = height * aspect

    if width is None or height is None:
        raise ValueError("view width/height are required")

    ox = view.view_offset_x if view_offset_x is None else view_offset_x
    oy = view.view_offset_y if view_offset_y is None else view_offset_y
    proj_type = view.projection_type.upper()

    if proj_type == "PARALLEL":
        return project_parallel(
            point,
            view.camera_position,
            view.camera_target,
            view.up_vector,
            width,
            height,
            ox,
            oy,
        )
    elif proj_type == "PERSPECTIVE":
        near_p = view.near_plane if view.near_plane is not None else 1e-4
        far_p = view.far_plane if view.far_plane is not None else 1e6
        return project_perspective(
            point,
            view.camera_position,
            view.camera_target,
            view.up_vector,
            width,
            height,
            ox,
            oy,
            near_plane=near_p,
            far_plane=far_p,
        )
    else:
        raise ValueError(f"unsupported projection type: {view.projection_type}")


def unproject_point_to_ray(
    point: Union[ImagePoint, Tuple[float, float]],
    view: ViewProjection,
    width: Optional[float] = None,
    height: Optional[float] = None,
    view_offset_x: Optional[float] = None,
    view_offset_y: Optional[float] = None,
) -> Ray3D:
    """Unproject a 2D screen coordinate (ImagePoint or (u, v)) into a 3D Ray3D.

    Supports both PERSPECTIVE and PARALLEL projection modes.
    """
    u = point.x if hasattr(point, "x") else point[0]
    v = point.y if hasattr(point, "y") else point[1]
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        raise ValueError("screen coordinates must be in [0, 1]")

    if not (view.camera_position and view.camera_target and view.up_vector):
        raise ValueError("camera metadata is incomplete")

    width = view.view_width if width is None else width
    height = view.view_height if height is None else height
    if (width is None or height is None) and view.perspective_angle:
        d = _norm(_sub(view.camera_target, view.camera_position))
        rad = math.radians(view.perspective_angle)
        height = 2.0 * d * math.tan(rad / 2.0)
        aspect = float(view.image_width) / float(view.image_height) if view.image_height else 1.0
        width = height * aspect

    if width is None or height is None:
        raise ValueError("view width/height are required")

    ox = view.view_offset_x if view_offset_x is None else view_offset_x
    oy = view.view_offset_y if view_offset_y is None else view_offset_y

    forward = _normalize(_sub(view.camera_target, view.camera_position))
    up_nom = _normalize(view.up_vector)
    right = _normalize(_cross(forward, up_nom))
    up = _normalize(_cross(right, forward))

    proj_type = view.projection_type.upper()
    if proj_type == "PERSPECTIVE":
        x_focal = (u - 0.5 - ox) * width
        y_focal = ((1.0 - v) - 0.5 - oy) * height
        p_focal = _add(
            view.camera_target,
            _add(_scale(right, x_focal), _scale(up, y_focal))
        )
        direction = _normalize(_sub(p_focal, view.camera_position))
        return Ray3D(origin=view.camera_position, direction=direction)
    elif proj_type == "PARALLEL":
        x_offset = (u - 0.5 - ox) * width
        y_offset = ((1.0 - v) - 0.5 - oy) * height
        origin = _add(
            view.camera_position,
            _add(_scale(right, x_offset), _scale(up, y_offset))
        )
        return Ray3D(origin=origin, direction=forward)
    else:
        raise ValueError(f"unsupported projection type: {view.projection_type}")


def ray_intersects_aabb(
    ray: Ray3D,
    box_min: Tuple[float, float, float],
    box_max: Tuple[float, float, float],
) -> Optional[Tuple[float, float]]:
    """Determine whether ray intersects an AABB using the slab method.

    Returns (t_near, t_far) along the ray where t_far >= max(0.0, t_near),
    or None if no intersection in front of the ray.
    """
    t_min = -float("inf")
    t_max = float("inf")

    for i in range(3):
        origin_val = ray.origin[i]
        dir_val = ray.direction[i]
        b_min = box_min[i]
        b_max = box_max[i]

        if abs(dir_val) < 1e-12:
            if origin_val < b_min or origin_val > b_max:
                return None
        else:
            t1 = (b_min - origin_val) / dir_val
            t2 = (b_max - origin_val) / dir_val
            if t1 > t2:
                t1, t2 = t2, t1
            t_min = max(t_min, t1)
            t_max = min(t_max, t2)

            if t_min > t_max:
                return None

    if t_max < 0.0:
        return None

    return (t_min, t_max)


def ray_intersects_plane(
    ray: Ray3D,
    plane_point: Tuple[float, float, float],
    plane_normal: Tuple[float, float, float],
    backface_cull: bool = False,
) -> Optional[float]:
    """Find parametric distance t where ray intersects a 3D plane.

    Returns t >= 0 if ray hits the front (or either side if backface_cull=False),
    or None if parallel or behind ray origin.
    """
    n = _normalize(plane_normal)
    denom = _dot(n, ray.direction)

    if backface_cull and denom >= -1e-6:
        return None

    if abs(denom) < 1e-9:
        return None

    delta = _sub(plane_point, ray.origin)
    t = _dot(delta, n) / denom

    if t < 0.0:
        return None
    return t


def ray_point_distance(
    ray: Ray3D,
    point: Tuple[float, float, float],
) -> Tuple[float, float]:
    """Calculate shortest distance from a 3D point to a Ray3D.

    Returns (distance, t_depth) where t_depth is the parametric distance along the ray.
    """
    delta = _sub(point, ray.origin)
    t = _dot(delta, ray.direction)

    if t <= 0.0:
        dist = math.sqrt(sum(x * x for x in delta))
        return dist, 0.0

    closest_pt = ray.point_at(t)
    dist = math.sqrt(sum((p - c) ** 2 for p, c in zip(point, closest_pt)))
    return dist, t


def select_geometry_by_ray(
    ray: Ray3D,
    candidates: Sequence[Dict[str, Any]],
    max_distance: float = 0.5,
    backface_cull: bool = True,
) -> List[Dict[str, Any]]:
    """Screen, depth-sort, and rank geometric candidates against a 3D ray.

    Returns ranked list of candidate dicts sorted by depth (Z-buffer) and ray-distance.
    """
    ranked = []
    for cand in candidates:
        pt = cand.get("locator_point") or cand.get("point") or cand.get("centroid")
        bbox = cand.get("bbox")

        bbox_t_near = None
        if bbox is not None:
            if hasattr(bbox, "min_x"):
                b_min = (bbox.min_x, bbox.min_y, bbox.min_z)
                b_max = (bbox.max_x, bbox.max_y, bbox.max_z)
            else:
                b_min, b_max = bbox[0], bbox[1]
            hit = ray_intersects_aabb(ray, b_min, b_max)
            if hit is not None:
                bbox_t_near = hit[0]
            elif pt is None:
                continue

        if pt is None:
            if bbox is not None and bbox_t_near is not None:
                pt = tuple((mn + mx) / 2.0 for mn, mx in zip(b_min, b_max))
            else:
                continue

        dist, t_depth = ray_point_distance(ray, pt)
        if t_depth <= 0.0:
            continue

        if dist > max_distance:
            continue

        normal = cand.get("normal")
        facing_score = 1.0
        if normal is not None:
            norm_vec = _normalize(normal)
            cos_angle = _dot(norm_vec, ray.direction)
            if cos_angle > 0.05 and backface_cull:
                continue
            facing_score = max(0.0, -cos_angle)

        distance_score = max(0.0, min(1.0, 1.0 - dist / max_distance))
        camera_depth = bbox_t_near if (bbox_t_near is not None and bbox_t_near > 0.0) else t_depth

        entry = dict(cand)
        entry["ray_distance"] = dist
        entry["camera_depth"] = camera_depth
        entry["facing_score"] = facing_score
        entry["distance_score"] = distance_score
        entry["total_score"] = 0.5 * distance_score + 0.3 * facing_score + 0.2 * (1.0 / (1.0 + 0.01 * camera_depth))
        ranked.append(entry)

    ranked.sort(key=lambda c: (c["camera_depth"], c["ray_distance"]))

    if ranked:
        ranked[0]["selected"] = True

    return ranked


def grounded_region_from_ray_selection(
    candidate: Dict[str, Any],
    target_semantic: str = "VIEWPORT_SELECTION",
) -> GroundedRegion:
    """Construct an evidenced GroundedRegion from a ray-selected candidate."""
    point = candidate.get("locator_point") or candidate.get("point") or candidate.get("centroid")
    if not point:
        raise ValueError("candidate must have locator coordinate")
    entity_type = candidate.get("entity_type", "Face")
    entity_id = str(candidate.get("index") or candidate.get("name") or "entity_0")
    confidence = float(candidate.get("distance_score", 1.0)) * float(candidate.get("facing_score", 1.0))
    confidence = max(0.0, min(1.0, confidence))
    return GroundedRegion(
        target_semantic=target_semantic,
        entity_type=entity_type,
        entity_ids=(entity_id,),
        anchor_point=tuple(point),
        confidence=confidence,
        status="RESOLVED",
        evidence=(
            f"ray_depth:{candidate.get('camera_depth', 0.0):.4f}",
            f"ray_distance:{candidate.get('ray_distance', 0.0):.4f}",
            f"facing_score:{candidate.get('facing_score', 1.0):.4f}",
        ),
    )
