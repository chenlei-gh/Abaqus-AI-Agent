from ..contracts.viewport import ViewportState
from .odb_rendering import (
    ContourPlotRequest,
    generate_headless_viewer_script,
    render_odb_contours_headless,
)


def capture_viewport_script(path, viewport_name=None, image_format="PNG"):
    # Abaqus/CAE supports PNG through abaqusConstants; keep generation
    # conservative for older Python/Abaqus environments.
    if viewport_name is None:
        return """from abaqusConstants import PNG\nvp = session.viewports[session.currentViewportName]\nsession.printToFile(fileName=%r, format=PNG, canvasObjects=(vp,))\nprint(%r)""" % (path, path)
    return """from abaqusConstants import PNG\nvp = session.viewports[%r]\nsession.printToFile(fileName=%r, format=PNG, canvasObjects=(vp,))\nprint(%r)""" % (viewport_name, path, path)


def capture_viewport(executor, path, viewport_name=None):
    return executor.execute(capture_viewport_script(path, viewport_name))


def _mapping(raw):
    if isinstance(raw, dict):
        for key in ("data", "result"):
            if isinstance(raw.get(key), dict):
                return raw[key]
        return raw
    return {}


def read_viewport_state(executor):
    raw = executor.viewport_state() if hasattr(executor, "viewport_state") else executor.execute(
        "print({})"
    )
    data = _mapping(raw)
    return ViewportState(
        viewport_name=str(data.get("viewport_name", "")),
        projection=str(data.get("projection", "unknown")),
        camera_position=tuple(data.get("camera_position", ()) or ()),
        camera_target=tuple(data.get("camera_target", ()) or ()),
        camera_up=tuple(data.get("camera_up", ()) or ()),
        displayed_instances=tuple(str(x) for x in (data.get("displayed_instances", ()) or ())),
        displayed_object=str(data.get("displayed_object", "")),
        image_path=str(data.get("image_path", "")),
        metadata=dict(data.get("metadata", {}) or {}),
    )
