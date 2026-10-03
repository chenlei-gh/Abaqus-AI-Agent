"""Unit tests for Track GA-1.1: Neutral CAD Ingestion and Standardized GeometryModel."""

import os
import tempfile
import pytest

from abaqus_ai_agent.capability_boundary import CapabilityStatus
from abaqus_ai_agent.geometry import (
    CadBoundingBox,
    CadFormat,
    CadIngestionError,
    CadUnit,
    CadVertex,
    GeometryModel,
    classify_cad_model,
    compute_file_sha256,
    detect_cad_format,
    ingest_cad_file,
)


# Sample authentic minimal STEP AP203 manifold solid representation
MINIMAL_STEP_SOLID = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Abaqus AI Agent Test Solid'),'2;1');
FILE_NAME('bracket.stp','2026-10-03T10:00:00',('Engineer'),('SIMULIA'),'Abaqus 2025','Preprocessor','');
FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));
ENDSEC;
DATA;
#10 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );
#20 = CARTESIAN_POINT('ORIGIN',(0.0, 0.0, 0.0));
#21 = CARTESIAN_POINT('P1',(100.0, 0.0, 0.0));
#22 = CARTESIAN_POINT('P2',(100.0, 50.0, 0.0));
#23 = CARTESIAN_POINT('P3',(0.0, 50.0, 0.0));
#24 = CARTESIAN_POINT('P4',(0.0, 0.0, 20.0));
#25 = CARTESIAN_POINT('P5',(100.0, 0.0, 20.0));
#26 = CARTESIAN_POINT('P6',(100.0, 50.0, 20.0));
#27 = CARTESIAN_POINT('P7',(0.0, 50.0, 20.0));
#30 = LINE('L1', #20, #21);
#31 = LINE('L2', #21, #22);
#32 = EDGE_CURVE('E1', #20, #21, #30, .T.);
#33 = EDGE_CURVE('E2', #21, #22, #31, .T.);
#40 = ADVANCED_FACE('F1', (#32), #20, .T.);
#41 = ADVANCED_FACE('F2', (#33), #21, .T.);
#50 = CLOSED_SHELL('SHELL_1', (#40, #41));
#60 = MANIFOLD_SOLID_BREP('SOLID_1', #50);
ENDSEC;
END-ISO-10303-21;
"""

MINIMAL_STEP_OPEN_SHELL = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Sheet Body Surface'),'2;1');
FILE_NAME('sheet.stp','2026-10-03',('User'),(''),'','','');
FILE_SCHEMA(('AP214'));
ENDSEC;
DATA;
#10 = CARTESIAN_POINT('',(0.0, 0.0, 0.0));
#11 = CARTESIAN_POINT('',(50.0, 50.0, 0.0));
#20 = ADVANCED_FACE('F1', (), #10, .T.);
#30 = OPEN_SHELL('SHELL_OPEN', (#20));
ENDSEC;
END-ISO-10303-21;
"""

MINIMAL_IGES_FILE = (
    "                                                                        S      1\n"
    "1H,,1H;,4HSTEP,8Htest.igs,10HAgent,10HCompany,32,38,6,308,15,4Htest,    G      1\n"
    "1.0,2,2HMM,1,0.0,15,1.0D-06,1.0D+06,10HAgent,10HCompany,11,0;          G      2\n"
    "     186       1       0       0       0       0       0       000010001D      1\n"
    "     186       0       0       1       0                               0D      2\n"
    "     514       2       0       0       0       0       0       000010001D      3\n"
    "     514       0       0       1       0                               0D      4\n"
    "     144       3       0       0       0       0       0       000010001D      5\n"
    "     144       0       0       1       0                               0D      6\n"
    "     110       4       0       0       0       0       0       000010001D      7\n"
    "     110       0       0       1       0                               0D      8\n"
    "     116       5       0       0       0       0       0       000010001D      9\n"
    "     116       0       0       1       0                               0D     10\n"
    "186,1,0;                                                               1P      1\n"
    "514,1,1;                                                               3P      2\n"
    "144,1,0;                                                               5P      3\n"
    "110,0.0,0.0,0.0,10.0,10.0,10.0;                                        7P      4\n"
    "116,0.0,0.0,0.0;                                                       9P      5\n"
    "S      1G      2D     10P      5                                        T      1\n"
)


