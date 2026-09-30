from types import SimpleNamespace

from abaqus_ai_agent.adapters.abaqus.locator_validation import validate_locator
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
