"""Unit and integration tests for GA-2.2 Feature / Physical Grounding Layer.

Validates deterministic semantic-to-geometry mapping without handwritten CAD fixtures:
- plate_with_hole.step autonomous pipeline -> INSTALLATION_HOLE & TOP_SURFACE.
- Zero-match fail-closed rejection (NOT_FOUND -> GroundingResolutionError).
- Multi-match ambiguity fail-closed gate (AMBIGUOUS -> GroundingAmbiguityError).
- Competing top faces ambiguity gate.
- Unsupported semantic targets fail-closed gate.
"""

from pathlib import Path
import pytest

from abaqus_ai_agent.geometry.cad_ingestion import ingest_cad_file
from abaqus_ai_agent.geometry.topology import normalize_topology
from abaqus_ai_agent.geometry.features import detect_features, FeatureCandidate, FeatureType
from abaqus_ai_agent.geometry.model import (
    GeometryModel,
    CadFace,
    CadEdge,
    CadVertex,
    CadBoundingBox,
    CadProvenance,
    CadFormat,
    CadUnit,
)
from abaqus_ai_agent.grounding.feature_grounding import (
    GroundedRegion,
    GroundingResolutionError,
    GroundingAmbiguityError,
    resolve_feature_grounding,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "step"


def _make_dummy_provenance(name: str = "dummy.step") -> CadProvenance:
    return CadProvenance(
        file_path=f"/dummy/{name}",
        file_name=name,
        file_sha256="0" * 64,
        file_size_bytes=1024,
        ingested_at="2026-10-03T00:00:00Z",
        cad_format=CadFormat.STEP,
        cad_schema="AP214",
    )


@pytest.fixture(scope="module")
def plate_model_and_features():
    """Ingest real STEP file and run full feature detection chain."""
    step_file = FIXTURES_DIR / "plate_with_hole.step"
    assert step_file.exists(), f"Missing fixture {step_file}"
    model = ingest_cad_file(str(step_file))
    topology = normalize_topology(model)
    features = detect_features(model, topology)
    return model, topology, features


def test_ground_installation_hole_on_real_step(plate_model_and_features):
    """Test grounding INSTALLATION_HOLE against real plate_with_hole.step without mocks."""
    model, topology, features = plate_model_and_features

    region = resolve_feature_grounding(
        target_semantic="INSTALLATION_HOLE",
        model=model,
        topology=topology,
        feature_candidates=features,
        strict=True,
    )

    assert isinstance(region, GroundedRegion)
    assert region.status == "RESOLVED"
    assert region.entity_type == "Face"
    assert region.entity_ids == ("F_277",)  # Cylindrical barrel face
    assert region.feature_id == "FEAT_FASTENER_HOLE_F_277"
    assert region.confidence >= 0.90

    # Anchor point must be on the cylinder surface (radius 10 from center (50, 50))
    x, y, z = region.anchor_point
    assert 0.0 <= z <= 20.0
    dist_to_axis = ((x - 50.0) ** 2 + (y - 50.0) ** 2) ** 0.5
    assert abs(dist_to_axis - 10.0) < 1e-3
    assert len(region.evidence) > 0


def test_ground_top_surface_on_real_step(plate_model_and_features):
    """Test grounding TOP_SURFACE on real plate_with_hole.step avoiding inner loop void."""
    model, topology, features = plate_model_and_features

    region = resolve_feature_grounding(
        target_semantic="TOP_SURFACE",
        model=model,
        topology=topology,
        feature_candidates=features,
        strict=True,
    )

    assert isinstance(region, GroundedRegion)
    assert region.status == "RESOLVED"
    assert region.entity_type == "Face"
    assert region.entity_ids == ("F_271",)  # Top planar face with normal (0, 0, 1)
    assert region.confidence == 1.0

    # Anchor point must be at Z = 20.0
    x, y, z = region.anchor_point
    assert abs(z - 20.0) < 1e-3
    # Anchor point must NOT be inside the hole (r = 10 at (50, 50))
    dist_to_hole = ((x - 50.0) ** 2 + (y - 50.0) ** 2) ** 0.5
    assert dist_to_hole > 10.0
    assert len(region.evidence) > 0


def test_ground_installation_hole_zero_candidates_fail_closed(plate_model_and_features):
    """Verify that zero hole candidate raises GroundingResolutionError in strict mode."""
    model, topology, _ = plate_model_and_features

    # Pass empty feature candidate list (simulating un-holed body)
    with pytest.raises(GroundingResolutionError) as exc_info:
        resolve_feature_grounding(
            target_semantic="INSTALLATION_HOLE",
            model=model,
            topology=topology,
            feature_candidates=(),
            strict=True,
        )
    assert "NO_FASTENER_HOLE_DETECTED" in str(exc_info.value)

    # In non-strict mode, verify NOT_FOUND status is cleanly returned
    region = resolve_feature_grounding(
        target_semantic="INSTALLATION_HOLE",
        model=model,
        topology=topology,
        feature_candidates=(),
        strict=False,
    )
    assert region.status == "NOT_FOUND"
    assert region.confidence == 0.0


def test_ground_installation_hole_multiple_candidates_ambiguity_gate(plate_model_and_features):
    """Verify that multiple conflicting holes raise GroundingAmbiguityError in strict mode."""
    model, topology, features = plate_model_and_features

    # Create synthetic multi-hole candidate tuple
    hole1 = [f for f in features if f.feature_type == FeatureType.FASTENER_HOLE][0]
    hole2 = FeatureCandidate(
        feature_id="FEAT_FASTENER_HOLE_2",
        feature_type=FeatureType.FASTENER_HOLE,
        face_ids=("F_999",),
        geometry={"diameter": 20.0, "sub_type": "THROUGH"},
        confidence=0.95,
        status="ASSISTED",
    )

    with pytest.raises(GroundingAmbiguityError) as exc_info:
        resolve_feature_grounding(
            target_semantic="INSTALLATION_HOLE",
            model=model,
            topology=topology,
            feature_candidates=(hole1, hole2),
            strict=True,
        )
    assert "MULTIPLE_HOLES_FOUND" in str(exc_info.value)

    # In non-strict mode, returns AMBIGUOUS
    reg = resolve_feature_grounding(
        target_semantic="INSTALLATION_HOLE",
        model=model,
        topology=topology,
        feature_candidates=(hole1, hole2),
        strict=False,
    )
    assert reg.status == "AMBIGUOUS"
    assert len(reg.entity_ids) == 2


def test_ground_top_surface_competing_faces_ambiguity_gate():
    """Verify that multiple competing coplanar top faces without dominant area trigger AMBIGUOUS."""
    v1 = CadVertex("V1", (0.0, 0.0, 50.0))
    v2 = CadVertex("V2", (10.0, 0.0, 50.0))
    v3 = CadVertex("V3", (10.0, 10.0, 50.0))
    v4 = CadVertex("V4", (0.0, 10.0, 50.0))
    e1 = CadEdge("E1", "LINE", "V1", "V2", 10.0)
    e2 = CadEdge("E2", "LINE", "V2", "V3", 10.0)
    e3 = CadEdge("E3", "LINE", "V3", "V4", 10.0)
    e4 = CadEdge("E4", "LINE", "V4", "V1", 10.0)

    # Two identical top faces side by side at Z=50
    f1 = CadFace(
        id="F_TOP_1",
        surface_type="PLANE",
        is_planar=True,
        normal=(0.0, 0.0, 1.0),
        edge_ids=("E1", "E2", "E3", "E4"),
        area=100.0,
    )
    f2 = CadFace(
        id="F_TOP_2",
        surface_type="PLANE",
        is_planar=True,
        normal=(0.0, 0.0, 1.0),
        edge_ids=("E1", "E2", "E3", "E4"),
        area=100.0,
    )

    prov = _make_dummy_provenance("competing.step")
    bbox = CadBoundingBox(0.0, 0.0, 0.0, 20.0, 20.0, 50.0)
    model = GeometryModel(
        model_id="MODEL_COMPETING",
        provenance=prov,
        unit=CadUnit.MM,
        solids=(),
        shells=(),
        faces=(f1, f2),
        edges=(e1, e2, e3, e4),
        vertices=(v1, v2, v3, v4),
        bounding_box=bbox,
    )

    with pytest.raises(GroundingAmbiguityError) as exc_info:
        resolve_feature_grounding("TOP_SURFACE", model, strict=True)
    assert "MULTIPLE_TOP_FACES" in str(exc_info.value)


def test_ground_unsupported_semantic_target(plate_model_and_features):
    """Verify that unhandled semantic targets fail closed with GroundingResolutionError."""
    model, topology, features = plate_model_and_features

    with pytest.raises(GroundingResolutionError) as exc_info:
        resolve_feature_grounding(
            target_semantic="SIDE_BEARING_BRACKET",
            model=model,
            topology=topology,
            feature_candidates=features,
            strict=True,
        )
    assert "UNSUPPORTED_SEMANTIC_TARGET" in str(exc_info.value)
