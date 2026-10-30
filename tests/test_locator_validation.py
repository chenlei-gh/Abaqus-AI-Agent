from types import SimpleNamespace

from abaqus_ai_agent.adapters.abaqus.locator_validation import (
    locator_guard_script,
    validate_locator,
)
from abaqus_ai_agent.contracts.geometry import GeometryCandidate


class Repo:
    def __init__(self, entities, result=None, error=None):
        self.entities = entities
        self.result = result
        self.error = error

    def findAt(self, coordinates):
        if self.error:
            raise self.error
        return self.result

    def __iter__(self):
        return iter(self.entities)


def candidate(entity_type="Face", locator=(1.0, 2.0, 3.0)):
    return GeometryCandidate(
        entity_type=entity_type,
        name="P-1",
        index=1,
        centroid=(9.0, 9.0, 9.0),
        normal=(0.0, 0.0, 1.0),
        area=1.0,
        distance_score=1.0,
        visual_score=1.0,
        topology_score=1.0,
        locator_point=locator,
    )


def test_locator_validation_accepts_resolved_face():
    face = object()
    instance = SimpleNamespace(faces=Repo([face], result=face))
    result = validate_locator(instance, candidate())
    assert result.valid
    assert result.reason == "validated"


def test_locator_validation_accepts_edge_and_vertex():
    edge = object()
    vertex = object()
    edge_instance = SimpleNamespace(edges=Repo([edge], result=edge))
    vertex_instance = SimpleNamespace(vertices=Repo([vertex], result=vertex))
    assert validate_locator(edge_instance, candidate("Edge")).valid
    assert validate_locator(vertex_instance, candidate("Vertex")).valid


def test_locator_validation_rejects_missing_locator():
    c = candidate()
    c = GeometryCandidate(
        entity_type=c.entity_type, name=c.name, index=c.index,
        centroid=None, normal=c.normal, area=c.area,
        distance_score=c.distance_score, visual_score=c.visual_score,
        topology_score=c.topology_score)
    result = validate_locator(SimpleNamespace(faces=Repo([])), c)
    assert not result.valid
    assert result.reason == "missing_locator"


def test_locator_validation_rejects_find_at_error():
    instance = SimpleNamespace(
        faces=Repo([], error=RuntimeError("no match")))
    result = validate_locator(instance, candidate())
    assert not result.valid
    assert result.reason == "findAt_failed:RuntimeError"


def test_locator_validation_rejects_non_unique_result():
    first, second = object(), object()
    instance = SimpleNamespace(
        faces=Repo([first, second], result=(first, second)))
    result = validate_locator(instance, candidate())
    assert not result.valid
    assert result.reason == "findAt_not_unique"


def test_locator_validation_rejects_instance_mismatch():
    expected = object()
    foreign = object()
    instance = SimpleNamespace(
        faces=Repo([expected], result=foreign))
    result = validate_locator(instance, candidate())
    assert not result.valid
    assert result.reason == "entity_instance_mismatch"


def test_locator_validation_rejects_unknown_type():
    c = candidate("Cell")
    result = validate_locator(SimpleNamespace(), c)
    assert not result.valid
    assert result.reason == "unsupported_entity_type"


class GeomSequence:
    """Stand-in for an Abaqus FaceArray: indexable, not a tuple or list."""

    def __init__(self, items):
        self.items = tuple(items)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def __iter__(self):
        return iter(self.items)


def test_locator_validation_rejects_empty_geom_sequence():
    instance = SimpleNamespace(faces=Repo([], result=GeomSequence(())))
    result = validate_locator(instance, candidate())
    assert not result.valid
    assert result.reason == "findAt_empty"


def test_locator_validation_rejects_none_findat():
    instance = SimpleNamespace(faces=Repo([], result=None))
    result = validate_locator(instance, candidate())
    assert not result.valid
    assert result.reason == "findAt_empty"


def test_locator_validation_accepts_single_item_geom_sequence():
    face = object()
    instance = SimpleNamespace(faces=Repo([face], result=GeomSequence((face,))))
    result = validate_locator(instance, candidate())
    assert result.valid
    assert result.reason == "validated"


def _bind(script, repository, points, label):
    namespace = {"repository": repository}
    exec(script, namespace)
    return namespace["_abqai_bind_region"](repository, points, label)


def test_generated_guard_rejects_empty_sequence_before_surface():
    class Faces:
        def findAt(self, coordinates):
            return GeomSequence(())

    script = locator_guard_script()
    assert "findAt_empty" in script
    try:
        region = _bind(script, Faces(), ((1.0, 2.0, 3.0),), "Contact_7_Main")
    except RuntimeError as exc:
        assert str(exc) == "Contact_7_Main: findAt_empty"
    else:
        raise AssertionError("empty GeomSequence was accepted: %r" % (region,))


def test_generated_guard_accepts_one_face_and_rejects_two():
    face = object()
    other = object()

    class OneFace:
        def findAt(self, coordinates):
            return GeomSequence((face,))

    class TwoFaces:
        def findAt(self, coordinates):
            return GeomSequence((face, other))

    class BareFace:
        def findAt(self, coordinates):
            return face

    # Downstream calls such as a.Set(faces=...) and a.Surface(side1Faces=...)
    # reject a bare Face, so a single hit must come back as a sequence.
    assert tuple(_bind(locator_guard_script(), OneFace(), ((1.0, 2.0, 3.0),), "Contact_1_Main")) == (face,)
    assert tuple(_bind(locator_guard_script(), BareFace(), ((1.0, 2.0, 3.0),), "Contact_1_Main")) == (face,)
    try:
        _bind(locator_guard_script(), TwoFaces(), ((1.0, 2.0, 3.0),), "Contact_1_Main")
    except RuntimeError as exc:
        assert str(exc) == "Contact_1_Main: findAt_not_unique"
    else:
        raise AssertionError("non-unique GeomSequence was accepted")
    assert "isinstance(found, (tuple, list))" not in locator_guard_script()
