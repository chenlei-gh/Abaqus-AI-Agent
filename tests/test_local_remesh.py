"""Contracts for the Agent's CAD-linked local incremental remesh capability."""

import pytest

from abaqus_ai_agent.contracts.local_remesh import local_remesh_script


def test_second_attempt_seeds_failed_host_faces_before_region_delete():
    script = local_remesh_script("p", 2)
    compile(script, "<local_remesh_2>", "exec")
    assert "_abqai_quality_failed" in script
    assert "_abqai_cell.getElements()" in script
    assert "_abqai_face.getElements()" in script
    assert "tet_local_host_cell_unresolved" in script
    assert "tet_local_host_faces_unresolved" in script
    assert "orphan-mesh local remeshing is unsupported" in script
    seeded = script.index("seedEdgeBySize(edges=_abqai_local_seed_edges")
    readback = script.index("getEdgeSeeds(edge=_abqai_edge, attribute=EDGE_SEEDING_METHOD)")
    deleted = script.index("deleteMesh(regions=_abqai_local_cells)")
    generated = script.index("generateMesh(regions=_abqai_local_cells)")
    assert seeded < readback < deleted < generated
    assert "constraint=FINER" in script
    assert "deleteMesh()" not in script
    assert "getAdjacentCells" not in script
    assert "seedPart(" not in script


def test_later_attempt_expands_or_uses_a_finer_face_seed():
    script = local_remesh_script("p", 3)
    compile(script, "<local_remesh_3>", "exec")
    assert "for _abqai_index in _abqai_local_host_indices" in script
    assert "getAdjacentCells()" in script
    assert "set(_abqai_local_region_indices) <= set(_abqai_local_host_indices)" in script
    assert "failed_host_faces_finer" in script
    assert "tet_local_scheme_not_different" in script
    assert "_abqai_local_seed_divisor = float(2 ** (3 - 1))" in script
    deleted = script.index("deleteMesh(regions=_abqai_local_cells)")
    generated = script.index("generateMesh(regions=_abqai_local_cells)")
    assert deleted < generated
    assert "deleteMesh()" not in script
    assert "seedPart(" not in script


def test_fourth_attempt_biases_edge_ends_without_dividing_the_seed():
    script = local_remesh_script("p", 4)
    compile(script, "<local_remesh_4>", "exec")
    assert "_abqai_local_scheme = 'edge_end_bias'" in script
    assert "seedEdgeByBias(biasMethod=DOUBLE, endEdges=_abqai_local_seed_edges" in script
    assert "deviationFactor" not in script.split("seedEdgeByBias", 1)[1]
    assert "seedEdgeBySize(" not in script
    assert "getAdjacentCells()" not in script
    assert "float(2 ** (4 - 1))" not in script
    assert "BIAS_METHOD" in script
    seeded = script.index("seedEdgeByBias(")
    deleted = script.index("deleteMesh(regions=_abqai_local_cells)")
    generated = script.index("generateMesh(regions=_abqai_local_cells)")
    assert seeded < deleted < generated


def test_fifth_attempt_changes_interior_growth_without_a_sixth_round():
    script = local_remesh_script("p", 5)
    compile(script, "<local_remesh_5>", "exec")
    assert "_abqai_local_attempt = 5" in script
    assert "_abqai_local_scheme = 'interior_growth_maximum'" in script
    assert "sizeGrowth=MAXIMUM" in script
    assert "algorithm=" not in script
    assert "seedEdgeBySize(" not in script
    assert "seedEdgeByBias(" not in script
    assert "float(2 ** (5 - 1))" not in script
    assert "getAdjacentCells()" not in script
    with pytest.raises(ValueError, match="attempt must be 2, 3, 4, or 5"):
        local_remesh_script("p", 6)


def test_local_remesh_rejects_invalid_attempt_or_empty_part():
    with pytest.raises(ValueError, match="attempt must be 2, 3, 4, or 5"):
        local_remesh_script("p", 1)
    with pytest.raises(ValueError, match="part expression"):
        local_remesh_script("", 2)


