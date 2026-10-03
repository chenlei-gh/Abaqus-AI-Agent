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
    """Verify FeatureCandidate rejects non-primitive complex objects in geometry."""
    class ArbitraryRuntimeObject:
        pass

    import pytest
    with pytest.raises(TypeError, match="geometry value for key 'bad_obj' must be primitive scalar"):
        FeatureCandidate(
            feature_id="FEAT_BAD",
            feature_type=FeatureType.GENERIC_HOLE,
            status=CapabilityStatus.ASSISTED,
            confidence=0.5,
            geometry={"bad_obj": ArbitraryRuntimeObject()},
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
    assert chamfer.status == CapabilityStatus.SUPPORTED
    assert chamfer.confidence >= 0.85
    assert any(e.evidence_type == "TRANSITIONAL_PLANAR_TOPOLOGY" for e in chamfer.evidence)
    assert any(e.evidence_type == "NON_COPLANAR_NEIGHBORS" for e in chamfer.evidence)


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

    # Must find all 3 distinct features
    feat_types = [f.feature_type for f in features1]
    assert FeatureType.FASTENER_HOLE in feat_types
    assert FeatureType.FILLET in feat_types
    assert FeatureType.CHAMFER in feat_types
    assert len(features1) == 3

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

    assert len(features_perm) == 3
    for f1, fp in zip(features1, features_perm):
        assert f1.feature_id == fp.feature_id
        assert f1.feature_type == fp.feature_type
        assert f1.status == fp.status
        assert f1.face_ids == fp.face_ids
        assert f1.edge_ids == fp.edge_ids
        assert f1.geometry == fp.geometry
