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
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
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


def project_point(
    point,
    view: ViewProjection,
    width: Optional[float] = None,
    height: Optional[float] = None,
    view_offset_x: Optional[float] = None,
    view_offset_y: Optional[float] = None,
):
    """Project a point from an adapter ViewProjection.

    Perspective projection is intentionally unsupported until calibrated
    against actual Abaqus output.
    """
    if view.projection_type.upper() != "PARALLEL":
        raise NotImplementedError("perspective projection requires calibration")
    if not (view.camera_position and view.camera_target and view.up_vector):
        raise ValueError("camera metadata is incomplete")

    width = view.view_width if width is None else width
    height = view.view_height if height is None else height
    if width is None or height is None:
        raise ValueError("view width/height are required")

    return project_parallel(
        point,
        view.camera_position,
        view.camera_target,
        view.up_vector,
        width,
        height,
        view.view_offset_x if view_offset_x is None else view_offset_x,
        view.view_offset_y if view_offset_y is None else view_offset_y,
    )
