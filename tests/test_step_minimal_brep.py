"""Comprehensive Unit Tests for GA-1.1 STEP Minimal B-Rep Qualification (P1/P2).

Verifies the pure-python deterministic B-Rep entity extractor across the full pipeline:
STEP File -> GeometryModel -> NormalizedTopology -> FeatureCandidate -> Meshability -> GeometryMeshPlan.

CRITICAL DISCIPLINE:
Zero FeatureCandidate fixtures or mock geometry models allowed.
All assertions operate strictly on models ingested from real STEP text/files.
"""

import os
import tempfile
import pytest

from abaqus_ai_agent.capability_boundary import CapabilityStatus
from abaqus_ai_agent.geometry import (
    CadBoundingBox,
    CadFormat,
    CadUnit,
    FeatureType,
    HoleSubType,
    assess_meshability,
    classify_cad_model,
    detect_fastener_holes,
    detect_features,
    detect_fillets,
    ingest_cad_file,
    normalize_topology,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "step")
PLATE_HOLE_STEP = os.path.join(FIXTURES_DIR, "plate_with_hole.step")
STEPPED_FILLET_STEP = os.path.join(FIXTURES_DIR, "stepped_fillet_bar.step")


def test_plate_with_hole_ingestion_hierarchy():
    """Verify B-Rep hierarchy: Solid -> Shell -> Face -> Loop -> Edge -> Vertex."""
    assert os.path.exists(PLATE_HOLE_STEP)
    model = ingest_cad_file(PLATE_HOLE_STEP)

    assert model.provenance.cad_format == CadFormat.STEP
    assert model.unit == CadUnit.MM
    assert model.solid_count == 1
    assert model.shell_count == 1
    assert model.face_count == 7  # 6 outer box faces + 1 hole cylinder
    assert model.is_manifold_solid is True
    assert model.has_open_shells is False

    # Check bounding box (100 x 100 x 20)
    assert model.bounding_box is not None
    assert model.bounding_box.dimensions == (100.0, 100.0, 20.0)

    # Check solid and shell linkage
    solid = model.solids[0]
    shell = model.shells[0]
    assert len(solid.shell_ids) == 1
    assert solid.shell_ids[0] == shell.id
    assert len(shell.face_ids) == 7

    # Check capability classification
    cap = classify_cad_model(model)
    assert cap.status == CapabilityStatus.SUPPORTED
    assert cap.engineering_verified is True


def test_plate_with_hole_loops_and_edges():
    """Verify Outer Loop, Inner Loop, and Oriented Edge directions on top/bottom faces."""
    model = ingest_cad_file(PLATE_HOLE_STEP)
    topo = normalize_topology(model)

    top_face = next(f for f in model.faces if f.id == "F_271")
    bot_face = next(f for f in model.faces if f.id == "F_272")
    hole_face = next(f for f in model.faces if f.id == "F_277")

    # Top face must have 1 outer loop and 1 inner hole loop
    assert top_face.is_planar is True
    assert top_face.normal == (0.0, 0.0, 1.0)
    assert top_face.outer_loop is not None
    assert top_face.outer_loop.is_outer is True
    assert len(top_face.outer_loop.edge_ids) == 4
    assert len(top_face.inner_loops) == 1
    assert top_face.inner_loops[0].is_outer is False
    assert len(top_face.inner_loops[0].edge_ids) == 1
    assert top_face.inner_loops[0].edge_ids[0] == "E_184"  # Top hole circle

    # Bottom face must have 1 outer loop and 1 inner hole loop
    assert bot_face.is_planar is True
    assert bot_face.normal == (0.0, 0.0, -1.0)
    assert bot_face.outer_loop is not None
    assert len(bot_face.inner_loops) == 1
    assert bot_face.inner_loops[0].edge_ids[0] == "E_183"  # Bottom hole circle

    # Hole cylinder face
    assert hole_face.surface_type == "CYLINDRICAL_SURFACE"
    assert hole_face.is_planar is False

    # Normalized topology bidirectional adjacency
    top_adj = topo.get_adjacent_faces(top_face.id)
    assert hole_face.id in top_adj
    bot_adj = topo.get_adjacent_faces(bot_face.id)
    assert hole_face.id in bot_adj
    hole_adj = topo.get_adjacent_faces(hole_face.id)
    assert top_face.id in hole_adj
    assert bot_face.id in hole_adj


