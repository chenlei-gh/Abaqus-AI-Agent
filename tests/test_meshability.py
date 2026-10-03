"""Unit tests for Track GA-1.4: Pre-meshing Meshability Assessment & Mesh Gate Reuse."""

import pytest
from typing import Dict, List, Tuple

from abaqus_ai_agent.capability_boundary import CapabilityStatus
from abaqus_ai_agent.contracts.mesh_strategy import GeometryMeshPlan
from abaqus_ai_agent.geometry.features import (
    FeatureCandidate,
    FeatureEvidence,
    FeatureType,
    HoleSubType,
)
from abaqus_ai_agent.geometry.health import (
    GeometryHealthIssue,
    GeometryHealthReport,
    HealthIssueKind,
    HealthSeverity,
    inspect_geometry_health,
)
from abaqus_ai_agent.geometry.meshability import (
    MeshabilityResult,
    MeshabilityRisk,
    MeshabilityRiskKind,
    MeshabilitySeverity,
    MeshRefinementCandidate,
    RecommendedMeshStrategy,
    assess_meshability,
)
from abaqus_ai_agent.geometry.model import (
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
)
from abaqus_ai_agent.geometry.topology import normalize_topology


def _make_dummy_provenance(name: str = "test.step") -> CadProvenance:
    return CadProvenance(
        file_path=f"/dummy/{name}",
        file_name=name,
        file_sha256="0" * 64,
        file_size_bytes=1024,
        ingested_at="2026-10-03T00:00:00Z",
        cad_format=CadFormat.STEP,
        cad_schema="AP214",
    )


def _make_clean_solid_block_model() -> GeometryModel:
    """Build a clean 10x10x10 cube with 6 planar faces, 12 edges, 8 vertices."""
    vertices = (
        CadVertex("V1", (0.0, 0.0, 0.0)),
        CadVertex("V2", (10.0, 0.0, 0.0)),
        CadVertex("V3", (10.0, 10.0, 0.0)),
        CadVertex("V4", (0.0, 10.0, 0.0)),
        CadVertex("V5", (0.0, 0.0, 10.0)),
        CadVertex("V6", (10.0, 0.0, 10.0)),
        CadVertex("V7", (10.0, 10.0, 10.0)),
        CadVertex("V8", (0.0, 10.0, 10.0)),
    )
    edges = (
        CadEdge("E1", "LINE", "V1", "V2", length=10.0),
        CadEdge("E2", "LINE", "V2", "V3", length=10.0),
        CadEdge("E3", "LINE", "V3", "V4", length=10.0),
        CadEdge("E4", "LINE", "V4", "V1", length=10.0),
        CadEdge("E5", "LINE", "V5", "V6", length=10.0),
        CadEdge("E6", "LINE", "V6", "V7", length=10.0),
        CadEdge("E7", "LINE", "V7", "V8", length=10.0),
        CadEdge("E8", "LINE", "V8", "V5", length=10.0),
        CadEdge("E9", "LINE", "V1", "V5", length=10.0),
        CadEdge("E10", "LINE", "V2", "V6", length=10.0),
        CadEdge("E11", "LINE", "V3", "V7", length=10.0),
        CadEdge("E12", "LINE", "V4", "V8", length=10.0),
    )
    faces = (
        CadFace("F_BOT", "PLANE", ("E1", "E2", "E3", "E4"), area=100.0, normal=(0.0, 0.0, -1.0), is_planar=True),
        CadFace("F_TOP", "PLANE", ("E5", "E6", "E7", "E8"), area=100.0, normal=(0.0, 0.0, 1.0), is_planar=True),
        CadFace("F_FRONT", "PLANE", ("E1", "E10", "E5", "E9"), area=100.0, normal=(0.0, -1.0, 0.0), is_planar=True),
        CadFace("F_RIGHT", "PLANE", ("E2", "E11", "E6", "E10"), area=100.0, normal=(1.0, 0.0, 0.0), is_planar=True),
        CadFace("F_BACK", "PLANE", ("E3", "E12", "E7", "E11"), area=100.0, normal=(0.0, 1.0, 0.0), is_planar=True),
        CadFace("F_LEFT", "PLANE", ("E4", "E9", "E8", "E12"), area=100.0, normal=(-1.0, 0.0, 0.0), is_planar=True),
    )
    shell = CadShell("S1", tuple(f.id for f in faces), is_closed=True)
    solid = CadSolid("SOL1", ("S1",), volume=1000.0)
    bbox = CadBoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0)

    return GeometryModel(
        model_id="clean_block",
        provenance=_make_dummy_provenance("cube.step"),
        unit=CadUnit.MM,
        solids=(solid,),
        shells=(shell,),
        faces=faces,
        edges=edges,
        vertices=vertices,
        bounding_box=bbox,
    )


