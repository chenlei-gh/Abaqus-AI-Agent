"""Unit tests for Track GA-1.3B: Feature Recognition and Fastener Hole Detection."""

from abaqus_ai_agent.capability_boundary import CapabilityStatus
from abaqus_ai_agent.geometry import (
    CadBoundingBox,
    CadEdge,
    CadFace,
    CadFormat,
    CadLoop,
    CadProvenance,
    CadSolid,
    CadUnit,
    FeatureCandidate,
    FeatureEvidence,
    FeatureType,
    GeometryModel,
    HoleSubType,
    detect_fastener_holes,
    detect_fillets,
    detect_chamfers,
    detect_ribs,
    detect_contact_planes,
    detect_features,
    normalize_topology,
)


def _make_dummy_provenance() -> CadProvenance:
    return CadProvenance(
        file_path="/mock/cad/part.stp",
        file_name="part.stp",
        file_sha256="c" * 64,
        file_size_bytes=4096,
        ingested_at="2026-10-03T16:00:00Z",
        cad_format=CadFormat.STEP,
        cad_schema="AP214",
    )


def test_feature_single_through_hole():
    """Verify clean through-hole detection across two opposing planar faces."""
    # Model: Plate 100x100x20 with through hole (D=10mm)
    faces = (
        CadFace(id="F_TOP", surface_type="PLANE", is_planar=True, edge_ids=("E_TOP_CIRC",)),
        CadFace(id="F_BOT", surface_type="PLANE", is_planar=True, edge_ids=("E_BOT_CIRC",)),
        CadFace(
            id="F_CYL_BARREL",
            surface_type="CYLINDRICAL_SURFACE",
            is_planar=False,
            edge_ids=("E_TOP_CIRC", "E_BOT_CIRC"),
        ),
    )
    # Circumference = pi * 10 = 31.4159
    edges = (
        CadEdge(id="E_TOP_CIRC", length=31.4159),
        CadEdge(id="E_BOT_CIRC", length=31.4159),
    )

    model = GeometryModel(
        model_id="M_THROUGH_HOLE",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 20.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    candidates = detect_fastener_holes(model, topo)

    assert len(candidates) == 1
    hole = candidates[0]
    assert hole.feature_type == FeatureType.FASTENER_HOLE
    assert hole.status == CapabilityStatus.SUPPORTED
    assert hole.geometry["sub_type"] == HoleSubType.THROUGH.value
    assert hole.geometry["is_fastener_hole"] is True
    assert 9.9 <= hole.geometry["diameter"] <= 10.1
    assert hole.confidence >= 0.9
    assert any(e.evidence_type == "DUAL_PLANAR_PENETRATION" for e in hole.evidence)


def test_feature_single_blind_hole():
    """Verify blind hole detection penetrating single planar entrance with interior closure."""
    # Barrel connects to Top plane only, bottom is closed
    faces = (
        CadFace(id="F_TOP", surface_type="PLANE", is_planar=True, edge_ids=("E_TOP_CIRC",)),
        CadFace(
            id="F_BLIND_BARREL",
            surface_type="CYLINDRICAL_SURFACE",
            is_planar=False,
            edge_ids=("E_TOP_CIRC", "E_BOTTOM_SEAL"),
        ),
    )
    edges = (
        CadEdge(id="E_TOP_CIRC", length=31.4159),
        CadEdge(id="E_BOTTOM_SEAL", length=31.4159),
    )

    model = GeometryModel(
        model_id="M_BLIND_HOLE",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 50.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    candidates = detect_fastener_holes(model, topo)

    assert len(candidates) == 1
    hole = candidates[0]
    assert hole.feature_type == FeatureType.FASTENER_HOLE
    assert hole.status == CapabilityStatus.SUPPORTED
    assert hole.geometry["sub_type"] == HoleSubType.BLIND.value
    assert any(e.evidence_type == "SINGLE_PLANAR_ENTRY" for e in hole.evidence)


def test_feature_counterbore_hole():
    """Verify counterbore multi-surface composition (stepped coaxial cylinders)."""
    # Stepped cylinder: F_CYL_LARGE (counterbore seat) + F_CYL_SMALL (shank passage)
    faces = (
        CadFace(id="F_TOP_PLATE", surface_type="PLANE", is_planar=True, edge_ids=("E1",)),
        CadFace(id="F_CYL_LARGE", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E1", "E2")),
        CadFace(id="F_CYL_SMALL", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E2", "E3")),
    )
    edges = (
        CadEdge(id="E1", length=50.0),
        CadEdge(id="E2", length=30.0),
        CadEdge(id="E3", length=30.0),
    )

    model = GeometryModel(
        model_id="M_COUNTERBORE",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 40.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    candidates = detect_fastener_holes(model, topo)

    assert len(candidates) == 1
    hole = candidates[0]
    assert hole.feature_type == FeatureType.FASTENER_HOLE
    assert hole.status == CapabilityStatus.SUPPORTED
    assert hole.geometry["sub_type"] == HoleSubType.COUNTERBORE.value
    assert set(hole.face_ids) == {"F_CYL_LARGE", "F_CYL_SMALL"}
    assert any(e.evidence_type == "STEPPED_CYLINDER_TOPOLOGY" for e in hole.evidence)


def test_feature_multi_hole_array_and_stable_ids():
    """Verify multiple holes in array yield distinct, deterministic, idempotent candidates."""
    faces = [
        CadFace(id="F_PLATE_TOP", surface_type="PLANE", is_planar=True, edge_ids=("E1", "E2", "E3", "E4")),
        CadFace(id="F_PLATE_BOT", surface_type="PLANE", is_planar=True, edge_ids=("EB1", "EB2", "EB3", "EB4")),
    ]
    edges = []

    for i in range(1, 5):
        top_e = f"E{i}"
        bot_e = f"EB{i}"
        cyl_f = f"F_HOLE_{i}"
        faces.append(
            CadFace(
                id=cyl_f,
                surface_type="CYLINDRICAL_SURFACE",
                is_planar=False,
                edge_ids=(top_e, bot_e),
            )
        )
        edges.append(CadEdge(id=top_e, length=18.8495))  # D = 6mm
        edges.append(CadEdge(id=bot_e, length=18.8495))

    model = GeometryModel(
        model_id="M_4_HOLE_FLANGE",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 200.0, 200.0, 20.0),
        faces=tuple(faces),
        edges=tuple(edges),
    )

    topo = normalize_topology(model)
    candidates1 = detect_fastener_holes(model, topo)
    candidates2 = detect_fastener_holes(model, topo)

    assert len(candidates1) == 4
    # Idempotent identity check
    assert [c.feature_id for c in candidates1] == [c.feature_id for c in candidates2]
    for c in candidates1:
        assert c.feature_type == FeatureType.FASTENER_HOLE
        assert c.status == CapabilityStatus.SUPPORTED
        assert 5.9 <= c.geometry["diameter"] <= 6.1

    # Invariant to input entity permutation (shuffled / reversed STEP entity order)
    model_permuted = GeometryModel(
        model_id="M_4_HOLE_FLANGE_PERMUTED",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 200.0, 200.0, 20.0),
        faces=tuple(reversed(faces)),
        edges=tuple(reversed(edges)),
    )
    topo_permuted = normalize_topology(model_permuted)
    candidates_permuted = detect_fastener_holes(model_permuted, topo_permuted)

    assert len(candidates_permuted) == 4
    assert [c.feature_id for c in candidates_permuted] == [c.feature_id for c in candidates1]
    for c_orig, c_perm in zip(candidates1, candidates_permuted):
        assert c_orig.feature_id == c_perm.feature_id
        assert c_orig.face_ids == c_perm.face_ids
        assert c_orig.edge_ids == c_perm.edge_ids
        assert c_orig.geometry == c_perm.geometry


def test_feature_cavity_false_positive_rejection():
    """Verify large cylinder cavity without mounting penetration is NOT misreported as fastener hole."""
    # Box 100x100x100 with massive internal cylindrical core D=80mm (circumference = 251.3)
    # 80mm > 100mm * 0.4 = 40mm threshold
    faces = (
        CadFace(id="F_MASSIVE_CORE", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E_BIG",)),
    )
    edges = (CadEdge(id="E_BIG", length=251.327),)

    model = GeometryModel(
        model_id="M_LARGE_CAVITY",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    candidates = detect_fastener_holes(model, topo)

    assert len(candidates) == 1
    cavity = candidates[0]
    # Must NOT be classified as FASTENER_HOLE
    assert cavity.feature_type == FeatureType.CYLINDRICAL_CAVITY
    assert cavity.status == CapabilityStatus.ASSISTED
    assert cavity.geometry["is_fastener_hole"] is False
    assert any(e.evidence_type == "SCALE_OVERSIZED" and e.result == "FAIL" for e in cavity.evidence)


def test_feature_non_manifold_defect_hole_blocked():
    """Verify hole with topological non-manifold edge defect fails closed to BLOCKED."""
    faces = (
        CadFace(id="F_TOP", surface_type="PLANE", is_planar=True, edge_ids=("E_DEFECT",)),
        CadFace(id="F_DEFECT_HOLE", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E_DEFECT",)),
        CadFace(id="F_EXTRA_WALL", surface_type="PLANE", is_planar=True, edge_ids=("E_DEFECT",)),
    )
    edges = (CadEdge(id="E_DEFECT", length=20.0),)

    model = GeometryModel(
        model_id="M_DEFECTIVE_HOLE",
        provenance=_make_dummy_provenance(),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    assert "E_DEFECT" in topo.non_manifold_edges

    candidates = detect_fastener_holes(model, topo)
    assert len(candidates) == 1
    defect_hole = candidates[0]
    assert defect_hole.status == CapabilityStatus.BLOCKED
    assert any(e.evidence_type == "TOPOLOGICAL_INTEGRITY" and e.result == "FAIL" for e in defect_hole.evidence)


def test_feature_candidate_serialization():
    """Verify FeatureCandidate dictionary serialization format."""
    ev = FeatureEvidence(
        evidence_type="CIRCULAR_EDGE",
        source_entity_ids=("E1",),
        rule="Constant curvature edge",
        measured_value=10.0,
        result="PASS",
    )
    feat = FeatureCandidate(
        feature_id="FEAT_FASTENER_HOLE_F1",
        feature_type=FeatureType.FASTENER_HOLE,
        status=CapabilityStatus.SUPPORTED,
        confidence=0.95,
        face_ids=("F1",),
        edge_ids=("E1",),
        geometry={"diameter": 10.0, "is_fastener_hole": True},
        evidence=(ev,),
    )
    d = feat.to_dict()
    assert d["feature_id"] == "FEAT_FASTENER_HOLE_F1"
    assert d["feature_type"] == "FASTENER_HOLE"
    assert d["status"] == "supported"
    assert d["confidence"] == 0.95
    assert len(d["evidence"]) == 1


def test_feature_candidate_geometry_type_guard():
    """Verify FeatureCandidate rejects non-primitive complex objects in geometry, including deep nesting."""
    class ArbitraryRuntimeObject:
        pass

    import pytest
    with pytest.raises(TypeError, match="must be a canonical primitive scalar"):
        FeatureCandidate(
            feature_id="FEAT_BAD_TOP",
            feature_type=FeatureType.GENERIC_HOLE,
            status=CapabilityStatus.ASSISTED,
            confidence=0.5,
            geometry={"bad_obj": ArbitraryRuntimeObject()},
        )

    # Deeply nested object guard
    with pytest.raises(TypeError, match="must be a canonical primitive scalar"):
        FeatureCandidate(
            feature_id="FEAT_BAD_NESTED",
            feature_type=FeatureType.GENERIC_HOLE,
            status=CapabilityStatus.ASSISTED,
            confidence=0.5,
            geometry={"level1": {"level2": {"bad_nested": ArbitraryRuntimeObject()}}},
        )

    with pytest.raises(TypeError, match="must be a canonical primitive scalar"):
        FeatureCandidate(
            feature_id="FEAT_BAD_LIST",
            feature_type=FeatureType.GENERIC_HOLE,
            status=CapabilityStatus.ASSISTED,
            confidence=0.5,
            geometry={"items": [1, 2, [ArbitraryRuntimeObject()]]},
        )


def test_detect_fillet_positive_and_honest_continuity_gating():
    """Verify cylindrical transition fillet recognition with honest continuity reporting."""
    # Box with 90-degree corner rounded by R=3mm cylinder (F_FILLET)
    # Connecting F_TOP (normal +Z) and F_SIDE (normal +X) via shared rails E_RAIL1, E_RAIL2
    faces = (
        CadFace(id="F_TOP", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), edge_ids=("E_RAIL1",)),
        CadFace(id="F_FILLET", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E_RAIL1", "E_RAIL2", "E_ARC")),
        CadFace(id="F_SIDE", surface_type="PLANE", is_planar=True, normal=(1.0, 0.0, 0.0), edge_ids=("E_RAIL2",)),
    )
    edges = (
        CadEdge(id="E_RAIL1", length=50.0),
        CadEdge(id="E_RAIL2", length=50.0),
        CadEdge(id="E_ARC", curve_type="CIRCLE", length=18.8495),  # 2*pi*R -> R=3mm
    )

    model = GeometryModel(
        model_id="M_FILLETED_BLOCK",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    fillets = detect_fillets(model, topo)

    assert len(fillets) == 1
    fillet = fillets[0]
    assert fillet.feature_type == FeatureType.FILLET
    # Honest continuity gating: without CAD kernel tangent vector field, status is ASSISTED
    assert fillet.status == CapabilityStatus.ASSISTED
    assert fillet.geometry["is_constant_radius"] is True
    assert 2.9 <= fillet.geometry["radius"] <= 3.1
    assert fillet.geometry["continuity_verified"] is False
    assert any(e.evidence_type == "SURFACE_CONTINUITY" and e.result == "INSUFFICIENT_EVIDENCE" for e in fillet.evidence)


def test_detect_fillet_oversized_cylinder_rejection():
    """Verify massive cylindrical body (e.g. main cylinder column) is NOT misreported as a fillet."""
    # Massive column R=40mm on 100mm block (R > 100*0.25 = 25mm threshold)
    faces = (
        CadFace(id="F_BLOCK_TOP", surface_type="PLANE", is_planar=True, edge_ids=("E_R1",)),
        CadFace(id="F_MAIN_COLUMN", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E_R1", "E_R2", "E_BIG_ARC")),
        CadFace(id="F_BLOCK_BOT", surface_type="PLANE", is_planar=True, edge_ids=("E_R2",)),
    )
    edges = (
        CadEdge(id="E_R1", length=100.0),
        CadEdge(id="E_R2", length=100.0),
        CadEdge(id="E_BIG_ARC", curve_type="CIRCLE", length=251.327),  # 2*pi*40 -> R=40mm
    )

    model = GeometryModel(
        model_id="M_MAIN_CYLINDER",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    fillets = detect_fillets(model, topo)
    assert len(fillets) == 0


def test_detect_fillet_non_manifold_blocked():
    """Verify transition fillet with non-manifold edge fails closed to BLOCKED."""
    faces = (
        CadFace(id="F_TOP", surface_type="PLANE", is_planar=True, edge_ids=("E_BAD_RAIL",)),
        CadFace(id="F_FILLET", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E_BAD_RAIL", "E_R2")),
        CadFace(id="F_SIDE", surface_type="PLANE", is_planar=True, edge_ids=("E_BAD_RAIL", "E_R2")),
    )
    edges = (
        CadEdge(id="E_BAD_RAIL", length=50.0),
        CadEdge(id="E_R2", length=50.0),
    )

    model = GeometryModel(
        model_id="M_DEFECT_FILLET",
        provenance=_make_dummy_provenance(),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    assert "E_BAD_RAIL" in topo.non_manifold_edges

    fillets = detect_fillets(model, topo)
    assert len(fillets) == 1
    assert fillets[0].status == CapabilityStatus.BLOCKED
    assert any(e.evidence_type == "TOPOLOGICAL_INTEGRITY" and e.result == "FAIL" for e in fillets[0].evidence)


def test_detect_chamfer_positive():
    """Verify planar chamfer transition between non-coplanar faces."""
    # 45-degree chamfer face F_CHAMFER (length 50mm, width 2mm) connecting F_TOP and F_FRONT
    faces = (
        CadFace(id="F_TOP", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), edge_ids=("E_C1",)),
        CadFace(id="F_CHAMFER", surface_type="PLANE", is_planar=True, normal=(0.0, 0.707, 0.707), edge_ids=("E_C1", "E_C2", "E_CW1", "E_CW2")),
        CadFace(id="F_FRONT", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), edge_ids=("E_C2",)),
    )
    edges = (
        CadEdge(id="E_C1", length=50.0),
        CadEdge(id="E_C2", length=50.0),
        CadEdge(id="E_CW1", length=2.0),
        CadEdge(id="E_CW2", length=2.0),
    )

    model = GeometryModel(
        model_id="M_CHAMFERED_BLOCK",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    chamfers = detect_chamfers(model, topo)

    assert len(chamfers) == 1
    chamfer = chamfers[0]
    assert chamfer.feature_type == FeatureType.CHAMFER
    # Honest boundary: 3D spatial width requires B-Rep kernel distance evaluation -> ASSISTED
    assert chamfer.status == CapabilityStatus.ASSISTED
    assert chamfer.confidence >= 0.75
    assert chamfer.geometry["width"] == 2.0
    assert chamfer.geometry["is_planar"] is True
    assert any(e.evidence_type == "TRANSITIONAL_PLANAR_TOPOLOGY" for e in chamfer.evidence)
    assert any(e.evidence_type == "NON_COPLANAR_NEIGHBORS" for e in chamfer.evidence)


def test_detect_fillet_without_arc_evidence_downgrades_to_none_radius():
    """Verify cylindrical transition fillet without circular/arc edges does NOT fabricate a radius."""
    faces = (
        CadFace(id="F_TOP", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), edge_ids=("E_RAIL1",)),
        CadFace(id="F_FILLET_NO_ARC", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E_RAIL1", "E_RAIL2")),
        CadFace(id="F_SIDE", surface_type="PLANE", is_planar=True, normal=(1.0, 0.0, 0.0), edge_ids=("E_RAIL2",)),
    )
    # Only straight boundary rails, zero circular/arc edges
    edges = (
        CadEdge(id="E_RAIL1", length=50.0),
        CadEdge(id="E_RAIL2", length=50.0),
    )

    model = GeometryModel(
        model_id="M_FILLET_NO_ARC",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    fillets = detect_fillets(model, topo)

    assert len(fillets) == 1
    fillet = fillets[0]
    assert fillet.feature_type == FeatureType.FILLET
    assert fillet.status == CapabilityStatus.ASSISTED
    # Must NOT fabricate radius=5.0 or area-derived radius
    assert fillet.geometry["radius"] is None
    assert fillet.geometry["is_constant_radius"] is False
    assert fillet.geometry["reason"] == "INSUFFICIENT_RADIUS_EVIDENCE"
    assert any(
        e.evidence_type == "LOCAL_SCALE_METRIC" and e.result == "INSUFFICIENT_EVIDENCE"
        for e in fillet.evidence
    )


def test_detect_chamfer_without_width_evidence_downgrades_to_none_width():
    """Verify planar chamfer without transverse profile edges does NOT fabricate a width."""
    faces = (
        CadFace(id="F_TOP", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), edge_ids=("E_C1",)),
        CadFace(id="F_CHAMFER_NO_WIDTH", surface_type="PLANE", is_planar=True, normal=(0.0, 0.707, 0.707), edge_ids=("E_C1", "E_C2", "E_CW_UNKNOWN")),
        CadFace(id="F_FRONT", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), edge_ids=("E_C2",)),
    )
    # Shared rails length=10mm (<= 15mm limit), transverse edge lacks length measurement
    edges = (
        CadEdge(id="E_C1", length=10.0),
        CadEdge(id="E_C2", length=10.0),
        CadEdge(id="E_CW_UNKNOWN", length=None),
    )

    model = GeometryModel(
        model_id="M_CHAMFER_NO_WIDTH",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    chamfers = detect_chamfers(model, topo)

    assert len(chamfers) == 1
    chamfer = chamfers[0]
    assert chamfer.feature_type == FeatureType.CHAMFER
    assert chamfer.status == CapabilityStatus.ASSISTED
    # Must NOT fabricate width=2.0
    assert chamfer.geometry["width"] is None
    assert chamfer.geometry["reason"] == "INSUFFICIENT_CHAMFER_WIDTH_EVIDENCE"
    assert any(
        e.evidence_type == "CHAMFER_DIMENSIONAL_METRIC" and e.result == "INSUFFICIENT_EVIDENCE"
        for e in chamfer.evidence
    )


def test_detect_chamfer_oversized_sloped_surface_rejection():
    """Verify primary sloped surfaces (e.g. large wedge slope) are rejected as chamfers."""
    # Wedge slope with width=40mm on 100mm block (width > 100*0.15 = 15mm)
    faces = (
        CadFace(id="F_BASE", surface_type="PLANE", is_planar=True, normal=(0.0, -1.0, 0.0), edge_ids=("E_W1",)),
        CadFace(id="F_LARGE_SLOPE", surface_type="PLANE", is_planar=True, normal=(0.707, 0.707, 0.0), edge_ids=("E_W1", "E_W2")),
        CadFace(id="F_BACK", surface_type="PLANE", is_planar=True, normal=(-1.0, 0.0, 0.0), edge_ids=("E_W2",)),
    )
    edges = (
        CadEdge(id="E_W1", length=40.0),
        CadEdge(id="E_W2", length=40.0),
    )

    model = GeometryModel(
        model_id="M_WEDGE_SLOPE",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    chamfers = detect_chamfers(model, topo)
    assert len(chamfers) == 0


def test_detect_chamfer_coplanar_neighbors_rejection():
    """Verify planar seam between coplanar / parallel faces is NOT a corner chamfer."""
    # F_LEFT and F_RIGHT both have normal +Z (parallel/coplanar), F_SEAM between them
    faces = (
        CadFace(id="F_LEFT", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), edge_ids=("E_S1",)),
        CadFace(id="F_SEAM", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), edge_ids=("E_S1", "E_S2")),
        CadFace(id="F_RIGHT", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), edge_ids=("E_S2",)),
    )
    edges = (
        CadEdge(id="E_S1", length=10.0),
        CadEdge(id="E_S2", length=10.0),
    )

    model = GeometryModel(
        model_id="M_COPLANAR_SEAM",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    chamfers = detect_chamfers(model, topo)
    assert len(chamfers) == 0


def test_detect_features_consolidated_and_permutation_invariance():
    """Verify consolidated multi-feature extraction and strict permutation invariance."""
    # Combined model with 1 through-hole, 1 fillet, and 1 chamfer
    faces = (
        CadFace(id="F_TOP", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), edge_ids=("E_HOLE_T", "E_FILLET_1", "E_CHAMFER_1")),
        CadFace(id="F_BOT", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, -1.0), edge_ids=("E_HOLE_B",)),
        CadFace(id="F_HOLE", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E_HOLE_T", "E_HOLE_B")),
        CadFace(id="F_FILLET", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E_FILLET_1", "E_FILLET_2", "E_ARC")),
        CadFace(id="F_SIDE1", surface_type="PLANE", is_planar=True, normal=(1.0, 0.0, 0.0), edge_ids=("E_FILLET_2",)),
        CadFace(id="F_CHAMFER", surface_type="PLANE", is_planar=True, normal=(0.0, 0.707, 0.707), edge_ids=("E_CHAMFER_1", "E_CHAMFER_2", "E_CW1", "E_CW2")),
        CadFace(id="F_SIDE2", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), edge_ids=("E_CHAMFER_2",)),
    )
    edges = (
        CadEdge(id="E_HOLE_T", length=18.8495),
        CadEdge(id="E_HOLE_B", length=18.8495),
        CadEdge(id="E_FILLET_1", length=50.0),
        CadEdge(id="E_FILLET_2", length=50.0),
        CadEdge(id="E_ARC", curve_type="CIRCLE", length=18.8495),
        CadEdge(id="E_CHAMFER_1", length=50.0),
        CadEdge(id="E_CHAMFER_2", length=50.0),
        CadEdge(id="E_CW1", length=2.0),
        CadEdge(id="E_CW2", length=2.0),
    )

    model = GeometryModel(
        model_id="M_COMBINED",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    features1 = detect_features(model, topo)

    # Must find all 3 distinct features (along with anchored contact planes)
    feat_types = [f.feature_type for f in features1]
    assert FeatureType.FASTENER_HOLE in feat_types
    assert FeatureType.FILLET in feat_types
    assert FeatureType.CHAMFER in feat_types
    assert len(features1) == 5

    # Permuted / shuffled input model
    model_perm = GeometryModel(
        model_id="M_COMBINED_PERM",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=tuple(reversed(faces)),
        edges=tuple(reversed(edges)),
    )
    topo_perm = normalize_topology(model_perm)
    features_perm = detect_features(model_perm, topo_perm)

    assert len(features_perm) == 5
    for f1, fp in zip(features1, features_perm):
        assert f1.feature_id == fp.feature_id
        assert f1.feature_type == fp.feature_type
        assert f1.status == fp.status
        assert f1.face_ids == fp.face_ids
        assert f1.edge_ids == fp.edge_ids
        assert f1.geometry == fp.geometry


# ---------------------------------------------------------------------------
# GA-1.3B-5: Rib & Contact Plane Recognition Unit Tests
# ---------------------------------------------------------------------------

def test_detect_rib_positive():
    """Verify structural stiffener rib with opposing walls, base anchoring, and measurable thickness."""
    # Substrate base plate F_BASE (100x100mm, normal +Y)
    # Stiffener rib: length 60mm, height 20mm, thickness 3mm
    # Opposing side walls F_RIB_SIDE1 (normal +X) and F_RIB_SIDE2 (normal -X)
    # Top cap ribbon F_RIB_CAP (normal +Y)
    faces = (
        CadFace(id="F_BASE", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), area=10000.0, edge_ids=("E_B1", "E_B2")),
        CadFace(id="F_RIB_SIDE1", surface_type="PLANE", is_planar=True, normal=(1.0, 0.0, 0.0), area=1200.0, edge_ids=("E_B1", "E_CAP1", "E_H1", "E_H2")),
        CadFace(id="F_RIB_SIDE2", surface_type="PLANE", is_planar=True, normal=(-1.0, 0.0, 0.0), area=1200.0, edge_ids=("E_B2", "E_CAP2", "E_H3", "E_H4")),
        CadFace(id="F_RIB_CAP", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), area=180.0, edge_ids=("E_CAP1", "E_CAP2", "E_CW1", "E_CW2")),
    )
    edges = (
        CadEdge(id="E_B1", length=60.0),
        CadEdge(id="E_B2", length=60.0),
        CadEdge(id="E_CAP1", length=60.0),
        CadEdge(id="E_CAP2", length=60.0),
        CadEdge(id="E_CW1", length=3.0),
        CadEdge(id="E_CW2", length=3.0),
        CadEdge(id="E_H1", length=20.0),
        CadEdge(id="E_H2", length=20.0),
        CadEdge(id="E_H3", length=20.0),
        CadEdge(id="E_H4", length=20.0),
    )

    model = GeometryModel(
        model_id="M_STIFFENER_RIB",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    ribs = detect_ribs(model, topo)

    assert len(ribs) == 1
    rib = ribs[0]
    assert rib.feature_type == FeatureType.RIB
    assert rib.status == CapabilityStatus.ASSISTED
    assert rib.confidence >= 0.75
    assert set(rib.face_ids) == {"F_RIB_SIDE1", "F_RIB_SIDE2", "F_RIB_CAP"}
    assert rib.geometry["thickness"] == 3.0
    assert rib.geometry["length"] == 60.0
    assert rib.geometry["slenderness_ratio"] == 20.0
    assert rib.geometry["base_face_id"] == "F_BASE"
    assert any(e.evidence_type == "OPPOSING_WALL_TOPOLOGY" for e in rib.evidence)
    assert any(e.evidence_type == "BASE_ATTACHMENT_TOPOLOGY" for e in rib.evidence)
    assert any(e.evidence_type == "TOP_CLOSURE_PROTRUSION" for e in rib.evidence)


def test_detect_rib_without_thickness_metric():
    """Verify rib without transverse boundary edge strictly sets thickness=None (zero synthetic fallback)."""
    # Identical topology but cap transverse edges lack length measurements
    faces = (
        CadFace(id="F_BASE", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), area=10000.0, edge_ids=("E_B1", "E_B2")),
        CadFace(id="F_RIB_SIDE1", surface_type="PLANE", is_planar=True, normal=(1.0, 0.0, 0.0), area=1200.0, edge_ids=("E_B1", "E_CAP1")),
        CadFace(id="F_RIB_SIDE2", surface_type="PLANE", is_planar=True, normal=(-1.0, 0.0, 0.0), area=1200.0, edge_ids=("E_B2", "E_CAP2")),
        CadFace(id="F_RIB_CAP", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), area=180.0, edge_ids=("E_CAP1", "E_CAP2", "E_CW_UNKNOWN")),
    )
    edges = (
        CadEdge(id="E_B1", length=60.0),
        CadEdge(id="E_B2", length=60.0),
        CadEdge(id="E_CAP1", length=60.0),
        CadEdge(id="E_CAP2", length=60.0),
        CadEdge(id="E_CW_UNKNOWN", length=None),
    )

    model = GeometryModel(
        model_id="M_RIB_NO_THICKNESS",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    ribs = detect_ribs(model, topo)

    assert len(ribs) == 1
    rib = ribs[0]
    assert rib.feature_type == FeatureType.RIB
    assert rib.status == CapabilityStatus.ASSISTED
    # Must NOT fabricate thickness=5.0
    assert rib.geometry["thickness"] is None
    assert rib.geometry["slenderness_ratio"] is None
    assert rib.geometry["reason"] == "INSUFFICIENT_THICKNESS_EVIDENCE"
    assert any(e.evidence_type == "LOCAL_SCALE_METRIC" and e.result == "INSUFFICIENT_EVIDENCE" for e in rib.evidence)


def test_detect_rib_groove_rejection():
    """Verify internal groove/pocket is conservatively rejected as a rib (protrusion evidence guard)."""
    # Block with an internal groove (U-channel)
    # The groove walls face inwards toward each other, opening up to ambient space without an outward cap
    faces = (
        CadFace(id="F_SUBSTRATE", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), edge_ids=("E_G1", "E_G2")),
        CadFace(id="F_GROOVE_W1", surface_type="PLANE", is_planar=True, normal=(1.0, 0.0, 0.0), edge_ids=("E_G1", "E_GBOT1")),
        CadFace(id="F_GROOVE_W2", surface_type="PLANE", is_planar=True, normal=(-1.0, 0.0, 0.0), edge_ids=("E_G2", "E_GBOT2")),
        CadFace(id="F_GROOVE_BOT", surface_type="PLANE", is_planar=True, normal=(0.0, -1.0, 0.0), edge_ids=("E_GBOT1", "E_GBOT2")),
    )
    edges = (
        CadEdge(id="E_G1", length=50.0),
        CadEdge(id="E_G2", length=50.0),
        CadEdge(id="E_GBOT1", length=50.0),
        CadEdge(id="E_GBOT2", length=50.0),
    )

    model = GeometryModel(
        model_id="M_INTERNAL_GROOVE",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    ribs = detect_ribs(model, topo)

    # Groove must NOT be misreported as a rib
    assert len(ribs) == 0


def test_detect_rib_oversized_slab_rejection():
    """Verify primary massive slab (e.g. main block body) is rejected as a rib."""
    # Plain rectangular block (6 faces) with two massive opposing faces (100x100mm)
    faces = (
        CadFace(id="F_TOP_SLAB", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), area=10000.0, edge_ids=("E1", "E2")),
        CadFace(id="F_BOT_SLAB", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, -1.0), area=10000.0, edge_ids=("E3", "E4")),
        CadFace(id="F_SIDE1", surface_type="PLANE", is_planar=True, normal=(1.0, 0.0, 0.0), area=2000.0, edge_ids=("E1", "E3")),
        CadFace(id="F_SIDE2", surface_type="PLANE", is_planar=True, normal=(-1.0, 0.0, 0.0), area=2000.0, edge_ids=("E2", "E4")),
    )
    edges = (
        CadEdge(id="E1", length=100.0),
        CadEdge(id="E2", length=100.0),
        CadEdge(id="E3", length=100.0),
        CadEdge(id="E4", length=100.0),
    )

    model = GeometryModel(
        model_id="M_MAIN_SLAB",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 20.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    ribs = detect_ribs(model, topo)
    assert len(ribs) == 0


def test_detect_rib_non_manifold_blocked():
    """Verify rib with non-manifold edge defect fails closed to BLOCKED."""
    faces = (
        CadFace(id="F_BASE", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), edge_ids=("E_BAD", "E_B2")),
        CadFace(id="F_RIB_SIDE1", surface_type="PLANE", is_planar=True, normal=(1.0, 0.0, 0.0), edge_ids=("E_BAD", "E_CAP1")),
        CadFace(id="F_RIB_SIDE2", surface_type="PLANE", is_planar=True, normal=(-1.0, 0.0, 0.0), edge_ids=("E_B2", "E_CAP2")),
        CadFace(id="F_RIB_CAP", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), edge_ids=("E_CAP1", "E_CAP2", "E_BAD")),
    )
    edges = (
        CadEdge(id="E_BAD", length=60.0),  # Shared by F_BASE, F_RIB_SIDE1, F_RIB_CAP -> 3 faces non-manifold
        CadEdge(id="E_B2", length=60.0),
        CadEdge(id="E_CAP1", length=60.0),
        CadEdge(id="E_CAP2", length=60.0),
    )

    model = GeometryModel(
        model_id="M_DEFECT_RIB",
        provenance=_make_dummy_provenance(),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    assert "E_BAD" in topo.non_manifold_edges

    ribs = detect_ribs(model, topo)
    assert len(ribs) == 1
    assert ribs[0].status == CapabilityStatus.BLOCKED
    assert ribs[0].confidence == 0.3
    assert ribs[0].geometry["reason"] == "NON_MANIFOLD_TOPOLOGY_DEFECT"
    assert any(e.evidence_type == "TOPOLOGICAL_INTEGRITY" and e.result == "FAIL" for e in ribs[0].evidence)


def test_detect_contact_plane_boss_with_hole():
    """Verify contact plane spotface anchored by inner loop hole boundary."""
    faces = (
        CadFace(
            id="F_SPOTFACE",
            surface_type="PLANE",
            is_planar=True,
            normal=(0.0, 0.0, 1.0),
            area=800.0,
            edge_ids=("E_OUTER1", "E_CIRC_HOLE"),
            inner_loops=(CadLoop(id="L_INNER", is_outer=False, edge_ids=("E_CIRC_HOLE",)),),
        ),
        CadFace(
            id="F_HOLE_BARREL",
            surface_type="CYLINDRICAL_SURFACE",
            is_planar=False,
            edge_ids=("E_CIRC_HOLE", "E_CIRC_BOT"),
        ),
        CadFace(id="F_BOT", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, -1.0), edge_ids=("E_CIRC_BOT",)),
    )
    edges = (
        CadEdge(id="E_OUTER1", length=100.0),
        CadEdge(id="E_CIRC_HOLE", length=31.4159),
        CadEdge(id="E_CIRC_BOT", length=31.4159),
    )

    model = GeometryModel(
        model_id="M_SPOTFACE_HOLE",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 30.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    holes = detect_fastener_holes(model, topo)
    contact_planes = detect_contact_planes(model, topo, holes=holes)

    assert len(contact_planes) >= 1
    spotface = next(cp for cp in contact_planes if cp.face_ids == ("F_SPOTFACE",))
    assert spotface.feature_type == FeatureType.CONTACT_PLANE
    assert spotface.status == CapabilityStatus.ASSISTED
    assert spotface.geometry["has_inner_hole"] is True
    assert len(spotface.geometry["associated_hole_ids"]) == 1
    assert spotface.geometry["normal"] == [0.0, 0.0, 1.0]
    assert spotface.geometry["area"] == 800.0
    assert any(e.evidence_type == "FASTENER_MOUNTING_ANCHOR" for e in spotface.evidence)


def test_detect_contact_plane_flange():
    """Verify flange mating surface anchored by orthogonal stepped shoulder walls."""
    # Flange collar face F_FLANGE (normal +Z) bounded by perpendicular stepped wall F_SHOULDER (normal +X)
    faces = (
        CadFace(id="F_FLANGE", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), area=1500.0, edge_ids=("E_STEP", "E_OUTER")),
        CadFace(id="F_SHOULDER", surface_type="PLANE", is_planar=True, normal=(1.0, 0.0, 0.0), area=300.0, edge_ids=("E_STEP", "E_WALL")),
    )
    edges = (
        CadEdge(id="E_STEP", length=50.0),
        CadEdge(id="E_OUTER", length=120.0),
        CadEdge(id="E_WALL", length=50.0),
    )

    model = GeometryModel(
        model_id="M_FLANGE_STEP",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 50.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    contact_planes = detect_contact_planes(model, topo)

    assert len(contact_planes) == 1
    flange = contact_planes[0]
    assert flange.feature_type == FeatureType.CONTACT_PLANE
    assert flange.status == CapabilityStatus.ASSISTED
    assert flange.geometry["normal"] == [0.0, 0.0, 1.0]
    assert flange.geometry["has_inner_hole"] is False
    assert any(e.evidence_type == "FLANGE_BEARING_ANCHOR" for e in flange.evidence)


def test_detect_contact_plane_unnormalized_normal():
    """Verify non-unit normal vector strictly results in normal=None without synthetic normalization."""
    # Face with unnormalized normal (0, 0, 5.0) -> norm = 5.0
    faces = (
        CadFace(
            id="F_FLANGE_UNNORMAL",
            surface_type="PLANE",
            is_planar=True,
            normal=(0.0, 0.0, 5.0),
            area=1200.0,
            edge_ids=("E_STEP",),
            inner_loops=(CadLoop(id="L1", is_outer=False, edge_ids=("E_STEP",)),),
        ),
    )
    edges = (
        CadEdge(id="E_STEP", length=30.0),
    )

    model = GeometryModel(
        model_id="M_UNNORMAL_FACE",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 30.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    contact_planes = detect_contact_planes(model, topo)

    assert len(contact_planes) == 1
    cp = contact_planes[0]
    assert cp.geometry["normal"] is None
    assert cp.geometry["reason"] == "UNVERIFIED_NORMAL_VECTOR"
    assert any(e.evidence_type == "SURFACE_NORMAL_UNIT_METRIC" and e.result == "INSUFFICIENT_EVIDENCE" for e in cp.evidence)


def test_detect_contact_plane_fillet_chamfer_exclusion():
    """Verify transition faces (fillets, chamfers, rib walls) are excluded from contact planes in consolidated pipeline."""
    faces = (
        CadFace(id="F_TOP_SPOT", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), area=2000.0, edge_ids=("E_F1", "E_CH1"), inner_loops=(CadLoop(id="L1", is_outer=False, edge_ids=("E_F1",)),)),
        CadFace(id="F_FILLET", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E_F1", "E_F2", "E_ARC")),
        CadFace(id="F_CHAMFER", surface_type="PLANE", is_planar=True, normal=(0.0, 0.707, 0.707), area=50.0, edge_ids=("E_CH1", "E_CH2", "E_CW1", "E_CW2")),
        CadFace(id="F_SIDE", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), area=2000.0, edge_ids=("E_F2", "E_CH2")),
    )
    edges = (
        CadEdge(id="E_F1", length=50.0),
        CadEdge(id="E_F2", length=50.0),
        CadEdge(id="E_ARC", curve_type="CIRCLE", length=18.8495),
        CadEdge(id="E_CH1", length=50.0),
        CadEdge(id="E_CH2", length=50.0),
        CadEdge(id="E_CW1", length=2.0),
        CadEdge(id="E_CW2", length=2.0),
    )

    model = GeometryModel(
        model_id="M_TRANSITION_CHECK",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    all_feats = detect_features(model, topo)

    # Chamfer ribbon and fillet transition must NOT be labeled as CONTACT_PLANE
    chamfer_feats = [f for f in all_feats if f.feature_type == FeatureType.CHAMFER]
    fillet_feats = [f for f in all_feats if f.feature_type == FeatureType.FILLET]
    contact_feats = [f for f in all_feats if f.feature_type == FeatureType.CONTACT_PLANE]

    assert len(chamfer_feats) == 1
    assert len(fillet_feats) == 1
    # Chamfer face F_CHAMFER and fillet F_FILLET are not in contact plane face IDs
    contact_face_ids = {fid for cp in contact_feats for fid in cp.face_ids}
    assert "F_CHAMFER" not in contact_face_ids
    assert "F_FILLET" not in contact_face_ids


def test_detect_contact_plane_no_assembly_pair_actions():
    """Verify Contact Plane detection creates strictly zero assembly contact pairs or interaction actions."""
    faces = (
        CadFace(id="F_PLATE", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), area=500.0, edge_ids=("E1",), inner_loops=(CadLoop(id="L1", is_outer=False, edge_ids=("E1",)),)),
    )
    edges = (CadEdge(id="E1", length=20.0),)

    model = GeometryModel(
        model_id="M_ISOLATED_CONTACT",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 20.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    cps = detect_contact_planes(model, topo)
    assert len(cps) == 1
    cp = cps[0]

    # Verify candidate dictionary contains zero contact interaction / tie / master-slave action fields
    d = cp.to_dict()
    forbidden_keys = {"interaction_pair", "contact_pair", "master_surface", "slave_surface", "tie_action", "contact_action"}
    assert not any(k in d for k in forbidden_keys)
    assert not any(k in d.get("geometry", {}) for k in forbidden_keys)


def test_detect_features_all_five_consolidated():
    """Verify consolidated multi-feature extraction across all 5 engineering feature classes."""
    # Complex engineering bracket with:
    # 1. Through fastener hole (F_HOLE)
    # 2. Cylindrical transition fillet (F_FILLET)
    # 3. Planar chamfer ribbon (F_CHAMFER)
    # 4. Stiffener rib (F_RIB_SIDE1, F_RIB_SIDE2, F_RIB_CAP)
    # 5. Fastener spotface contact plane (F_SPOTFACE)
    faces = (
        # Fastener Spotface Plane (Contact Plane)
        CadFace(id="F_SPOTFACE", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), area=5000.0, edge_ids=("E_H_TOP", "E_RIB_B1", "E_RIB_B2", "E_FILLET_1", "E_CHAMFER_1"), inner_loops=(CadLoop(id="L_HOLE", is_outer=False, edge_ids=("E_H_TOP",)),)),
        # Hole
        CadFace(id="F_HOLE_BOT", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, -1.0), area=5000.0, edge_ids=("E_H_BOT",)),
        CadFace(id="F_HOLE", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E_H_TOP", "E_H_BOT")),
        # Fillet
        CadFace(id="F_FILLET", surface_type="CYLINDRICAL_SURFACE", is_planar=False, edge_ids=("E_FILLET_1", "E_FILLET_2", "E_FILLET_ARC")),
        CadFace(id="F_SIDE_F", surface_type="PLANE", is_planar=True, normal=(1.0, 0.0, 0.0), area=2000.0, edge_ids=("E_FILLET_2",)),
        # Chamfer
        CadFace(id="F_CHAMFER", surface_type="PLANE", is_planar=True, normal=(0.0, 0.707, 0.707), area=60.0, edge_ids=("E_CHAMFER_1", "E_CHAMFER_2", "E_CW1", "E_CW2")),
        CadFace(id="F_SIDE_C", surface_type="PLANE", is_planar=True, normal=(0.0, 1.0, 0.0), area=2000.0, edge_ids=("E_CHAMFER_2",)),
        # Rib
        CadFace(id="F_RIB_SIDE1", surface_type="PLANE", is_planar=True, normal=(1.0, 0.0, 0.0), area=800.0, edge_ids=("E_RIB_B1", "E_RIB_CAP1", "E_RH1", "E_RH2")),
        CadFace(id="F_RIB_SIDE2", surface_type="PLANE", is_planar=True, normal=(-1.0, 0.0, 0.0), area=800.0, edge_ids=("E_RIB_B2", "E_RIB_CAP2", "E_RH3", "E_RH4")),
        CadFace(id="F_RIB_CAP", surface_type="PLANE", is_planar=True, normal=(0.0, 0.0, 1.0), area=120.0, edge_ids=("E_RIB_CAP1", "E_RIB_CAP2", "E_RCW1", "E_RCW2")),
    )
    edges = (
        # Hole edges
        CadEdge(id="E_H_TOP", length=31.4159),
        CadEdge(id="E_H_BOT", length=31.4159),
        # Fillet edges
        CadEdge(id="E_FILLET_1", length=50.0),
        CadEdge(id="E_FILLET_2", length=50.0),
        CadEdge(id="E_FILLET_ARC", curve_type="CIRCLE", length=18.8495),
        # Chamfer edges
        CadEdge(id="E_CHAMFER_1", length=50.0),
        CadEdge(id="E_CHAMFER_2", length=50.0),
        CadEdge(id="E_CW1", length=2.0),
        CadEdge(id="E_CW2", length=2.0),
        # Rib edges
        CadEdge(id="E_RIB_B1", length=40.0),
        CadEdge(id="E_RIB_B2", length=40.0),
        CadEdge(id="E_RIB_CAP1", length=40.0),
        CadEdge(id="E_RIB_CAP2", length=40.0),
        CadEdge(id="E_RCW1", length=3.0),
        CadEdge(id="E_RCW2", length=3.0),
        CadEdge(id="E_RH1", length=20.0),
        CadEdge(id="E_RH2", length=20.0),
        CadEdge(id="E_RH3", length=20.0),
        CadEdge(id="E_RH4", length=20.0),
    )

    model = GeometryModel(
        model_id="M_ALL_FIVE_FEATS",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=faces,
        edges=edges,
    )

    topo = normalize_topology(model)
    all_features = detect_features(model, topo)

    # All 5 feature classes must be present
    found_types = {f.feature_type for f in all_features}
    assert FeatureType.FASTENER_HOLE in found_types
    assert FeatureType.FILLET in found_types
    assert FeatureType.CHAMFER in found_types
    assert FeatureType.RIB in found_types
    assert FeatureType.CONTACT_PLANE in found_types

    # Strict deterministic sorting by feature_id
    feature_ids = [f.feature_id for f in all_features]
    assert feature_ids == sorted(feature_ids)

    # Permuted / shuffled model invariance check
    model_shuffled = GeometryModel(
        model_id="M_ALL_FIVE_SHUFFLED",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        faces=tuple(reversed(faces)),
        edges=tuple(reversed(edges)),
    )
    topo_shuffled = normalize_topology(model_shuffled)
    features_shuffled = detect_features(model_shuffled, topo_shuffled)

    assert len(all_features) == len(features_shuffled)
    for f1, f2 in zip(all_features, features_shuffled):
        assert f1.feature_id == f2.feature_id
        assert f1.feature_type == f2.feature_type
        assert f1.status == f2.status
        assert f1.face_ids == f2.face_ids
        assert f1.edge_ids == f2.edge_ids
        assert f1.geometry == f2.geometry
