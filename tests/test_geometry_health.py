"""Unit tests for Track GA-1.2: Multi-Layer Geometry Health Inspection Gate."""

from abaqus_ai_agent.capability_boundary import CapabilityStatus
from abaqus_ai_agent.geometry import (
    CadBoundingBox,
    CadEdge,
    CadFace,
    CadFormat,
    CadProvenance,
    CadShell,
    CadSolid,
    CadUnit,
    CadVertex,
    GeometryHealthReport,
    GeometryModel,
    HealthIssueKind,
    HealthSeverity,
    inspect_geometry_health,
)


def _make_dummy_provenance() -> CadProvenance:
    return CadProvenance(
        file_path="/mock/cad/part.stp",
        file_name="part.stp",
        file_sha256="a" * 64,
        file_size_bytes=1024,
        ingested_at="2026-10-03T12:00:00Z",
        cad_format=CadFormat.STEP,
        cad_schema="AP203",
    )


def test_health_clean_solid_supported():
    """Verify that a standard manifold solid passes health inspection as SUPPORTED."""
    model = GeometryModel(
        model_id="M_CLEAN_SOLID",
        provenance=_make_dummy_provenance(),
        unit=CadUnit.MM,
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 50.0, 20.0),
        solids=(CadSolid(id="S1"),),
        shells=(CadShell(id="SH1", is_closed=True),),
        faces=(
            CadFace(id="F1", area=1000.0, edge_ids=("E1", "E2")),
            CadFace(id="F2", area=1000.0, edge_ids=("E2", "E3")),
        ),
        edges=(
            CadEdge(id="E1", length=50.0),
            CadEdge(id="E2", length=50.0),
            CadEdge(id="E3", length=50.0),
        ),
        vertices=(CadVertex(id="V1", point=(0.0, 0.0, 0.0)),),
    )

    report = inspect_geometry_health(model, analysis_intent="solid")
    assert report.status == CapabilityStatus.SUPPORTED
    assert report.is_acceptable_for_analysis is True
    assert report.error_count == 0
    assert report.warning_count == 0


def test_health_degenerate_edge_blocked():
    """Verify degenerate near-zero edge is caught as an ERROR and BLOCKS analysis."""
    model = GeometryModel(
        model_id="M_DEG_EDGE",
        provenance=_make_dummy_provenance(),
        unit=CadUnit.MM,
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
        solids=(CadSolid(id="S1"),),
        edges=(CadEdge(id="E_COLLAPSED", length=1e-9),),
    )

    report = inspect_geometry_health(model, analysis_intent="solid")
    assert report.status == CapabilityStatus.BLOCKED
    assert report.is_acceptable_for_analysis is False
    assert any(i.kind == HealthIssueKind.DEGENERATE_EDGE for i in report.issues)


def test_health_degenerate_face_blocked():
    """Verify degenerate zero-area face is caught as an ERROR and BLOCKS analysis."""
    model = GeometryModel(
        model_id="M_DEG_FACE",
        provenance=_make_dummy_provenance(),
        unit=CadUnit.MM,
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
        solids=(CadSolid(id="S1"),),
        faces=(CadFace(id="F_ZERO", area=0.0),),
    )

    report = inspect_geometry_health(model, analysis_intent="solid")
    assert report.status == CapabilityStatus.BLOCKED
    assert any(i.kind == HealthIssueKind.DEGENERATE_FACE for i in report.issues)


def test_health_non_manifold_edge_blocked():
    """Verify edge shared by >2 faces is flagged as NON_MANIFOLD_EDGE and BLOCKED."""
    model = GeometryModel(
        model_id="M_NON_MANIFOLD",
        provenance=_make_dummy_provenance(),
        unit=CadUnit.MM,
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 20.0, 20.0, 20.0),
        faces=(
            CadFace(id="F1", area=100.0, edge_ids=("E_T_JUNCTION",)),
            CadFace(id="F2", area=100.0, edge_ids=("E_T_JUNCTION",)),
            CadFace(id="F3", area=100.0, edge_ids=("E_T_JUNCTION",)),
        ),
        edges=(CadEdge(id="E_T_JUNCTION", length=20.0),),
    )

    report = inspect_geometry_health(model, analysis_intent="solid")
    assert report.status == CapabilityStatus.BLOCKED
    issue = next(i for i in report.issues if i.kind == HealthIssueKind.NON_MANIFOLD_EDGE)
    assert issue.severity == HealthSeverity.ERROR
    assert "shared by 3 faces" in issue.description


