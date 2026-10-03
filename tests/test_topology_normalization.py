"""Unit tests for Track GA-1.3A: Canonical Topology Normalization."""

from abaqus_ai_agent.geometry import (
    CadBoundingBox,
    CadEdge,
    CadFace,
    CadFormat,
    CadLoop,
    CadProvenance,
    CadShell,
    CadSolid,
    CadUnit,
    CadVertex,
    GeometryModel,
    NormalizedTopology,
    normalize_topology,
)


def _make_dummy_provenance() -> CadProvenance:
    return CadProvenance(
        file_path="/mock/cad/part.stp",
        file_name="part.stp",
        file_sha256="b" * 64,
        file_size_bytes=2048,
        ingested_at="2026-10-03T14:00:00Z",
        cad_format=CadFormat.STEP,
        cad_schema="AP203",
    )


def test_topology_normalization_cube():
    """Verify full 2-manifold B-Rep hierarchy on a canonical 6-face cube."""
    # Cube: 6 faces, 12 edges, 8 vertices
    # Each face has an outer loop of 4 edges; every edge shared by exactly 2 faces
    edges = tuple(CadEdge(id=f"E{i}") for i in range(1, 13))

    faces = (
        CadFace(id="F_BOTTOM", outer_loop=CadLoop(id="L_BOT", is_outer=True, edge_ids=("E1", "E2", "E3", "E4"))),
        CadFace(id="F_TOP", outer_loop=CadLoop(id="L_TOP", is_outer=True, edge_ids=("E5", "E6", "E7", "E8"))),
        CadFace(id="F_FRONT", outer_loop=CadLoop(id="L_FRONT", is_outer=True, edge_ids=("E1", "E9", "E5", "E10"))),
        CadFace(id="F_BACK", outer_loop=CadLoop(id="L_BACK", is_outer=True, edge_ids=("E3", "E11", "E7", "E12"))),
        CadFace(id="F_LEFT", outer_loop=CadLoop(id="L_LEFT", is_outer=True, edge_ids=("E4", "E10", "E8", "E12"))),
        CadFace(id="F_RIGHT", outer_loop=CadLoop(id="L_RIGHT", is_outer=True, edge_ids=("E2", "E9", "E6", "E11"))),
    )

    shell = CadShell(id="SH1", face_ids=("F_BOTTOM", "F_TOP", "F_FRONT", "F_BACK", "F_LEFT", "F_RIGHT"), is_closed=True)
    solid = CadSolid(id="S1", shell_ids=("SH1",))

    model = GeometryModel(
        model_id="M_CUBE",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
        solids=(solid,),
        shells=(shell,),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)

    assert topo.solid_to_shells["S1"] == ("SH1",)
    assert len(topo.shell_to_faces["SH1"]) == 6
    assert len(topo.manifold_shared_edges) == 12
    assert len(topo.boundary_edges) == 0
    assert len(topo.non_manifold_edges) == 0
    assert len(topo.dangling_edges) == 0
    assert topo.is_watertight_shell("SH1") is True
    assert len(topo.connected_components) == 1
    assert len(topo.connected_components[0]) == 6

    # Verify face adjacency via shared edges
    bot_adj = topo.get_adjacent_faces("F_BOTTOM")
    assert set(bot_adj) == {"F_FRONT", "F_RIGHT", "F_BACK", "F_LEFT"}
    shared = topo.get_shared_edges("F_BOTTOM", "F_FRONT")
    assert shared == ("E1",)