def test_meshability_clean_solid_block():
    """Verify clean manifold block passes meshability without risks and yields valid plan."""
    model = _make_clean_solid_block_model()
    result = assess_meshability(model, target_mesh_size=2.0)

    assert result.is_meshable is True
    assert result.status == CapabilityStatus.SUPPORTED
    assert result.recommended_strategy == RecommendedMeshStrategy.UNDECIDED
    assert len(result.risks) == 0
    assert result.characteristic_length == pytest.approx(17.3205, rel=1e-3)
    assert len(result.limitations) >= 4

    # Bridge to GeometryMeshPlan
    plan = result.to_geometry_mesh_plan()
    assert isinstance(plan, GeometryMeshPlan)
    assert plan.global_size == 2.0
    assert len(plan.warnings) == 0
    assert plan.requires_partition is False


def test_meshability_with_fastener_hole_heuristic_size():
    """Verify hole feature produces suggested refinement size ~ 0.25D without Kt assumptions."""
    model = _make_clean_solid_block_model()

    hole_feature = FeatureCandidate(
        feature_id="FEAT_HOLE_1",
        feature_type=FeatureType.FASTENER_HOLE,
        status=CapabilityStatus.SUPPORTED,
        confidence=0.92,
        face_ids=("F_TOP",),
        edge_ids=("E5",),
        geometry={"diameter": 4.0, "depth": 10.0, "hole_type": "THROUGH"},
        evidence=(
            FeatureEvidence("CYLINDER_DETECTION", ("F_TOP",), "radius_detected", 2.0, "r>0"),
        ),
    )

    result = assess_meshability(model, features=(hole_feature,), target_mesh_size=1.0)
    assert result.is_meshable is True
    assert len(result.refinement_candidates) == 1

    cand = result.refinement_candidates[0]
    assert cand.feature_type == FeatureType.FASTENER_HOLE
    assert cand.characteristic_name == "diameter"
    assert cand.characteristic_value == 4.0
    assert cand.suggested_size == pytest.approx(1.0)  # 4.0 * 0.25
    assert cand.priority == "high"
    # Ensure no Kt formulation in reason
    assert "Kt" not in cand.reason and "K_t" not in cand.reason
    assert "Circumferential curvature resolution" in cand.reason

    # Plan bridge
    plan = result.to_geometry_mesh_plan()
    assert len(plan.refinements) == 1
    assert plan.refinements[0].target_size == pytest.approx(1.0)
    assert plan.refinements[0].requires_partition is False


def test_meshability_scale_conflict_element_swallowing_is_warning_not_blocked():
    """Verify target_mesh_size > 2x min_edge triggers warning risk, not hard blocking."""
    model = _make_clean_solid_block_model()
    # Cube edges are 10.0. If target_mesh_size is 25.0 (> 2 * 10.0), trigger conflict warning
    result = assess_meshability(model, target_mesh_size=25.0)

    assert result.is_meshable is True
    assert result.status == CapabilityStatus.ASSISTED
    assert result.has_scale_conflicts is True

    conflict_risks = [r for r in result.risks if r.kind == MeshabilityRiskKind.SCALE_CONFLICT_ELEMENT_SWALLOWING]
    assert len(conflict_risks) == 1
    assert conflict_risks[0].severity == MeshabilitySeverity.WARNING
    assert "geometrically swallowed or distorted" in conflict_risks[0].description


