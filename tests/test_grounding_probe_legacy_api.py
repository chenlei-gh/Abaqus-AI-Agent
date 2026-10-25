from abaqus_ai_agent.adapters.abaqus.grounding_probe import (
    extract_geometry,
    extract_viewport,
    snapshot,
)


class _Face:
    pointOn = ((1.0, 2.0, 3.0),)

    def getCentroid(self):
        return (1.5, 2.5, 3.5)

    def getNormal(self):
        return (0.0, 0.0, 1.0)

    def getSize(self):
        return 2.5


class _Edge:
    pointOn = ((4.0, 5.0, 6.0),)

    def getSize(self):
        return 1.25


class _Owner:
    def __init__(self, name=None):
        self.faces = [_Face()]
        self.edges = [_Edge()]
        if name is not None:
            self.name = name


class _View:
    projection = "PARALLEL"
    cameraPosition = (0.0, 0.0, 10.0)
    cameraTarget = (0.0, 0.0, 0.0)
    cameraUpVector = (0.0, 1.0, 0.0)
    width = 100.0
    height = 50.0
    viewOffsetX = 0.25
    viewOffsetY = -0.5
    displayedObjectScreenWidth = 800.0
    displayedObjectScreenHeight = 600.0


class _Viewport:
    name = "Viewport: 1"

    def __init__(self, displayed):
        self.view = _View()
        self.displayedObject = displayed


class _Session:
    def __init__(self, displayed):
        self.viewports = {"Viewport: 1": _Viewport(displayed)}


def test_extract_geometry_preserves_legacy_descriptor_shape():
    geometry = extract_geometry(_Owner())

    assert geometry["faces"] == [{
        "entity_type": "Face",
        "index": 0,
        "point_on": (1.0, 2.0, 3.0),
        "centroid": (1.5, 2.5, 3.5),
        "normal": (0.0, 0.0, 1.0),
        "size": 2.5,
    }]
    assert geometry["edges"] == [{
        "entity_type": "Edge",
        "index": 0,
        "point_on": (4.0, 5.0, 6.0),
        "centroid": (4.0, 5.0, 6.0),
        "normal": None,
        "size": 1.25,
    }]


def test_extract_viewport_preserves_camera_and_screen_state():
    viewport = _Viewport(_Owner())

    data = extract_viewport(viewport)

    assert data["viewport_id"] == "Viewport: 1"
    assert data["projection_type"] == "PARALLEL"
    assert data["camera_position"] == (0.0, 0.0, 10.0)
    assert data["camera_target"] == (0.0, 0.0, 0.0)
    assert data["up_vector"] == (0.0, 1.0, 0.0)
    assert data["view_offset_x"] == 0.25
    assert data["view_offset_y"] == -0.5
    assert data["displayed_object_screen_width"] == 800.0
    assert data["displayed_object_screen_height"] == 600.0


def test_snapshot_preserves_instance_and_part_object_shapes():
    class _DisplayedWithInstances:
        instances = {"PART-1-1": _Owner()}

    instance_session = _Session(_DisplayedWithInstances())
    instance_data = snapshot(instance_session)

    assert instance_data["viewport"]["viewport_id"] == "Viewport: 1"
    assert instance_data["objects"] == [{
        "name": "PART-1-1",
        "entity_type": "Instance",
        "geometry": extract_geometry(_Owner()),
    }]

    part_session = _Session(_Owner(name="PART-1"))
    part_data = snapshot(part_session)

    assert part_data["objects"] == [{
        "name": "PART-1",
        "entity_type": "Part",
        "geometry": extract_geometry(_Owner()),
    }]


def test_snapshot_without_displayed_object_keeps_empty_objects():
    data = snapshot(_Session(None))

    assert data["viewport"]["viewport_id"] == "Viewport: 1"
    assert data["objects"] == []