def test_health_tiny_edges_and_slivers_assisted():
    """Verify sub-scale micro-features produce WARNINGS and transition to ASSISTED."""
    # Model diagonal = sqrt(100^2 + 100^2 + 100^2) ≈ 173.2 mm
    # tiny_edge_threshold = 173.2 * 1e-3 = 0.173 mm
    model = GeometryModel(
        model_id="M_MICRO_FEATURES",
        provenance=_make_dummy_provenance(),
        unit=CadUnit.MM,
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        solids=(CadSolid(id="S1"),),
        faces=(CadFace(id="F_SLIVER", area=0.01),),  # 0.01 << 173.2^2 * 1e-5 = 0.3
        edges=(CadEdge(id="E_TINY", length=0.05),),  # 0.05 < 0.173
    )

    report = inspect_geometry_health(model, analysis_intent="solid")
    assert report.status == CapabilityStatus.ASSISTED
    assert report.is_acceptable_for_analysis is True
    assert any(i.kind == HealthIssueKind.TINY_EDGE for i in report.issues)
    assert any(i.kind == HealthIssueKind.SLIVER_FACE for i in report.issues)


def test_health_analysis_intent_compatibility():
    """Verify 'open shell = defect' is not absolute; depends on analysis intent.

    - Under solid mechanics intent: an open sheet shell cannot form a solid volume -> BLOCKED.
    - Under shell mechanics intent: an open sheet shell is intentional and legitimate -> SUPPORTED.
    """
    sheet_model = GeometryModel(
        model_id="M_CURVED_PANEL",
        provenance=_make_dummy_provenance(),
        unit=CadUnit.MM,
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 500.0, 500.0, 2.0),
        shells=(CadShell(id="SH_OPEN", is_closed=False),),
        faces=(CadFace(id="F_SHEET", area=250000.0),),
    )

    # 1. In solid intent, cannot mesh 3D continuum elements
    solid_report = inspect_geometry_health(sheet_model, analysis_intent="solid")
    assert solid_report.status == CapabilityStatus.BLOCKED
    assert solid_report.is_acceptable_for_analysis is False
    assert any(i.kind == HealthIssueKind.UNCLOSED_SHELL_IN_SOLID for i in solid_report.issues)

    # 2. In shell intent, perfectly valid 2D/3D shell structural model
    shell_report = inspect_geometry_health(sheet_model, analysis_intent="shell")
    assert shell_report.status == CapabilityStatus.SUPPORTED
    assert shell_report.is_acceptable_for_analysis is True
    assert shell_report.error_count == 0


def test_health_empty_geometry_blocked():
    """Verify empty CAD model halts cleanly as BLOCKED."""
    empty_model = GeometryModel(
        model_id="M_EMPTY",
        provenance=_make_dummy_provenance(),
    )
    report = inspect_geometry_health(empty_model)
    assert report.status == CapabilityStatus.BLOCKED
    assert report.is_acceptable_for_analysis is False


def test_health_report_serialization():
    """Verify report serialization contract matches audit expectations."""
    model = GeometryModel(
        model_id="M_SERIALIZE",
        provenance=_make_dummy_provenance(),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
        edges=(CadEdge(id="E1", length=10.0),),
    )
    report = inspect_geometry_health(model, analysis_intent="shell")
    d = report.to_dict()
    assert d["model_id"] == "M_SERIALIZE"
    assert d["status"] == "supported"
    assert d["analysis_intent"] == "shell"
    assert "counts" in d