def test_meshability_unproven_hole_dimension_falls_back_to_review():
    """Verify hole with unproven diameter outputs suggested_size=None and converts to review in plan."""
    model = _make_clean_solid_block_model()

    hole_feature = FeatureCandidate(
        feature_id="FEAT_HOLE_UNPROVEN",
        feature_type=FeatureType.FASTENER_HOLE,
        status=CapabilityStatus.ASSISTED,
        confidence=0.60,
        face_ids=("F_TOP",),
        geometry={"hole_type": "UNKNOWN"},  # diameter is None
    )

    result = assess_meshability(model, features=(hole_feature,), target_mesh_size=2.0)
    assert len(result.refinement_candidates) == 1
    cand = result.refinement_candidates[0]
    assert cand.suggested_size is None
    assert cand.characteristic_value is None

    plan = result.to_geometry_mesh_plan()
    assert len(plan.refinements) == 0
    assert len(plan.feature_reviews) == 1
    assert "review_unproven_scale" in plan.feature_reviews[0].reason


def test_meshability_with_fillet_and_chamfer():
    """Verify fillet and chamfer refinement candidates obey evidenced dimensions."""
    model = _make_clean_solid_block_model()

    fillet_with_rad = FeatureCandidate(
        feature_id="FEAT_FILLET_1",
        feature_type=FeatureType.FILLET,
        status=CapabilityStatus.ASSISTED,
        confidence=0.85,
        face_ids=("F_FRONT",),
        geometry={"radius": 2.0, "is_constant_radius": True},
    )
    fillet_no_rad = FeatureCandidate(
        feature_id="FEAT_FILLET_2",
        feature_type=FeatureType.FILLET,
        status=CapabilityStatus.ASSISTED,
        confidence=0.70,
        face_ids=("F_RIGHT",),
        geometry={"radius": None},
    )
    chamfer_with_width = FeatureCandidate(
        feature_id="FEAT_CHAMFER_1",
        feature_type=FeatureType.CHAMFER,
        status=CapabilityStatus.ASSISTED,
        confidence=0.88,
        face_ids=("F_BACK",),
        geometry={"chamfer_width": 1.5},
    )

    result = assess_meshability(
        model,
        features=(fillet_with_rad, fillet_no_rad, chamfer_with_width),
        target_mesh_size=2.0,
    )

    cands = {c.target_id: c for c in result.refinement_candidates}
    # Fillet 1: radius=2.0 -> suggested_size=1.0
    assert cands["F_FRONT"].suggested_size == pytest.approx(1.0)
    # Fillet 2: radius=None -> suggested_size=None
    assert cands["F_RIGHT"].suggested_size is None
    # Chamfer 1: width=1.5 -> suggested_size=0.75
    assert cands["F_BACK"].suggested_size == pytest.approx(0.75)


def test_meshability_with_rib_no_partition_mandate():
    """Verify rib provides thickness hint but strictly avoids partition mandates in GA-1.4."""
    model = _make_clean_solid_block_model()

    rib_feature = FeatureCandidate(
        feature_id="FEAT_RIB_1",
        feature_type=FeatureType.RIB,
        status=CapabilityStatus.ASSISTED,
        confidence=0.82,
        face_ids=("F_LEFT",),
        geometry={"thickness": 1.2, "slenderness_ratio": 4.0},
    )

    result = assess_meshability(model, features=(rib_feature,))
    assert len(result.refinement_candidates) == 1
    cand = result.refinement_candidates[0]
    assert cand.suggested_size == pytest.approx(0.6)  # 1.2 * 0.5

    plan = result.to_geometry_mesh_plan(global_size=2.0)
    assert len(plan.refinements) == 1
    # User adjudication: requires_partition MUST be False
    assert plan.refinements[0].requires_partition is False
    assert plan.requires_partition is False