class _Element:
    def __init__(self, label):
        self.label = label


class _Face:
    def __init__(self, edge_ids, elements=()):
        self._edges = tuple(edge_ids)
        self._elements = tuple(elements)

    def getEdges(self):
        return self._edges

    def getElements(self):
        return self._elements


class _Edge:
    def __init__(self, index):
        self.index = index


class _Cell:
    def __init__(self, index, elements=(), neighbors=()):
        self.index = index
        self.pointOn = ((float(index), 0.0, 0.0),)
        self._elements = tuple(elements)
        self._neighbors = tuple(neighbors)

    def getElements(self):
        return self._elements

    def getAdjacentCells(self):
        return self._neighbors


class _Cells:
    def __init__(self, cells):
        self._cells = tuple(cells)

    def __iter__(self):
        return iter(self._cells)

    def __getitem__(self, index):
        return self._cells[index]

    def findAt(self, points, printWarning=False):
        assert points
        return tuple(self._cells[int(point[0])] for point in points)


class _Part:
    def __init__(self, cells, faces=(), edge_count=1):
        self.cells = _Cells(cells)
        self.faces = tuple(faces)
        self.edges = tuple(_Edge(index) for index in range(edge_count))
        self.mesh_calls = []
        self.delete_calls = []
        self.seed_calls = []
        self.bias_calls = []
        self.control_calls = []
        self.elements = (_Element(1),)
        self.nodes = (_Element(1),)

    def deleteMesh(self, regions):
        self.delete_calls.append(regions)
        self.elements = ()
        self.nodes = ()

    def getPartSeeds(self, attribute=None):
        return 2.0

    def seedEdgeBySize(self, edges, size, deviationFactor=None, minSizeFactor=None, constraint=None):
        self.seed_calls.append((tuple(edge.index for edge in edges), size, constraint))

    def seedEdgeByBias(self, biasMethod=None, endEdges=(), minSize=None, maxSize=None, constraint=None):
        self.bias_calls.append((biasMethod, tuple(edge.index for edge in endEdges), minSize, maxSize, constraint))
        self._bias = (minSize, maxSize)

    def setMeshControls(self, regions=None, elemShape=None, technique=None, sizeGrowth=None):
        self.control_calls.append((elemShape, technique, sizeGrowth))

    def getMeshControl(self, region=None, attribute=None):
        if attribute == "ELEM_SHAPE":
            return "TET"
        if attribute == "TECHNIQUE":
            return "FREE"
        return None

    def getEdgeSeeds(self, edge, attribute=None):
        if attribute == "EDGE_SEEDING_METHOD" and getattr(self, "_bias", None):
            return "BIASED"
        if attribute == "BIAS_METHOD" and getattr(self, "_bias", None):
            return "DOUBLE"
        if attribute == "BIAS_MIN_SIZE" and getattr(self, "_bias", None):
            return self._bias[0]
        if attribute == "BIAS_MAX_SIZE" and getattr(self, "_bias", None):
            return self._bias[1]
        return "SIZE"

    def generateMesh(self, regions):
        self.mesh_calls.append(regions)
        self.elements = (_Element(len(self.mesh_calls) + 1),)
        self.nodes = (_Element(len(self.mesh_calls) + 1),)


def test_runtime_third_attempt_expands_to_adjacent_cells():
    failed = _Element(10)
    first = _Cell(0, elements=(failed,))
    second = _Cell(1)
    first._neighbors = (second,)
    part = _Part((first, second), faces=(_Face((0,), (failed,)),), edge_count=1)
    scope = {
        "p": part,
        "_abqai_quality_failed": (failed,),
        "SIZE": "SIZE",
        "DEFAULT_SIZE": "DEFAULT_SIZE",
        "FINER": "FINER",
        "EDGE_SEEDING_METHOD": "EDGE_SEEDING_METHOD",
    }

    exec(compile(local_remesh_script("p", 2), "<round2>", "exec"), scope)
    assert scope["_abqai_local_region_indices"] == [0]
    assert len(part.delete_calls) == 1
    assert len(part.mesh_calls) == 1
    assert part.delete_calls[0] == part.mesh_calls[0]

    exec(compile(local_remesh_script("p", 3), "<round3>", "exec"), scope)
    assert scope["_abqai_local_region_indices"] == [0, 1]
    assert scope["_abqai_local_status"] == "applied_expanded_cells"
    assert len(part.delete_calls) == 2
    assert len(part.mesh_calls) == 2