def test_plate_with_hole_end_to_end_recognition_no_fixture():
    """Verify 100% autonomous FASTENER_HOLE detection and mesh planning from STEP."""
    model = ingest_cad_file(PLATE_HOLE_STEP)
    topo = normalize_topology(model)

    features = detect_features(model, topo)
    hole_feats = [f for f in features if f.feature_type == FeatureType.FASTENER_HOLE]

    assert len(hole_feats) == 1
    hole = hole_feats[0]
    assert hole.status == CapabilityStatus.SUPPORTED
    assert hole.geometry["sub_type"] == HoleSubType.THROUGH.value
    assert hole.geometry["is_fastener_hole"] is True
    assert 19.9 <= hole.geometry["diameter"] <= 20.1  # Exactly 20.0 mm
    assert hole.confidence >= 0.90

    # Downstream GA-1.4 Meshability Assessment
    mesh_res = assess_meshability(model, topo, features, target_mesh_size=10.0)
    assert mesh_res.is_meshable is True
    assert mesh_res.status == CapabilityStatus.SUPPORTED

    # Hole candidate produces suggested_size = 0.25 * D = 5.0 mm
    refinements = mesh_res.refinement_candidates
    hole_ref = next((r for r in refinements if r.feature_type == FeatureType.FASTENER_HOLE), None)
    assert hole_ref is not None
    assert hole_ref.characteristic_value == 20.0
    assert hole_ref.suggested_size == 5.0

    # GeometryMeshPlan handoff
    plan = mesh_res.to_geometry_mesh_plan(global_size=10.0)
    assert plan.global_size == 10.0
    assert len(plan.refinements) >= 1
    hole_plan_ref = next((r for r in plan.refinements if r.target_size == 5.0), None)
    assert hole_plan_ref is not None
    assert hole_plan_ref.requires_partition is False


def test_stepped_fillet_bar_ingestion_and_recognition_no_fixture():
    """Verify autonomous FILLET recognition and mesh planning from stepped_fillet_bar.step."""
    assert os.path.exists(STEPPED_FILLET_STEP)
    model = ingest_cad_file(STEPPED_FILLET_STEP)

    assert model.provenance.cad_format == CadFormat.STEP
    assert model.solid_count == 1
    assert model.shell_count == 1
    assert model.face_count == 9  # 8 planar faces + 1 fillet cylinder face
    assert model.is_manifold_solid is True

    topo = normalize_topology(model)
    features = detect_features(model, topo)

    fillets = [f for f in features if f.feature_type == FeatureType.FILLET]
    assert len(fillets) == 1
    fillet = fillets[0]
    assert fillet.status == CapabilityStatus.ASSISTED  # Honest no-synthetic-G1 rule
    assert fillet.geometry["is_constant_radius"] is True
    assert 4.9 <= fillet.geometry["radius"] <= 5.1  # R = 5.0 mm

    # Downstream GA-1.4 Meshability Assessment
    mesh_res = assess_meshability(model, topo, features, target_mesh_size=10.0)
    assert mesh_res.is_meshable is True
    assert mesh_res.status == CapabilityStatus.SUPPORTED

    fillet_ref = next((r for r in mesh_res.refinement_candidates if r.feature_type == FeatureType.FILLET), None)
    assert fillet_ref is not None
    assert fillet_ref.characteristic_value == 5.0
    assert fillet_ref.suggested_size == 2.5  # 0.5 * R

    # GeometryMeshPlan handoff
    plan = mesh_res.to_geometry_mesh_plan(global_size=10.0)
    assert plan.global_size == 10.0
    fillet_plan_ref = next((r for r in plan.refinements if r.target_size == 2.5), None)
    assert fillet_plan_ref is not None
    assert fillet_plan_ref.requires_partition is False