def test_meshability_with_contact_plane_hint_only():
    """Verify contact plane only provides potential contact region review hint, not contact pair."""
    model = _make_clean_solid_block_model()

    contact_feature = FeatureCandidate(
        feature_id="FEAT_CONTACT_1",
        feature_type=FeatureType.CONTACT_PLANE,
        status=CapabilityStatus.ASSISTED,
        confidence=0.80,
        face_ids=("F_BOT",),
        geometry={"area": 100.0, "normal": [0.0, 0.0, -1.0], "has_inner_hole": False},
    )

    result = assess_meshability(model, features=(contact_feature,))
    assert len(result.refinement_candidates) == 1
    cand = result.refinement_candidates[0]
    assert cand.feature_type == FeatureType.CONTACT_PLANE
    assert cand.suggested_size is None  # Left to assembly contact discretization
    assert "Potential planar contact/bearing surface" in cand.reason


def test_meshability_tiny_edge_and_sliver_face_risks():
    """Verify sub-scale edges and micro-sliver faces generate warning risks."""
    # Build model with an edge < 0.005 char_len
    model = _make_clean_solid_block_model()
    # Replace E1 with length 0.01 (char_len ~ 17.32, 0.005 * 17.32 ~ 0.086)
    tiny_edge = CadEdge("E_TINY", "LINE", "V1", "V2", length=0.01)
    sliver_face = CadFace("F_SLIVER", "PLANE", ("E_TINY",), area=0.001, is_planar=True)

    new_model = GeometryModel(
        model_id="tiny_feature_model",
        provenance=model.provenance,
        unit=model.unit,
        solids=model.solids,
        shells=model.shells,
        faces=model.faces + (sliver_face,),
        edges=model.edges + (tiny_edge,),
        vertices=model.vertices,
        bounding_box=model.bounding_box,
    )

    result = assess_meshability(new_model)
    assert result.status == CapabilityStatus.ASSISTED
    risk_kinds = [r.kind for r in result.risks]
    assert MeshabilityRiskKind.TINY_FEATURE_DEFORMATION in risk_kinds
    assert MeshabilityRiskKind.SLIVER_FACE_DISTORTION in risk_kinds


def test_meshability_defective_non_manifold_fails_closed():
    """Verify non-manifold geometry is blocked fail-closed and cannot produce plan."""
    # An edge shared by 3 faces
    e1 = CadEdge("E1", "LINE", "V1", "V2", length=10.0)
    f1 = CadFace("F1", "PLANE", ("E1",), area=10.0)
    f2 = CadFace("F2", "PLANE", ("E1",), area=10.0)
    f3 = CadFace("F3", "PLANE", ("E1",), area=10.0)

    model = GeometryModel(
        model_id="non_manifold_model",
        provenance=_make_dummy_provenance("nm.step"),
        faces=(f1, f2, f3),
        edges=(e1,),
        vertices=(CadVertex("V1", (0.0, 0.0, 0.0)), CadVertex("V2", (10.0, 0.0, 0.0))),
        bounding_box=CadBoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
    )

    result = assess_meshability(model)
    assert result.is_meshable is False
    assert result.status == CapabilityStatus.BLOCKED
    assert result.recommended_strategy == RecommendedMeshStrategy.BLOCKED
    assert result.has_critical_risks is True

    # Fail-closed enforcement on to_geometry_mesh_plan
    with pytest.raises(ValueError, match="Cannot create GeometryMeshPlan for unmeshable/blocked model"):
        result.to_geometry_mesh_plan()


def test_meshability_auto_resolves_topology_health_features():
    """Verify assess_meshability can be called with only model and resolves downstream layers."""
    model = _make_clean_solid_block_model()
    result = assess_meshability(model)

    assert result.model_id == "clean_block"
    assert result.is_meshable is True
    assert result.status == CapabilityStatus.SUPPORTED
    assert result.characteristic_length > 0
    assert "model:clean_block" in result.evidence
    # Ensure serializable to dict
    d = result.to_dict()
    assert d["model_id"] == "clean_block"
    assert d["is_meshable"] is True
    assert isinstance(d["limitations"], list)
