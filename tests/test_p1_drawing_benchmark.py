"""P1.1 Engineering Drawing Benchmark & Real Machine Qualification Tests.

Verifies:
1. Tier 1 Vector PDF ingestion, perception pipeline, and precision/recall evaluation.
2. Tier 2 Scanned PDF & Tier 3 CAD Screenshot ground truth contracts.
3. Offline regression verification of the authentic Abaqus 2025 Drawing Golden Manifest.
4. Fail-closed perception benchmark evaluator negative probes.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from abaqus_ai_agent.contracts.drawing_benchmark import DrawingGroundTruth
from abaqus_ai_agent.perception.benchmark_evaluator import evaluate_drawing_perception
from abaqus_ai_agent.perception.ingestion import DocumentIngestionPipeline
from abaqus_ai_agent.perception.perception_pipeline import PerceptionPipeline, PerceptionResult
from abaqus_ai_agent.perception.provider import DrawingVisionProvider

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "test_assets" / "drawings"
MANIFEST_PATH = ROOT / "machine_validation" / "p1_drawing_golden_manifest.json"


@pytest.fixture(scope="module")
def golden_manifest():
    assert MANIFEST_PATH.exists(), f"Drawing Golden Manifest not found at {MANIFEST_PATH}"
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data


# =========================================================================
# Tier 1, 2, 3 Benchmark Assets & Ingestion Verification
# =========================================================================

def test_tier1_vector_pdf_perception_and_qualification():
    """Verify that Tier 1 vector PDF is processed with 100% precision & recall."""
    pdf_path = ASSETS / "tier1_vector_pdf" / "l_bracket_blueprint.pdf"
    gt_path = ASSETS / "tier1_vector_pdf" / "l_bracket_ground_truth.json"

    assert pdf_path.exists()
    assert gt_path.exists()

    ground_truth = DrawingGroundTruth.load_json(gt_path)
    assert ground_truth.drawing_id == "L_BRACKET_TIER1_VECTOR_PDF"
    assert len(ground_truth.dimensions) == 4
    assert len(ground_truth.boundary_conditions) == 1
    assert len(ground_truth.loads) == 1

    ingestion = DocumentIngestionPipeline()
    pages = ingestion.load_document(pdf_path)
    assert len(pages) == 1
    assert pages[0].is_vector is True

    provider = DrawingVisionProvider()
    pipeline = PerceptionPipeline(provider=provider, ingestion_pipeline=ingestion)
    result = pipeline.process_page(pages[0])

    assert result.valid_callout_count >= 6
    assert result.confidence.overall_confidence > 0.9

    report = evaluate_drawing_perception(result, ground_truth)
    assert report.is_qualified is True
    assert report.overall_f1 == pytest.approx(1.0, abs=1e-4)
    assert report.dimension_metrics.f1_score == pytest.approx(1.0, abs=1e-4)
    assert report.boundary_metrics.f1_score == pytest.approx(1.0, abs=1e-4)
    assert report.load_metrics.f1_score == pytest.approx(1.0, abs=1e-4)


def test_tier2_and_tier3_ground_truth_contracts():
    """Verify contracts and consistency of Tier 2 and Tier 3 benchmark assets."""
    tier2_gt = DrawingGroundTruth.load_json(ASSETS / "tier2_scan_pdf" / "l_bracket_ground_truth.json")
    tier3_gt = DrawingGroundTruth.load_json(ASSETS / "tier3_screenshot" / "l_bracket_ground_truth.json")

    assert tier2_gt.drawing_id == "L_BRACKET_TIER2_SCAN_PDF"
    assert tier3_gt.drawing_id == "L_BRACKET_TIER3_SCREENSHOT"

    for gt in (tier2_gt, tier3_gt):
        assert gt.material.material_name == "Q235"
        assert gt.material.elastic_modulus == 210000.0
        assert gt.material.poisson_ratio == 0.3
        assert len(gt.dimensions) == 4
        assert len(gt.boundary_conditions) == 1
        assert len(gt.loads) == 1
        assert gt.loads[0].magnitude == 1000.0
        assert gt.loads[0].direction_vector == (0.0, -1.0)


# =========================================================================
# Authentic Abaqus 2025 Real Machine Golden Manifest Checks (CI Compatible)
# =========================================================================

def test_p1_drawing_golden_manifest_execution_metadata(golden_manifest):
    """Verify solver execution metadata in the authentic machine manifest."""
    assert golden_manifest["benchmark_id"] == "L_BRACKET_TIER1_VECTOR_PDF"
    assert golden_manifest["solver"] == "Abaqus 2025 (Live Execution)"
    assert golden_manifest["run_id"] == "run_p1_drawing_lbracket_live_2025"

    metrics = golden_manifest["perception_metrics"]
    assert metrics["is_qualified"] is True
    assert metrics["overall_f1"] == 1.0


def test_p1_drawing_golden_manifest_physics_and_equilibrium(golden_manifest):
    """Verify authentic physical equilibrium and stresses recorded from live Abaqus ODB."""
    sim = golden_manifest["simulation_results"]
    assert sim["applied_load_n"] == 1000.0
    assert sim["acceptance"] == "ACCEPTED"

    # Strict reaction equilibrium: |RF_y| == Applied Load within 0.001%
    assert sim["equilibrium_error_percent"] <= 0.001
    assert abs(sim["total_reaction_rf_y_n"] - 1000.0) < 0.1

    # Max Mises Stress within structural limits [5, 150] MPa
    assert 5.0 <= sim["max_mises_mpa"] <= 150.0

    # Deflection magnitude is non-trivial and positive
    assert sim["max_deflection_mm"] > 0.0


def test_p1_drawing_golden_manifest_artifacts_and_probes(golden_manifest):
    """Verify the 6 mandatory solver artifacts and probe results in the manifest."""
    artifacts = golden_manifest["artifacts"]
    required_exts = (".inp", ".odb", ".sta", ".msg", ".dat", ".log")
    for ext in required_exts:
        matching = [name for name in artifacts if name.endswith(ext)]
        assert len(matching) == 1, f"Missing or duplicate artifact for extension {ext}"
        info = artifacts[matching[0]]
        assert info["exists"] is True
        assert len(info["sha256"]) == 64
        assert info["size_bytes"] > 0

    probes = golden_manifest["probes"]
    assert probes["probe_1_unconfirmed_hitl_block"] == "PASS"
    assert probes["probe_2_evidence_tampering_block"] == "PASS"


# =========================================================================
# Perception Benchmark Evaluator Negative Probes
# =========================================================================

def test_benchmark_evaluator_unqualified_when_dimensions_missed():
    """Evaluator must disqualify when dimensions fail precision/recall thresholds."""
    from abaqus_ai_agent.perception.contracts import ObservationProvenance, PerceptionConfidence

    gt_path = ASSETS / "tier1_vector_pdf" / "l_bracket_ground_truth.json"
    ground_truth = DrawingGroundTruth.load_json(gt_path)

    # Empty perception result
    prov = ObservationProvenance(source_path="test.pdf", page_index=0, extraction_method="test")
    conf = PerceptionConfidence(text_confidence=0.0, symbol_confidence=0.0)
    empty_result = PerceptionResult(
        source_path="test.pdf",
        page_index=0,
        callouts=(),
        rejected_observations=(),
        confidence=conf,
        provenance=prov,
    )
    report = evaluate_drawing_perception(empty_result, ground_truth)

    assert report.is_qualified is False
    assert report.overall_f1 == 0.0
    assert report.dimension_metrics.f1_score == 0.0
    assert report.boundary_metrics.f1_score == 0.0
    assert report.load_metrics.f1_score == 0.0
    assert len(report.missing_truth_ids) > 0