def test_cad_format_detection_and_sha256():
    """Verify format detection and cryptographically sound hashing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        step_path = os.path.join(tmpdir, "model.step")
        with open(step_path, "w", encoding="utf-8") as f:
            f.write(MINIMAL_STEP_SOLID)

        assert detect_cad_format(step_path) == CadFormat.STEP
        sha = compute_file_sha256(step_path)
        assert len(sha) == 64
        assert int(sha, 16) > 0


def test_step_solid_ingestion_and_provenance():
    """Verify parsing of valid STEP AP203 solid, bounding box, and SUPPORTED status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        step_path = os.path.join(tmpdir, "bracket.stp")
        with open(step_path, "w", encoding="utf-8") as f:
            f.write(MINIMAL_STEP_SOLID)

        model = ingest_cad_file(step_path)

        assert model.provenance.cad_format == CadFormat.STEP
        assert model.provenance.cad_schema == "CONFIG_CONTROL_DESIGN"
        assert model.provenance.preprocessor == "Abaqus 2025"
        assert model.unit == CadUnit.MM
        assert model.solid_count == 1
        assert model.shell_count == 1
        assert model.face_count == 2
        assert model.edge_count == 2
        assert model.vertex_count == 8
        assert model.is_manifold_solid is True
        assert model.has_open_shells is False

        # Bounding box verification (X: 0~100, Y: 0~50, Z: 0~20)
        assert model.bounding_box is not None
        assert model.bounding_box.min_x == 0.0
        assert model.bounding_box.max_x == 100.0
        assert model.bounding_box.min_y == 0.0
        assert model.bounding_box.max_y == 50.0
        assert model.bounding_box.min_z == 0.0
        assert model.bounding_box.max_z == 20.0
        assert model.bounding_box.dimensions == (100.0, 50.0, 20.0)
        assert model.bounding_box.center == (50.0, 25.0, 10.0)

        # 4-state Capability Classification
        cap = classify_cad_model(model)
        assert cap.status == CapabilityStatus.SUPPORTED
        assert cap.engineering_verified is True
        assert "manifold closed solid" in cap.reason


def test_step_open_shell_assisted_classification():
    """Verify open shell detection transitions to ASSISTED capability boundary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        step_path = os.path.join(tmpdir, "sheet.stp")
        with open(step_path, "w", encoding="utf-8") as f:
            f.write(MINIMAL_STEP_OPEN_SHELL)

        model = ingest_cad_file(step_path)
        assert model.shell_count == 1
        assert model.has_open_shells is True
        assert model.is_manifold_solid is False

        cap = classify_cad_model(model)
        assert cap.status == CapabilityStatus.ASSISTED
        assert "open shell" in cap.reason


def test_iges_ingestion():
    """Verify IGES 80-column structured entity extraction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        iges_path = os.path.join(tmpdir, "sample.igs")
        with open(iges_path, "w", encoding="utf-8") as f:
            f.write(MINIMAL_IGES_FILE)

        assert detect_cad_format(iges_path) == CadFormat.IGES
        model = ingest_cad_file(iges_path)

        assert model.provenance.cad_format == CadFormat.IGES
        assert model.unit == CadUnit.MM
        assert model.solid_count == 1
        assert model.shell_count == 1
        assert model.face_count == 1
        assert model.edge_count == 1
        assert model.vertex_count == 1

        cap = classify_cad_model(model)
        assert cap.status in (CapabilityStatus.SUPPORTED, CapabilityStatus.ASSISTED)


def test_cad_ingestion_errors_and_blocked_states():
    """Verify fail-closed error handling on corrupt or missing files."""
    # Non-existent file
    with pytest.raises(FileNotFoundError):
        ingest_cad_file("non_existent_file.stp")

    # Empty 0-byte file
    with tempfile.TemporaryDirectory() as tmpdir:
        empty_path = os.path.join(tmpdir, "empty.stp")
        with open(empty_path, "w") as f:
            pass
        with pytest.raises(CadIngestionError, match="empty"):
            ingest_cad_file(empty_path)

        # Corrupt non-CAD file
        corrupt_path = os.path.join(tmpdir, "corrupt.stp")
        with open(corrupt_path, "w") as f:
            f.write("Random text not conforming to ISO-10303-21 standard")
        with pytest.raises(CadIngestionError, match="not a valid ISO-10303-21"):
            ingest_cad_file(corrupt_path)


def test_cad_bounding_box_validation_and_methods():
    """Verify CadBoundingBox invariants and geometric calculations."""
    bbox = CadBoundingBox(0.0, 0.0, 0.0, 10.0, 20.0, 30.0)
    assert bbox.dimensions == (10.0, 20.0, 30.0)
    assert bbox.center == (5.0, 10.0, 15.0)
    assert pytest.approx(bbox.diagonal, 0.001) == 37.41657

    with pytest.raises(ValueError, match="invalid bounding box"):
        CadBoundingBox(10.0, 0.0, 0.0, 5.0, 10.0, 10.0)


def test_geometry_model_serialization():
    """Verify GeometryModel serialization dictionary matches contract."""
    with tempfile.TemporaryDirectory() as tmpdir:
        step_path = os.path.join(tmpdir, "bracket.stp")
        with open(step_path, "w", encoding="utf-8") as f:
            f.write(MINIMAL_STEP_SOLID)

        model = ingest_cad_file(step_path)
        d = model.to_dict()
        assert d["format"] == "STEP"
        assert d["unit"] == "mm"
        assert d["counts"]["solids"] == 1
        assert d["counts"]["vertices"] == 8
        assert d["is_manifold_solid"] is True
        assert d["bounding_box"]["dimensions"] == [100.0, 50.0, 20.0]