def test_topology_outer_and_inner_loops():
    """Verify differentiation of outer boundary loops vs. inner hole/void loops."""
    face = CadFace(
        id="F_PLATE_WITH_HOLE",
        outer_loop=CadLoop(id="LOOP_OUTER", is_outer=True, edge_ids=("E1", "E2", "E3", "E4")),
        inner_loops=(
            CadLoop(id="LOOP_HOLE_1", is_outer=False, edge_ids=("E_H1_A", "E_H1_B")),
            CadLoop(id="LOOP_HOLE_2", is_outer=False, edge_ids=("E_H2_A", "E_H2_B")),
        ),
    )

    model = GeometryModel(
        model_id="M_HOLE_PLATE",
        provenance=_make_dummy_provenance(),
        faces=(face,),
        edges=(
            CadEdge(id="E1"), CadEdge(id="E2"), CadEdge(id="E3"), CadEdge(id="E4"),
            CadEdge(id="E_H1_A"), CadEdge(id="E_H1_B"),
            CadEdge(id="E_H2_A"), CadEdge(id="E_H2_B"),
        ),
    )

    topo = normalize_topology(model)
    outer = topo.get_outer_loop("F_PLATE_WITH_HOLE")
    assert outer is not None
    assert outer.id == "LOOP_OUTER"
    assert outer.edge_ids == ("E1", "E2", "E3", "E4")

    inners = topo.get_inner_loops("F_PLATE_WITH_HOLE")
    assert len(inners) == 2
    inner_ids = {l.id for l in inners}
    assert inner_ids == {"LOOP_HOLE_1", "LOOP_HOLE_2"}

    # Total face edges must consolidate all loops
    face_edges = topo.face_to_edges["F_PLATE_WITH_HOLE"]
    assert len(face_edges) == 8
    assert "E_H1_A" in face_edges


def test_topology_boundary_and_dangling_edges():
    """Verify open sheet boundary edges and dangling wireframe edge detection."""
    # 2 faces sharing E2. E1, E3 are boundary edges. E_DANGLE is isolated.
    faces = (
        CadFace(id="F1", edge_ids=("E1", "E2")),
        CadFace(id="F2", edge_ids=("E2", "E3")),
    )
    edges = (
        CadEdge(id="E1"),
        CadEdge(id="E2"),
        CadEdge(id="E3"),
        CadEdge(id="E_DANGLE"),
    )

    model = GeometryModel(
        model_id="M_SHEET",
        provenance=_make_dummy_provenance(),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    assert set(topo.boundary_edges) == {"E1", "E3"}
    assert topo.manifold_shared_edges == ("E2",)
    assert topo.dangling_edges == ("E_DANGLE",)


def test_topology_connected_components_split():
    """Verify distinct disconnected components are partitioned correctly."""
    # Component 1: F1 <-> F2
    # Component 2: F3 <-> F4 (separate body/island)
    faces = (
        CadFace(id="F1", edge_ids=("E1",)),
        CadFace(id="F2", edge_ids=("E1",)),
        CadFace(id="F3", edge_ids=("E2",)),
        CadFace(id="F4", edge_ids=("E2",)),
    )
    edges = (CadEdge(id="E1"), CadEdge(id="E2"))

    model = GeometryModel(
        model_id="M_DISCONNECTED",
        provenance=_make_dummy_provenance(),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    assert len(topo.connected_components) == 2
    comp_sets = [set(c) for c in topo.connected_components]
    assert {"F1", "F2"} in comp_sets
    assert {"F3", "F4"} in comp_sets


def test_topology_normalization_idempotence():
    """Verify that multiple normalize_topology runs on same model yield identical results."""
    faces = (
        CadFace(id="F_B", edge_ids=("E2", "E1")),
        CadFace(id="F_A", edge_ids=("E1", "E3")),
    )
    edges = (CadEdge(id="E1"), CadEdge(id="E2"), CadEdge(id="E3"))

    model = GeometryModel(
        model_id="M_IDEMPOTENT",
        provenance=_make_dummy_provenance(),
        faces=faces,
        edges=edges,
    )

    topo1 = normalize_topology(model)
    topo2 = normalize_topology(model)

    assert topo1.to_dict() == topo2.to_dict()
    assert topo1.face_to_edges == topo2.face_to_edges
    assert topo1.edge_to_adjacent_faces == topo2.edge_to_adjacent_faces
    assert topo1.face_adjacency == topo2.face_adjacency
