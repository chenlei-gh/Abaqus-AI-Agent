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
    assert "regions=_abqai_boundary_regions" in script
    assert "regions=tuple(_abqai_boundary_elements)" not in script
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


def test_fifth_attempt_is_a_boundary_stop_gate():
    script = local_remesh_script("p", 5)
    compile(script, "<local_remesh_5>", "exec")
    assert "_abqai_local_attempt = 5" in script
    assert "_abqai_local_scheme = 'boundary_stop_gate'" in script
    assert "sizeGrowth=MAXIMUM" not in script
    assert "algorithm=" not in script
    assert "seedEdgeBySize(" not in script
    assert "seedEdgeByBias(" not in script
    assert "float(2 ** (5 - 1))" not in script
    assert "getAdjacentCells()" not in script
    assert "deleteMesh(regions=_abqai_local_cells)" not in script
    assert "generateMesh(" not in script
    assert "elemShape=TRI" in script
    assert "regions=_abqai_boundary_regions" in script
    assert "regions=tuple(_abqai_boundary_elements)" not in script
    assert "tet_fifth_boundary_stop" in script
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

    def getCells(self):
        return getattr(self, "_cells", ())


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
        self.preview_calls = []
        self.preview_deletes = 0
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

    def generateMesh(self, regions, boundaryPreview=False):
        if boundaryPreview:
            self.preview_calls.append(regions)
            return
        self.mesh_calls.append(regions)
        self.elements = (_Element(len(self.mesh_calls) + 1),)
        self.nodes = (_Element(len(self.mesh_calls) + 1),)

    def deletePreviewMesh(self):
        self.preview_deletes += 1

    def verifyMeshQuality(self, criterion=None, threshold=None, elemShape=None, regions=()):
        return {"failedElements": (), "warningElements": (), "worst": 0.2}


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
        "ON": "ON",
        "TRI": "TRI",
        "SHAPE_FACTOR": "SHAPE_FACTOR",
        "ANALYSIS_CHECKS": "ANALYSIS_CHECKS",
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
        "ON": "ON",
        "TRI": "TRI",
        "SHAPE_FACTOR": "SHAPE_FACTOR",
        "ANALYSIS_CHECKS": "ANALYSIS_CHECKS",
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
    assert scope["_abqai_local_status"] == "boundary_stop_gate"
    assert scope["_abqai_boundary_gate"]["status"] == "boundary_accepted_interior_unchanged"
    assert scope["_abqai_boundary_gate"]["interior_generated"] is False
    assert [call[1] for call in part.seed_calls] == [1.0, 0.5]
    assert part.bias_calls[0][2:4] == (0.5, 2.0)
    assert part.control_calls == []
    assert len(part.delete_calls) == 3
    assert len(part.mesh_calls) == 3
    assert len(part.preview_calls) == 3
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
        "ON": "ON",
        "TRI": "TRI",
        "SHAPE_FACTOR": "SHAPE_FACTOR",
        "ANALYSIS_CHECKS": "ANALYSIS_CHECKS",
    }
    exec(compile(local_remesh_script("p", 2), "<round2>", "exec"), scope)
    exec(compile(local_remesh_script("p", 3), "<round3>", "exec"), scope)
    assert scope["_abqai_local_region_indices"] == [0, 1]
    exec(compile(local_remesh_script("p", 4), "<round4>", "exec"), scope)
    assert scope["_abqai_local_region_indices"] == [0]
    assert scope["_abqai_local_status"] == "applied_failed_host_edge_ends"
    assert [call[1] for call in part.seed_calls] == [1.0, 0.5]
    assert len(part.mesh_calls) == 3


def test_round_two_half_seed_keeps_the_wall_and_five_percent_floor():
    script = local_remesh_script("p", 2, primary_wall_thickness=1.5)
    compile(script, "<round2_guard>", "exec")
    assert "_abqai_local_seed_floor = _abqai_local_base_seed * 0.05" in script
    assert "_abqai_local_seed_wall = 1.5" in script
    assert "tet_local_half_seed_below_floor" in script
    assert "tet_local_half_seed_exceeds_wall" in script
    guarded = script.index("tet_local_half_seed_below_floor")
    deleted = script.index("deleteMesh(regions=_abqai_local_cells)")
    preview = script.index("generateMesh(regions=_abqai_local_cells, boundaryPreview=ON)")
    interior = script.index("generateMesh(regions=_abqai_local_cells)\n")
    assert guarded < deleted < preview < interior
    later = local_remesh_script("p", 3, primary_wall_thickness=1.5)
    assert "tet_local_half_seed_below_floor" not in later
    assert "* 0.5" not in later.replace("* 0.05", "")
    stop = local_remesh_script("p", 5, primary_wall_thickness=1.5)
    assert "* 0.5" not in stop.replace("* 0.05", "")
    assert "_abqai_local_seed_wall" not in stop


class _RecoveryElement:
    def __init__(self, label):
        self.label = label


