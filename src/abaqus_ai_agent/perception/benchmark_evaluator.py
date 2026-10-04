"""Evaluation metrics and benchmark runner for engineering drawing perception.

Calculates:
- Precision, Recall, F1 for Dimensions, Boundary Conditions, and Loads.
- Strict metric validation against DrawingGroundTruth contracts.
- Provenance and error reporting for engineering auditing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts.drawing_benchmark import (
    DrawingBoundaryTruth,
    DrawingDimensionTruth,
    DrawingGroundTruth,
    DrawingLoadTruth,
)
from .perception_pipeline import PerceptionResult


@dataclass(frozen=True)
class BenchmarkMetricSummary:
    """Precision and recall summary for an individual semantic category."""
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float


@dataclass(frozen=True)
class DrawingBenchmarkEvaluation:
    """Complete evaluation report comparing perception results against ground truth."""
    drawing_id: str
    tier: str
    dimension_metrics: BenchmarkMetricSummary
    boundary_metrics: BenchmarkMetricSummary
    load_metrics: BenchmarkMetricSummary
    overall_f1: float
    is_qualified: bool
    matched_callout_ids: Tuple[str, ...]
    unmatched_callout_ids: Tuple[str, ...]
    missing_truth_ids: Tuple[str, ...]
    details: Dict[str, Any] = field(default_factory=dict)


def evaluate_drawing_perception(
    perception_result: PerceptionResult,
    ground_truth: DrawingGroundTruth,
    tolerance_ratio: float = 0.05,
) -> DrawingBenchmarkEvaluation:
    """Evaluates perception extraction accuracy against canonical ground truth."""
    # 1. Evaluate Dimensions
    dim_callouts = [c for c in perception_result.callouts if c.callout_type == "DIMENSION"]
    matched_dims: List[str] = []
    unmatched_dims: List[str] = []
    matched_truth_dims: set[str] = set()

    for c in dim_callouts:
        c_mag = c.magnitude
        c_unit = (c.unit or "").lower()
        matched = False
        for gt_d in ground_truth.dimensions:
            if gt_d.dimension_id in matched_truth_dims:
                continue
            # Compare nominal value and unit
            gt_unit = gt_d.unit.lower()
            if c_mag is not None and abs(c_mag - gt_d.nominal_value) <= max(0.01, gt_d.nominal_value * tolerance_ratio):
                if not c_unit or c_unit == gt_unit:
                    matched = True
                    matched_truth_dims.add(gt_d.dimension_id)
                    matched_dims.append(c.callout_id)
                    break
        if not matched:
            unmatched_dims.append(c.callout_id)

    tp_dim = len(matched_truth_dims)
    fp_dim = len(unmatched_dims)
    fn_dim = len(ground_truth.dimensions) - tp_dim
    prec_dim = tp_dim / (tp_dim + fp_dim) if (tp_dim + fp_dim) > 0 else 1.0
    rec_dim = tp_dim / (tp_dim + fn_dim) if (tp_dim + fn_dim) > 0 else 1.0
    f1_dim = (2 * prec_dim * rec_dim / (prec_dim + rec_dim)) if (prec_dim + rec_dim) > 0 else 0.0

    dim_metrics = BenchmarkMetricSummary(
        true_positives=tp_dim,
        false_positives=fp_dim,
        false_negatives=fn_dim,
        precision=prec_dim,
        recall=rec_dim,
        f1_score=f1_dim,
    )

    # 2. Evaluate Boundaries
    bc_callouts = [
        c for c in perception_result.callouts
        if c.semantic_intent in ("FIXED_SUPPORT", "PINNED_SUPPORT", "ROLLER_SUPPORT", "SYMMETRY_PLANE")
    ]
    matched_bcs: List[str] = []
    unmatched_bcs: List[str] = []
    matched_truth_bcs: set[str] = set()

    for c in bc_callouts:
        matched = False
        for gt_b in ground_truth.boundary_conditions:
            if gt_b.boundary_id in matched_truth_bcs:
                continue
            if c.semantic_intent == gt_b.bc_type:
                matched = True
                matched_truth_bcs.add(gt_b.boundary_id)
                matched_bcs.append(c.callout_id)
                break
        if not matched:
            unmatched_bcs.append(c.callout_id)

    tp_bc = len(matched_truth_bcs)
    fp_bc = len(unmatched_bcs)
    fn_bc = len(ground_truth.boundary_conditions) - tp_bc
    prec_bc = tp_bc / (tp_bc + fp_bc) if (tp_bc + fp_bc) > 0 else 1.0
    rec_bc = tp_bc / (tp_bc + fn_bc) if (tp_bc + fn_bc) > 0 else 1.0
    f1_bc = (2 * prec_bc * rec_bc / (prec_bc + rec_bc)) if (prec_bc + rec_bc) > 0 else 0.0

    bc_metrics = BenchmarkMetricSummary(
        true_positives=tp_bc,
        false_positives=fp_bc,
        false_negatives=fn_bc,
        precision=prec_bc,
        recall=rec_bc,
        f1_score=f1_bc,
    )

    # 3. Evaluate Loads
    load_callouts = [
        c for c in perception_result.callouts
        if c.semantic_intent in ("CONCENTRATED_FORCE", "PRESSURE", "MOMENT")
    ]
    matched_loads: List[str] = []
    unmatched_loads: List[str] = []
    matched_truth_loads: set[str] = set()

    for c in load_callouts:
        matched = False
        for gt_l in ground_truth.loads:
            if gt_l.load_id in matched_truth_loads:
                continue
            if c.semantic_intent == gt_l.load_type:
                # Compare magnitude
                if c.magnitude is not None and abs(c.magnitude - gt_l.magnitude) <= max(0.01, gt_l.magnitude * tolerance_ratio):
                    matched = True
                    matched_truth_loads.add(gt_l.load_id)
                    matched_loads.append(c.callout_id)
                    break
        if not matched:
            unmatched_loads.append(c.callout_id)

    tp_load = len(matched_truth_loads)
    fp_load = len(unmatched_loads)
    fn_load = len(ground_truth.loads) - tp_load
    prec_load = tp_load / (tp_load + fp_load) if (tp_load + fp_load) > 0 else 1.0
    rec_load = tp_load / (tp_load + fn_load) if (tp_load + fn_load) > 0 else 1.0
    f1_load = (2 * prec_load * rec_load / (prec_load + rec_load)) if (prec_load + rec_load) > 0 else 0.0

    load_metrics = BenchmarkMetricSummary(
        true_positives=tp_load,
        false_positives=fp_load,
        false_negatives=fn_load,
        precision=prec_load,
        recall=rec_load,
        f1_score=f1_load,
    )

    # Overall Metrics
    total_tp = tp_dim + tp_bc + tp_load
    total_fp = fp_dim + fp_bc + fp_load
    total_fn = fn_dim + fn_bc + fn_load
    total_prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 1.0
    total_rec = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 1.0
    overall_f1 = (2 * total_prec * total_rec / (total_prec + total_rec)) if (total_prec + total_rec) > 0 else 0.0

    # Qualified if F1 >= 0.90 and all required boundary conditions and loads are recovered
    is_qualified = (overall_f1 >= 0.90) and (fn_bc == 0) and (fn_load == 0)

    matched_callouts = tuple(matched_dims + matched_bcs + matched_loads)
    unmatched_callouts = tuple(unmatched_dims + unmatched_bcs + unmatched_loads)

    missing_truths = []
    for gt_d in ground_truth.dimensions:
        if gt_d.dimension_id not in matched_truth_dims:
            missing_truths.append(gt_d.dimension_id)
    for gt_b in ground_truth.boundary_conditions:
        if gt_b.boundary_id not in matched_truth_bcs:
            missing_truths.append(gt_b.boundary_id)
    for gt_l in ground_truth.loads:
        if gt_l.load_id not in matched_truth_loads:
            missing_truths.append(gt_l.load_id)

    return DrawingBenchmarkEvaluation(
        drawing_id=ground_truth.drawing_id,
        tier=ground_truth.tier,
        dimension_metrics=dim_metrics,
        boundary_metrics=bc_metrics,
        load_metrics=load_metrics,
        overall_f1=overall_f1,
        is_qualified=is_qualified,
        matched_callout_ids=matched_callouts,
        unmatched_callout_ids=unmatched_callouts,
        missing_truth_ids=tuple(missing_truths),
        details={
            "total_callouts": perception_result.valid_callout_count,
            "total_rejected": len(perception_result.rejected_observations),
            "confidence": perception_result.confidence.overall_confidence,
        },
    )