def test_step_unit_resolution_contracts():
    """Verify source STEP unit detection (.MILLI. -> MM, .METRE. -> M, .INCH. -> IN)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Metre unit STEP
        metre_step = os.path.join(tmpdir, "model_m.stp")
        with open(metre_step, "w", encoding="utf-8") as f:
            f.write(
                "ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('AP203'));\nENDSEC;\nDATA;\n"
                "#10 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT($,.METRE.) );\n"
                "#20 = CARTESIAN_POINT('', (1.0, 2.0, 3.0));\n"
                "ENDSEC;\nEND-ISO-10303-21;\n"
            )
        model_m = ingest_cad_file(metre_step)
        assert model_m.unit == CadUnit.M

        # Inch unit STEP
        inch_step = os.path.join(tmpdir, "model_in.stp")
        with open(inch_step, "w", encoding="utf-8") as f:
            f.write(
                "ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('AP203'));\nENDSEC;\nDATA;\n"
                "#10 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT($,.INCH.) );\n"
                "#20 = CARTESIAN_POINT('', (1.0, 2.0, 3.0));\n"
                "ENDSEC;\nEND-ISO-10303-21;\n"
            )
        model_in = ingest_cad_file(inch_step)
        assert model_in.unit == CadUnit.IN


def test_step_permutation_invariance():
    """Verify that permuting entity IDs or definition lines produces identical canonical results."""
    with open(PLATE_HOLE_STEP, "r", encoding="utf-8") as f:
        lines = f.readlines()

    header_lines = []
    data_lines = []
    is_data = False
    for line in lines:
        if "DATA;" in line:
            is_data = True
            continue
        if "ENDSEC;" in line and is_data:
            break
        if is_data:
            data_lines.append(line)
        else:
            header_lines.append(line)

    # Reverse the order of entity lines in DATA section
    reversed_data = list(reversed(data_lines))
    permuted_content = "".join(header_lines) + "DATA;\n" + "".join(reversed_data) + "ENDSEC;\nEND-ISO-10303-21;\n"

    with tempfile.TemporaryDirectory() as tmpdir:
        perm_path = os.path.join(tmpdir, "permuted.stp")
        with open(perm_path, "w", encoding="utf-8") as f:
            f.write(permuted_content)

        model_orig = ingest_cad_file(PLATE_HOLE_STEP)
        model_perm = ingest_cad_file(perm_path)

        assert model_perm.solid_count == model_orig.solid_count
        assert model_perm.face_count == model_orig.face_count
        assert model_perm.edge_count == model_orig.edge_count
        assert model_perm.vertex_count == model_orig.vertex_count

        topo_orig = normalize_topology(model_orig)
        feats_orig = detect_features(model_orig, topo_orig)
        topo_perm = normalize_topology(model_perm)
        feats_perm = detect_features(model_perm, topo_perm)
        assert len(feats_perm) == len(feats_orig)
        assert tuple(f.feature_type for f in feats_perm) == tuple(f.feature_type for f in feats_orig)
        assert tuple(f.status for f in feats_perm) == tuple(f.status for f in feats_orig)

        hole_orig = next(f for f in feats_orig if f.feature_type == FeatureType.FASTENER_HOLE)
        hole_perm = next(f for f in feats_perm if f.feature_type == FeatureType.FASTENER_HOLE)
        assert hole_perm.geometry["diameter"] == hole_orig.geometry["diameter"] == 20.0


def test_step_unsupported_entity_fail_closed():
    """Verify that presence of unsupported CAD entities downgrades model to ASSISTED."""
    unsupported_step = (
        "ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('AP203'));\nENDSEC;\nDATA;\n"
        "#10 = CARTESIAN_POINT('', (0.0, 0.0, 0.0));\n"
        "#20 = B_SPLINE_SURFACE_WITH_KNOTS('SURF_SPLINE', 1, 1, ((#10)), .UNSPECIFIED., .F., .F., .F., (2, 2), (0.0, 1.0), (0.0, 1.0), .PIECEWISE_BEZIER_KNOTS.);\n"
        "#30 = ADVANCED_FACE('F1', (), #20, .T.);\n"
        "#40 = CLOSED_SHELL('SH1', (#30));\n"
        "#50 = MANIFOLD_SOLID_BREP('S1', #40);\n"
        "ENDSEC;\nEND-ISO-10303-21;\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        p = os.path.join(tmpdir, "unsupported.stp")
        with open(p, "w", encoding="utf-8") as f:
            f.write(unsupported_step)

        model = ingest_cad_file(p)
        assert len(model.metadata.get("unsupported_entities", [])) > 0

        cap = classify_cad_model(model)
        assert cap.status == CapabilityStatus.ASSISTED
        assert "unsupported entity" in cap.reason


def test_step_broken_reference_blocks_model():
    """Verify that unresolvable broken references block model from automated meshing."""
    broken_step = (
        "ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('AP203'));\nENDSEC;\nDATA;\n"
        "#10 = CARTESIAN_POINT('', (0.0, 0.0, 0.0));\n"
        "#30 = ADVANCED_FACE('F1', (), #9999, .T.);\n"  # #9999 does not exist
        "#40 = CLOSED_SHELL('SH1', (#30));\n"
        "#50 = MANIFOLD_SOLID_BREP('S1', #40);\n"
        "ENDSEC;\nEND-ISO-10303-21;\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        p = os.path.join(tmpdir, "broken.stp")
        with open(p, "w", encoding="utf-8") as f:
            f.write(broken_step)

        model = ingest_cad_file(p)
        assert len(model.metadata.get("broken_references", [])) > 0

        cap = classify_cad_model(model)
        assert cap.status == CapabilityStatus.BLOCKED
        assert "broken topological entity references" in cap.reason