class _RecoveryPart:
    def __init__(self, boundary_failures, interior_failures=0):
        failed = _RecoveryElement(10)
        self.failed = failed
        self.cells = _Cells((_Cell(0, elements=(failed,)),))
        self.faces = (_Face((0,), (failed,)),)
        self.edges = (_Edge(0),)
        self.elements = (failed,)
        self.nodes = (_RecoveryElement(1),)
        self.boundary_failures = list(boundary_failures)
        self.interior_failures = interior_failures
        self.preview_calls = []
        self.interior_calls = []
        self.preview_deletes = 0
        self.seed_calls = []
        self.quality_regions = []

    def deleteMesh(self, regions):
        self.elements = ()
        self.nodes = ()

    def deletePreviewMesh(self):
        self.preview_deletes += 1
        self.elements = ()
        self.nodes = ()

    def getPartSeeds(self, attribute=None):
        return 2.0

    def seedEdgeBySize(self, edges, size, deviationFactor=None, minSizeFactor=None, constraint=None):
        self.seed_calls.append((size, constraint, deviationFactor, minSizeFactor))

    def getEdgeSeeds(self, edge, attribute=None):
        return "SIZE"

    def generateMesh(self, regions, boundaryPreview=False):
        if boundaryPreview:
            self.preview_calls.append(regions)
            self.elements = (_RecoveryElement(90),)
            self.nodes = (_RecoveryElement(91),)
            return
        self.interior_calls.append(regions)
        self.elements = (_RecoveryElement(100),)
        self.nodes = (_RecoveryElement(101),)

    def verifyMeshQuality(self, criterion=None, threshold=None, elemShape=None, regions=()):
        self.quality_regions.append((elemShape, tuple(regions)))
        if elemShape == "TRI":
            failed = self.boundary_failures.pop(0)
            return {"failedElements": ((_RecoveryElement(10),) if failed else ()), "worst": 0.2}
        failed = self.interior_failures
        return {"failedElements": ((_RecoveryElement(11),) if failed else ()), "worst": 0.2}


def _recovery_scope(part, seed=0.5):
    return {
        "p": part,
        "_abqai_quality_failed": (part.failed,),
        "_abqai_quality_ok": False,
        "_abqai_local_seed_size": seed,
        "_abqai_rounds": [{"round": 5, "passed": False}],
        "SIZE": "SIZE",
        "DEFAULT_SIZE": "DEFAULT_SIZE",
        "FINER": "FINER",
        "ON": "ON",
        "EDGE_SEEDING_METHOD": "EDGE_SEEDING_METHOD",
        "TRI": "TRI",
        "TET": "TET",
        "SHAPE_FACTOR": "SHAPE_FACTOR",
        "ANALYSIS_CHECKS": "ANALYSIS_CHECKS",
    }


def test_runtime_round_two_stops_before_delete_when_half_seed_exceeds_wall():
    failed = _Element(10)
    part = _Part((_Cell(0, elements=(failed,)),), faces=(_Face((0,), (failed,)),), edge_count=1)
    scope = {
        "p": part,
        "_abqai_quality_failed": (failed,),
        "SIZE": "SIZE",
        "DEFAULT_SIZE": "DEFAULT_SIZE",
        "FINER": "FINER",
        "EDGE_SEEDING_METHOD": "EDGE_SEEDING_METHOD",
        "ON": "ON",
        "TRI": "TRI",
        "SHAPE_FACTOR": "SHAPE_FACTOR",
        "ANALYSIS_CHECKS": "ANALYSIS_CHECKS",
    }
    with pytest.raises(RuntimeError, match="tet_local_half_seed_exceeds_wall"):
        exec(compile(local_remesh_script("p", 2, primary_wall_thickness=0.4), "<wall>", "exec"), scope)
    assert part.delete_calls == []
    assert part.mesh_calls == []
    assert part.preview_calls == []
    assert part.seed_calls == []


def test_runtime_face_getcells_locates_a_boundary_triangle_host():
    triangle = _Element(10)
    face = _Face((0,), (triangle,))
    face._cells = (0,)
    part = _Part((_Cell(0, elements=(_Element(1),)),), faces=(face,), edge_count=1)
    scope = {
        "p": part,
        "_abqai_quality_failed": (triangle,),
        "SIZE": "SIZE",
        "DEFAULT_SIZE": "DEFAULT_SIZE",
        "FINER": "FINER",
        "EDGE_SEEDING_METHOD": "EDGE_SEEDING_METHOD",
        "ON": "ON",
        "TRI": "TRI",
        "SHAPE_FACTOR": "SHAPE_FACTOR",
        "ANALYSIS_CHECKS": "ANALYSIS_CHECKS",
    }
    exec(compile(local_remesh_script("p", 2), "<face_host>", "exec"), scope)
    assert scope["_abqai_local_current_hosts"] == [0]
    assert scope["_abqai_local_status"] == "applied_host_faces"
    assert len(part.preview_calls) == 1
    assert len(part.mesh_calls) == 1


def test_runtime_fifth_round_rejects_existing_triangles_without_deleting_mesh():
    failed = _Element(10)
    part = _Part((_Cell(0, elements=(failed,)),), faces=(_Face((0,), (failed,)),), edge_count=1)

    def reject_triangles(criterion=None, threshold=None, elemShape=None, regions=()):
        if elemShape == "TRI":
            return {"failedElements": (failed,), "warningElements": (), "worst": 1.0e-8}
        return {"failedElements": (), "warningElements": (), "worst": 0.2}

    part.verifyMeshQuality = reject_triangles
    scope = {
        "p": part,
        "_abqai_quality_failed": (failed,),
        "SIZE": "SIZE",
        "DEFAULT_SIZE": "DEFAULT_SIZE",
        "FINER": "FINER",
        "EDGE_SEEDING_METHOD": "EDGE_SEEDING_METHOD",
        "TRI": "TRI",
        "SHAPE_FACTOR": "SHAPE_FACTOR",
        "ANALYSIS_CHECKS": "ANALYSIS_CHECKS",
    }
    with pytest.raises(RuntimeError, match="tet_fifth_boundary_stop"):
        exec(compile(local_remesh_script("p", 5), "<stop>", "exec"), scope)
    assert part.delete_calls == []
    assert part.mesh_calls == []
    assert part.preview_calls == []
    assert part.preview_deletes == 0
    assert scope["_abqai_boundary_gate"]["status"] == "boundary_rejected"
    assert scope["_abqai_boundary_gate"]["interior_generated"] is False