def test_runtime_single_cell_third_attempt_uses_finer_local_seed():
    failed = _Element(10)
    part = _Part(
        (_Cell(0, elements=(failed,)),),
        faces=(_Face((0,), (failed,)),),
        edge_count=1,
    )
    scope = {
        "p": part,
        "_abqai_quality_failed": (failed,),
        "SIZE": "SIZE",
        "DEFAULT_SIZE": "DEFAULT_SIZE",
        "FINER": "FINER",
        "EDGE_SEEDING_METHOD": "EDGE_SEEDING_METHOD",
    }
    constants = {
        "DOUBLE": "DOUBLE", "BIASED": "BIASED", "BIAS_METHOD": "BIAS_METHOD",
        "BIAS_MIN_SIZE": "BIAS_MIN_SIZE", "BIAS_MAX_SIZE": "BIAS_MAX_SIZE",
        "MAXIMUM": "MAXIMUM", "ELEM_SHAPE": "ELEM_SHAPE", "TECHNIQUE": "TECHNIQUE",
        "TET": "TET", "FREE": "FREE",
    }
    scope.update(constants)
    exec(compile(local_remesh_script("p", 2), "<round2>", "exec"), scope)
    exec(compile(local_remesh_script("p", 3), "<round3>", "exec"), scope)
    exec(compile(local_remesh_script("p", 4), "<round4>", "exec"), scope)
    exec(compile(local_remesh_script("p", 5), "<round5>", "exec"), scope)
    assert scope["_abqai_local_status"] == "applied_located_cells_growth"
    assert [call[1] for call in part.seed_calls] == [1.0, 0.5]
    assert part.bias_calls[0][2:4] == (0.5, 2.0)
    assert part.control_calls == [("TET", "FREE", "MAXIMUM")]
    assert len(part.delete_calls) == 4
    assert len(part.mesh_calls) == 4
    assert scope["_abqai_local_region_indices"] == [0]


def test_runtime_multi_cell_later_attempts_keep_expanding():
    failed = _Element(10)
    first = _Cell(0, elements=(failed,))
    second = _Cell(1)
    third = _Cell(2)
    first._neighbors = (second,)
    second._neighbors = (first, third)
    part = _Part(
        (first, second, third),
        faces=(_Face((0,), (failed,)),),
        edge_count=1,
    )
    scope = {
        "p": part,
        "_abqai_quality_failed": (failed,),
        "SIZE": "SIZE",
        "DEFAULT_SIZE": "DEFAULT_SIZE",
        "FINER": "FINER",
        "EDGE_SEEDING_METHOD": "EDGE_SEEDING_METHOD",
        "DOUBLE": "DOUBLE", "BIASED": "BIASED", "BIAS_METHOD": "BIAS_METHOD",
        "BIAS_MIN_SIZE": "BIAS_MIN_SIZE", "BIAS_MAX_SIZE": "BIAS_MAX_SIZE",
    }
    exec(compile(local_remesh_script("p", 2), "<round2>", "exec"), scope)
    exec(compile(local_remesh_script("p", 3), "<round3>", "exec"), scope)
    assert scope["_abqai_local_region_indices"] == [0, 1]
    exec(compile(local_remesh_script("p", 4), "<round4>", "exec"), scope)
    assert scope["_abqai_local_region_indices"] == [0]
    assert scope["_abqai_local_status"] == "applied_failed_host_edge_ends"
    assert [call[1] for call in part.seed_calls] == [1.0, 0.5]
    assert len(part.mesh_calls) == 3
