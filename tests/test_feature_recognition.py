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
