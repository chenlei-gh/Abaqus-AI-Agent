import math
from typing import Optional, Tuple

from ..contracts.geometry import ImagePoint, ViewProjection


def _normalize(v):
    n = math.sqrt(sum(x * x for x in v))
    if n == 0.0:
        raise ValueError("zero-length vector")
    return tuple(x / n for x in v)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def project_parallel(point: Tuple[float, float, float],
                     camera_position: Tuple[float, float, float],
                     camera_target: Tuple[float, float, float],
                     up_vector: Tuple[float, float, float],
                     width: float, height: float,
                     view_offset_x: float = 0.0,
                     view_offset_y: float = 0.0) -> Optional[ImagePoint]:
    """Project a model point using an Abaqus parallel View definition.

    This is deliberately limited to PARALLEL projection until perspective
    calibration is validated against real Abaqus screenshots.
    """
    if width <= 0.0 or height <= 0.0:
        raise ValueError("projection width and height must be positive")
    forward = _normalize(tuple(t - p for p, t in zip(camera_position, camera_target)))
    up = _normalize(up_vector)
    right = _normalize(_cross(forward, up))
    up = _normalize(_cross(right, forward))
    delta = tuple(p - t for p, t in zip(point, camera_target))
    x = 0.5 + _dot(delta, right) / width - view_offset_x
    y = 0.5 + _dot(delta, up) / height - view_offset_y
    return ImagePoint(x, 1.0 - y) if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 else None


def project_point(point, view: ViewProjection, width: float, height: float,
                  view_offset_x: float = 0.0, view_offset_y: float = 0.0):
    if view.projection_type.upper() != "PARALLEL":
        raise NotImplementedError("perspective projection requires calibration")
    if not (view.camera_position and view.camera_target and view.up_vector):
        raise ValueError("camera metadata is incomplete")
    return project_parallel(point, view.camera_position, view.camera_target,
                            view.up_vector, width, height,
                            view_offset_x, view_offset_y)
