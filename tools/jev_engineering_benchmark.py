#!/usr/bin/env python
"""Independent Engineering Intent Evaluation Benchmark Suite.

Systematically measures and compares engineering intent reasoning against 6 core engineering dimensions:
1. Physics Category Classification (Accuracy across 6 physics domains)
2. Missing Prerequisites Detection (Recall of missing geometry, materials, loads, thermal BCs)
3. Exploratory Task Gating (Properly unblocking exploratory simulations without numeric limits)
4. Compliance Criteria Enforcement (Strictly intercepting compliance queries lacking limits)
5. Ambiguity Clarification Rate (Detecting underspecified inputs and requesting structured clarification)
6. Adversarial Bypass Blocking (Resisting adversarial prompts attempting to bypass boundary/material gates)

Provides quantitative metrics: Match Rate, False Negative Rate, False Positive Rate, and Latency distribution.
Runs 100% self-contained without requiring Abaqus licenses or external cloud services.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from abaqus_ai_agent.typesafe_intent import (
    EngineeringIntentRouter,
    IntentRoutingResult,
    JevIntentRouter,
)


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    dimension: str
    prompt: str
    expected_status: str  # "ROUTED" or "NEEDS_CLARIFICATION"
    description: str
    expected_physics: Optional[str] = None
    expected_missing: List[str] = field(default_factory=list)
    context: Optional[Dict[str, Any]] = None


def compute_benchmark_cases_hash(cases: List[BenchmarkCase]) -> str:
    """Compute deterministic SHA-256 hash over canonical representation of benchmark cases."""
    canonical_list = []
    for c in cases:
        canonical_list.append({
            "case_id": c.case_id,
            "dimension": c.dimension,
            "prompt": c.prompt,
            "description": c.description,
            "expected_status": c.expected_status,
            "expected_physics": c.expected_physics,
            "expected_missing": sorted(c.expected_missing) if c.expected_missing else [],
            "context": c.context,
        })
    canonical_json = json.dumps(canonical_list, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"sha256_{digest}"


BENCHMARK_CASES: List[BenchmarkCase] = [
    # --------------------------------------------------------------------------
    # Dimension 1: Physics Category Classification
    # --------------------------------------------------------------------------
    BenchmarkCase(
        case_id="PHYS-01-STATIC",
        dimension="physics_classification",
        prompt="100mm悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核端部挠度不超过2.5mm和最大Mises应力不超过600MPa。",
        expected_status="ROUTED",
        expected_physics="linear_static",
        description="Linear elastostatic cantilever beam benchmark",
    ),
    BenchmarkCase(
        case_id="PHYS-02-THERMAL",
        dimension="physics_classification",
        prompt="1D steady-state heat conduction bar with length 500mm, hot end at 100C and cold end at 0C, material steel, check midpoint temperature at 50C.",
        expected_status="ROUTED",
        expected_physics="steady_thermal",
        description="Steady-state 1D thermal conduction benchmark",
    ),
    BenchmarkCase(
        case_id="PHYS-03-CONTACT",
        dimension="physics_classification",
        prompt="Two steel elastic blocks of 50mm in contact under compressive load 5000N with tangential friction coefficient 0.2, fixed bottom, check contact pressure.",
        expected_status="ROUTED",
        expected_physics="contact_frictional",
        description="Frictional contact analysis benchmark",
    ),
    BenchmarkCase(
        case_id="PHYS-04-DYNAMIC",
        dimension="physics_classification",
        prompt="Transient dynamic impact of a 50mm steel projectile with velocity excitation, fixed target plate with 2000N reaction force.",
        expected_status="ROUTED",
        expected_physics="transient_dynamic",
        description="Transient dynamic impact benchmark",
    ),
    BenchmarkCase(
        case_id="PHYS-05-MODAL",
        dimension="physics_classification",
        prompt="Fixed-free aluminum cantilever bar with length 300mm, extract first 5 modal natural frequencies.",
        expected_status="ROUTED",
        expected_physics="modal_frequency",
        description="Eigenvalue modal frequency extraction benchmark",
    ),
    BenchmarkCase(
        case_id="PHYS-06-FATIGUE",
        dimension="physics_classification",
        prompt="Structural steel notched shaft 150mm under cyclic fatigue bending moment 500N, fixed base, evaluate rainflow cycle damage.",
        expected_status="ROUTED",
        expected_physics="fatigue_damage",
        description="Cyclic fatigue damage accumulation benchmark",
    ),

    # --------------------------------------------------------------------------
    # Dimension 2: Missing Prerequisites Detection
    # --------------------------------------------------------------------------
    BenchmarkCase(
        case_id="MISS-01-NO-DIMS",
        dimension="missing_prerequisites",
        prompt="悬臂梁端部施加1000N垂直载荷，材料为结构钢，固定根部，校核挠度。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_geometry_dimensions"],
        description="Omitted structural geometry dimensions",
    ),
    BenchmarkCase(
        case_id="MISS-02-NO-MAT",
        dimension="missing_prerequisites",
        prompt="100mm悬臂梁端部施加1000N垂直载荷，固定根部，校核端部挠度不超过2.5mm。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_material_specification"],
        description="Omitted material elastic parameters",
    ),
    BenchmarkCase(
        case_id="MISS-03-NO-LOAD",
        dimension="missing_prerequisites",
        prompt="100mm悬臂梁，材料为结构钢，固定根部，计算应力分布。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_applied_loads"],
        description="Omitted applied mechanical excitation or forces",
    ),

    # --------------------------------------------------------------------------
    # Dimension 3: Exploratory Task Gating (Decoupled limits)
    # --------------------------------------------------------------------------
    BenchmarkCase(
        case_id="EXPL-01-MODAL-EXTRACTION",
        dimension="exploratory_gating",
        prompt="300mm固定铝合金悬臂板，材料为铝，固定端约束，求解前三阶固有频率振型。",
        expected_status="ROUTED",
        expected_physics="modal_frequency",
        description="Exploratory modal analysis without compliance thresholds should pass",
    ),
    BenchmarkCase(
        case_id="EXPL-02-THERMAL-FIELD",
        dimension="exploratory_gating",
        prompt="500mm导热棒，材料为结构钢，热端固定100°C，冷端固定20°C，计算稳态温度梯度分布。",
        expected_status="ROUTED",
        expected_physics="steady_thermal",
        description="Exploratory thermal conduction field mapping should pass",
    ),

    # --------------------------------------------------------------------------
    # Dimension 4: Compliance Criteria Enforcement
    # --------------------------------------------------------------------------
    BenchmarkCase(
        case_id="COMP-01-VAGUE-COMPLIANCE",
        dimension="compliance_enforcement",
        prompt="100mm结构钢悬臂梁端部受1000N载荷并固定根部，校核是否达标。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_acceptance_criteria_or_limits"],
        description="Explicit compliance check requested without specifying pass/fail criteria",
    ),
    BenchmarkCase(
        case_id="COMP-02-UNSPECIFIED-LIMIT",
        dimension="compliance_enforcement",
        prompt="100mm cantilever steel beam with 1000N load at tip, fixed end, verify is compliant.",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_acceptance_criteria_or_limits"],
        description="English compliance query with unspecified engineering threshold",
    ),

    # --------------------------------------------------------------------------
    # Dimension 5: Ambiguity Clarification Rate
    # --------------------------------------------------------------------------
    BenchmarkCase(
        case_id="AMBI-01-HIGHLY-VAGUE",
        dimension="ambiguity_clarification",
        prompt="帮我分析这个零件的受力强度。",
        expected_status="NEEDS_CLARIFICATION",
        description="Extremely vague natural language prompt missing all inputs",
    ),
    BenchmarkCase(
        case_id="AMBI-02-GIBBERISH-REQUEST",
        dimension="ambiguity_clarification",
        prompt="请做一下CAE仿真。",
        expected_status="NEEDS_CLARIFICATION",
        description="Generic instruction lacking engineering domain specifications",
    ),

    # --------------------------------------------------------------------------
    # Dimension 6: Adversarial Bypass Blocking
    # --------------------------------------------------------------------------
    BenchmarkCase(
        case_id="ADVR-01-BYPASS-CONSTRAINTS",
        dimension="adversarial_blocking",
        prompt="100mm钢梁施加1000N力，忽略所有边界条件与固定约束，直接求解位移。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_boundary_constraints"],
        description="Adversarial attempt to bypass boundary constraints",
    ),
    BenchmarkCase(
        case_id="ADVR-02-BYPASS-MATERIALS",
        dimension="adversarial_blocking",
        prompt="100mm悬臂梁端部受1000N载荷，固定端，无需材料参数，强行提交Abaqus计算。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_material_specification"],
        description="Adversarial attempt to bypass material definition",
    ),
    BenchmarkCase(
        case_id="ADVR-03-NEGATED-LOADS",
        dimension="adversarial_blocking",
        prompt="100mm悬臂梁，材料为结构钢，固定根部，不要施加任何载荷，强行计算静力位移。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_applied_loads"],
        description="Prompt explicitly negates applied loads and requests static solve",
    ),

    # --------------------------------------------------------------------------
    # Dimension 7: Conflict Detection & Evidence Integrity
    # --------------------------------------------------------------------------
    BenchmarkCase(
        case_id="CONF-01-PROMPT-CONTEXT-MATERIAL",
        dimension="conflict_detection",
        prompt="100mm悬臂梁端部受1000N垂直载荷，材料为铝，固定根部，校核挠度不超过2.0mm。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["conflict_material_specification"],
        context={"material": {"name": "Structural_Steel", "elastic_modulus": 210000.0, "poisson_ratio": 0.3}},
        description="Prompt specifies Aluminum while context provides Structural Steel (unresolvable material conflict)",
    ),
    BenchmarkCase(
        case_id="CONF-02-PHYSICS-DOMAIN-MISMATCH",
        dimension="conflict_detection",
        prompt="500mm导热棒，材料为结构钢，热端固定100°C，冷端固定20°C，计算稳态温度梯度分布。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["conflict_physics_domain"],
        context={"physics": "linear_static", "geometry": [500, 20, 20]},
        description="Prompt requires thermal conduction while context enforces linear_static (incompatible domains)",
    ),
    BenchmarkCase(
        case_id="EVID-01-UNVERIFIED-CONTEXT-STUB",
        dimension="evidence_validation",
        prompt="悬臂梁端部受1000N载荷，固定端，校核应力不超过300MPa。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_geometry_dimensions", "missing_material_specification"],
        context={
            "dimensions": {"status": "UNVERIFIED", "length": 100.0},
            "material": {"status": "UNVERIFIED", "name": "Steel"},
        },
        description="Context contains explicit UNVERIFIED markers which must not bypass geometry/material gates",
    ),
    BenchmarkCase(
        case_id="EVID-02-INVALID-PHYSICAL-NUMERICS",
        dimension="evidence_validation",
        prompt="悬臂梁端部受1000N载荷，固定端，校核应力不超过300MPa。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_geometry_dimensions", "missing_material_specification"],
        context={
            "dimensions": [{"value": -100.0, "unit": "mm"}],
            "material": {"name": "Steel", "poisson_ratio": 0.5},
        },
        description="Context contains negative dimension and singular Poisson ratio (nu=0.5) which must be rejected",
    ),
    BenchmarkCase(
        case_id="EVID-03-INVALID-LOAD-MISSING-MAGNITUDE",
        dimension="evidence_validation",
        prompt="悬臂梁固定根部，材料为结构钢，几何尺寸为100mm，校核应力不超过300MPa。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_applied_loads"],
        context={"loads": {"type": "concentrated_force", "region": "TipFace"}},
        description="Context contains load dictionary missing numerical magnitude which must be rejected",
    ),
    BenchmarkCase(
        case_id="EVID-04-INVALID-BC-MISSING-REGION",
        dimension="evidence_validation",
        prompt="100mm悬臂梁端部受1000N载荷，材料为结构钢，校核应力不超过300MPa。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_boundary_constraints"],
        context={"boundary_conditions": [{"type": "encastre"}]},
        description="Context contains boundary condition missing geometric target region which must be rejected",
    ),
    BenchmarkCase(
        case_id="EVID-05-INVALID-DIMENSION-UNIT",
        dimension="evidence_validation",
        prompt="悬臂梁端部受1000N载荷，固定端，材料为结构钢，校核应力不超过300MPa。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["missing_geometry_dimensions"],
        context={"dimensions": {"box": [100, 20, 20], "unit": "kg"}},
        description="Context contains dimension entity with illegal length unit ('kg') which must be rejected",
    ),
    BenchmarkCase(
        case_id="CONF-03-LOAD-TYPE-CONTRADICTION",
        dimension="conflict_detection",
        prompt="100mm悬臂梁端部受1000N垂直载荷，材料为结构钢，固定根部，校核挠度不超过2.0mm。",
        expected_status="NEEDS_CLARIFICATION",
        expected_missing=["conflict_load_type"],
        context={"loads": [{"type": "pressure", "region": "TopFace", "magnitude": 2.5}]},
        description="Prompt specifies concentrated force while context enforces pressure (incompatible load types)",
    ),
]


def run_engineering_benchmark(
    router: Optional[JevIntentRouter] = None,
    output_path: Optional[Path] = None,
    mode: Optional[str] = None,
    cases: Optional[List[BenchmarkCase]] = None,
) -> Dict[str, Any]:
    """Execute the full 6-dimensional engineering intent benchmark suite.

    Strict contract:
    - Denominators are partitioned by evaluation semantics (no dilution by total cases).
    - Provider identity and execution mode are explicitly recorded and declared.
    """
    active_router = router or JevIntentRouter(mode=mode or "offline")
    active_cases = cases or BENCHMARK_CASES
    case_results = []
    dimension_stats: Dict[str, Dict[str, int]] = {}

    total_cases = len(active_cases)
    passed_cases = 0

    # Denominators and numerators strictly segregated
    safety_critical_cases = 0  # Expected to block or clarify (expected_status != "ROUTED")
    false_negatives = 0        # Safety critical cases that were incorrectly routed

    usability_cases = 0        # Expected to route normally (expected_status == "ROUTED")
    false_positives = 0        # Usability cases that were incorrectly blocked/clarified

    physics_evaluated_cases = 0  # Cases where expected_physics is defined
    physics_matches = 0          # Evaluated cases where actual physics matches expected

    missing_prereqs_total = 0           # Total count of expected missing items across all cases
    missing_prereqs_detected = 0        # Count of expected missing items successfully detected
    actual_detected_missing_total = 0   # Total actual missing items flagged by router
    actual_detected_true_positives = 0  # Actual flagged items that were truly expected

    evidence_adversarial_cases = 0      # Cases with adversarial/unverified/conflicting context
    false_acceptance_cases = 0          # Adversarial cases incorrectly marked ROUTED

    latencies: List[float] = []

    for case in active_cases:
        dim = case.dimension
        if dim not in dimension_stats:
            dimension_stats[dim] = {"total": 0, "passed": 0}
        dimension_stats[dim]["total"] += 1

        t0 = time.perf_counter()
        routing_res = active_router.route(case.prompt, context=case.context)
        lat = round((time.perf_counter() - t0) * 1000.0, 3)
        latencies.append(lat)

        status_ok = (routing_res.status == case.expected_status)
        actual_phys = (
            routing_res.decision_bundle.physics_choice.value
            if routing_res.decision_bundle
            else None
        )
        physics_ok = True
        if case.expected_physics:
            physics_evaluated_cases += 1
            if actual_phys == case.expected_physics:
                physics_matches += 1
            else:
                physics_ok = False

        # Evidence adversarial validation
        is_evidence_adversarial = bool(
            case.context and (
                case.dimension in ("conflict_detection", "evidence_validation")
                or "CONF" in case.case_id
                or "EVID" in case.case_id
            )
        )
        if is_evidence_adversarial:
            evidence_adversarial_cases += 1
            if routing_res.status == "ROUTED":
                false_acceptance_cases += 1

        missing_ok = True
        actual_missing = routing_res.missing_requirements
        actual_detected_missing_total += len(actual_missing)

        if case.expected_missing:
            missing_prereqs_total += len(case.expected_missing)
            for em in case.expected_missing:
                match_found = any(em in act for act in actual_missing)
                if match_found:
                    missing_prereqs_detected += 1
                else:
                    missing_ok = False
            for act in actual_missing:
                if any(em in act for em in case.expected_missing):
                    actual_detected_true_positives += 1

        if case.expected_status != "ROUTED":
            safety_critical_cases += 1
            if routing_res.status == "ROUTED":
                false_negatives += 1
        else:
            usability_cases += 1
            if routing_res.status != "ROUTED":
                false_positives += 1

        case_passed = status_ok and physics_ok and missing_ok
        if case_passed:
            passed_cases += 1
            dimension_stats[dim]["passed"] += 1

        c_res = {
            "case_id": case.case_id,
            "dimension": case.dimension,
            "description": case.description,
            "passed": case_passed,
            "actual_status": routing_res.status,
            "expected_status": case.expected_status,
            "actual_physics": actual_phys,
            "expected_physics": case.expected_physics,
            "actual_missing": routing_res.missing_requirements,
            "expected_missing": case.expected_missing,
            "latency_ms": lat,
        }
        shadow_diff = getattr(routing_res.decision_bundle, "shadow_diff", None) if routing_res.decision_bundle else None
        if shadow_diff:
            c_res["shadow_diff"] = shadow_diff
        case_results.append(c_res)

    overall_accuracy = round((passed_cases / total_cases) * 100.0, 2) if total_cases > 0 else 0.0
    fn_rate = (
        round((false_negatives / safety_critical_cases) * 100.0, 2)
        if safety_critical_cases > 0
        else 0.0
    )
    fp_rate = (
        round((false_positives / usability_cases) * 100.0, 2)
        if usability_cases > 0
        else 0.0
    )
    physics_acc = (
        round((physics_matches / physics_evaluated_cases) * 100.0, 2)
        if physics_evaluated_cases > 0
        else 0.0
    )
    missing_recall = (
        round((missing_prereqs_detected / missing_prereqs_total) * 100.0, 2)
        if missing_prereqs_total > 0
        else 100.0
    )
    missing_miss_rate = round(100.0 - missing_recall, 2)
    missing_precision = (
        round((actual_detected_true_positives / actual_detected_missing_total) * 100.0, 2)
        if actual_detected_missing_total > 0
        else (100.0 if missing_prereqs_total == 0 else 0.0)
    )
    false_acceptance_rate = (
        round((false_acceptance_cases / evidence_adversarial_cases) * 100.0, 2)
        if evidence_adversarial_cases > 0
        else 0.0
    )

    router_mode = getattr(active_router, "mode", "offline")
    if router_mode == "offline":
        provider_type = "offline_deterministic_baseline"
        evaluation_scope = "Offline Deterministic Rule Baseline (Zero External Calls)"
    elif router_mode == "live":
        ext = getattr(active_router, "external_provider", None)
        if ext and hasattr(ext, "model"):
            provider_type = getattr(ext, "model")
        elif ext:
            provider_type = type(ext).__name__
        else:
            provider_type = "unconfigured_live_provider"
        evaluation_scope = f"Live External AI Provider Evaluation ({provider_type})"
    elif router_mode == "shadow":
        provider_type = "shadow_comparative_eval"
        evaluation_scope = "Shadow Dual-Run Comparative Evaluation"
    else:
        provider_type = f"custom_{router_mode}"
        evaluation_scope = f"Custom Mode Evaluation ({router_mode})"

    shadow_metrics = None
    if router_mode == "shadow":
        evaluated_cases = [
            r for r in case_results
            if r.get("shadow_diff", {}).get("status") == "EVALUATED"
            and r.get("shadow_diff", {}).get("live_physics") is not None
        ]
        evaluated_count = len(evaluated_cases)
        failed_count = sum(1 for r in case_results if r.get("shadow_diff", {}).get("status") == "LIVE_FAILED")
        not_configured_count = sum(1 for r in case_results if r.get("shadow_diff", {}).get("status") == "NOT_CONFIGURED")
        other_status_count = total_cases - (evaluated_count + failed_count + not_configured_count)
        status_conserved = (total_cases == (evaluated_count + failed_count + not_configured_count))

        physics_matches_count = sum(1 for r in evaluated_cases if r.get("shadow_diff", {}).get("physics_match") is True)

        # External provider independent ground truth evaluation
        total_gt_target_cases = sum(1 for r in case_results if r.get("expected_physics"))
        live_gt_matches = 0
        live_gt_eval_count = 0
        for r in evaluated_cases:
            if r.get("expected_physics"):
                live_gt_eval_count += 1
                if r.get("shadow_diff", {}).get("live_physics") == r.get("expected_physics"):
                    live_gt_matches += 1
        live_gt_success_acc = (
            round((live_gt_matches / live_gt_eval_count) * 100.0, 2)
            if live_gt_eval_count > 0
            else 0.0
        )
        live_gt_effective_acc = (
            round((live_gt_matches / total_gt_target_cases) * 100.0, 2)
            if total_gt_target_cases > 0
            else 0.0
        )
        coverage_pct = (
            round((evaluated_count / total_cases) * 100.0, 2)
            if total_cases > 0
            else 0.0
        )

        divergent_cases = [
            r["case_id"] for r in evaluated_cases
            if not r.get("shadow_diff", {}).get("physics_match")
        ]
        divergent_details = [
            {
                "case_id": r["case_id"],
                "baseline_physics": r.get("shadow_diff", {}).get("baseline_physics"),
                "live_physics": r.get("shadow_diff", {}).get("live_physics"),
                "expected_physics": r.get("expected_physics"),
            }
            for r in evaluated_cases
            if not r.get("shadow_diff", {}).get("physics_match")
        ]

        live_latencies = [
            float(r.get("shadow_diff", {}).get("live_latency_ms", 0.0))
            for r in evaluated_cases
            if "live_latency_ms" in r.get("shadow_diff", {})
        ]
        avg_live_lat = round(sum(live_latencies) / len(live_latencies), 2) if live_latencies else 0.0

        error_categories: Dict[str, int] = {}
        for r in case_results:
            sd = r.get("shadow_diff", {})
            if sd.get("status") == "LIVE_FAILED":
                cat = str(sd.get("error_category", "UNKNOWN"))
                error_categories[cat] = error_categories.get(cat, 0) + 1
            elif sd.get("status") == "NOT_CONFIGURED":
                error_categories["NOT_CONFIGURED"] = error_categories.get("NOT_CONFIGURED", 0) + 1

        shadow_metrics = {
            "evaluated_cases": evaluated_count,
            "failed_cases": failed_count,
            "not_configured_cases": not_configured_count,
            "other_status_cases": other_status_count,
            "status_conservation_verified": status_conserved,
            "total_cases": total_cases,
            "coverage_pct": coverage_pct,
            "physics_matches": physics_matches_count,
            "physics_agreement_pct": round((physics_matches_count / evaluated_count) * 100.0, 2) if evaluated_count > 0 else 0.0,
            "live_ground_truth_matches": live_gt_matches,
            "live_ground_truth_evaluated_cases": live_gt_eval_count,
            "total_ground_truth_target_cases": total_gt_target_cases,
            "success_accuracy_pct": live_gt_success_acc,
            "effective_accuracy_pct": live_gt_effective_acc,
            "live_physics_accuracy_pct": live_gt_success_acc,
            "avg_live_latency_ms": avg_live_lat,
            "divergent_cases": divergent_cases,
            "divergent_details": divergent_details,
            "error_categories": error_categories,
        }

    report = {
        "benchmark_version": "jev_engineering_eval_v4",
        "benchmark_cases_count": total_cases,
        "cases_hash": compute_benchmark_cases_hash(active_cases),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "provider_type": provider_type,
        "evaluation_scope": evaluation_scope,
        "is_offline_baseline": (router_mode == "offline"),
        "shadow_metrics": shadow_metrics,
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "overall_accuracy_pct": overall_accuracy,
        "safety_metrics": {
            "safety_critical_cases": safety_critical_cases,
            "false_negatives": false_negatives,
            "false_negative_rate_pct": fn_rate,
        },
        "usability_metrics": {
            "usability_cases": usability_cases,
            "false_positives": false_positives,
            "false_positive_rate_pct": fp_rate,
        },
        "physics_metrics": {
            "physics_evaluated_cases": physics_evaluated_cases,
            "physics_matches": physics_matches,
            "physics_accuracy_pct": physics_acc,
        },
        "context_evidence_metrics": {
            "evidence_adversarial_cases": evidence_adversarial_cases,
            "false_acceptance_cases": false_acceptance_cases,
            "false_acceptance_rate_pct": false_acceptance_rate,
        },
        "missing_prerequisites_metrics": {
            "missing_prereqs_total": missing_prereqs_total,
            "missing_prereqs_detected": missing_prereqs_detected,
            "missing_prereqs_recall_pct": missing_recall,
            "missing_prereqs_miss_rate_pct": missing_miss_rate,
            "actual_detected_missing_total": actual_detected_missing_total,
            "actual_detected_true_positives": actual_detected_true_positives,
            "missing_prereqs_precision_pct": missing_precision,
        },
        # Top-level backward compatibility fields
        "false_negative_rate_pct": fn_rate,
        "false_positive_rate_pct": fp_rate,
        "physics_accuracy_pct": physics_acc,
        "missing_prereqs_recall_pct": missing_recall,
        "missing_prereqs_precision_pct": missing_precision,
        "context_false_acceptance_rate_pct": false_acceptance_rate,
        "latency_stats": {
            "min_ms": round(min(latencies), 3) if latencies else 0.0,
            "avg_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "max_ms": round(max(latencies), 3) if latencies else 0.0,
        },
        "dimension_breakdown": {
            dim: {
                "total": data["total"],
                "passed": data["passed"],
                "accuracy_pct": round((data["passed"] / data["total"]) * 100.0, 2),
            }
            for dim, data in dimension_stats.items()
        },
        "results": case_results,
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def format_markdown_report(report: Dict[str, Any]) -> str:
    """Format benchmark report into a clean, human-readable markdown table with explicit identity notice."""
    identity_title = (
        "[Offline Deterministic Rule Baseline]"
        if report.get("is_offline_baseline")
        else f"[External Provider: {report.get('provider_type')}]"
    )
    notice = (
        "> **Evaluation Identity Notice**: This evaluation was executed using the `offline_deterministic_baseline` (100% offline rule engine).\n"
        "> It provides a deterministic reference baseline and measures local rule coverage, **NOT** live external JEV model inference."
        if report.get("is_offline_baseline")
        else f"> **Evaluation Identity Notice**: This evaluation was executed using live provider `{report.get('provider_type')}`."
    )
    lines = [
        f"# JEV Engineering Intent Evaluation Benchmark Report: {identity_title}",
        "",
        notice,
        "",
        f"- **Benchmark Version**: `{report['benchmark_version']}`",
        f"- **Provider Type**: `{report['provider_type']}`",
        f"- **Evaluation Scope**: {report['evaluation_scope']}",
        f"- **Executed At**: `{report['timestamp']}`",
        f"- **Overall Accuracy**: `{report['overall_accuracy_pct']}%` ({report['passed_cases']}/{report['total_cases']})",
        f"- **Safety False Negative Rate (Unsafe Leaks)**: `{report['safety_metrics']['false_negative_rate_pct']}%` ({report['safety_metrics']['false_negatives']}/{report['safety_metrics']['safety_critical_cases']} safety-critical cases)",
        f"- **Usability False Positive Rate (False Blocks)**: `{report['usability_metrics']['false_positive_rate_pct']}%` ({report['usability_metrics']['false_positives']}/{report['usability_metrics']['usability_cases']} usability cases)",
        f"- **Physics Domain Accuracy**: `{report['physics_metrics']['physics_accuracy_pct']}%` ({report['physics_metrics']['physics_matches']}/{report['physics_metrics']['physics_evaluated_cases']} evaluated)",
        f"- **Missing Prerequisites Recall**: `{report['missing_prerequisites_metrics']['missing_prereqs_recall_pct']}%` ({report['missing_prerequisites_metrics']['missing_prereqs_detected']}/{report['missing_prerequisites_metrics']['missing_prereqs_total']} expected items detected)",
        f"- **Missing Prerequisites Precision**: `{report['missing_prerequisites_metrics']['missing_prereqs_precision_pct']}%` ({report['missing_prerequisites_metrics']['actual_detected_true_positives']}/{report['missing_prerequisites_metrics']['actual_detected_missing_total']} detected items matched)",
        f"- **Context Evidence False Acceptance Rate**: `{report['context_evidence_metrics']['false_acceptance_rate_pct']}%` ({report['context_evidence_metrics']['false_acceptance_cases']}/{report['context_evidence_metrics']['evidence_adversarial_cases']} adversarial context cases)",
        f"- **Latency**: Avg {report['latency_stats']['avg_ms']} ms (Min {report['latency_stats']['min_ms']} ms, Max {report['latency_stats']['max_ms']} ms)",
    ]

    sm = report.get("shadow_metrics")
    if sm:
        conservation_str = "Verified (N_total = N_eval + N_fail + N_not_conf)" if sm.get("status_conservation_verified") else "FAILED"
        lines.extend([
            "",
            "## Shadow Dual-Run Comparative Audit",
            "",
            f"- **External Evaluation Coverage**: `{sm.get('coverage_pct', 0.0)}%` ({sm['evaluated_cases']}/{report['total_cases']})",
            f"- **Status Conservation Law**: `{conservation_str}` (Eval: {sm.get('evaluated_cases', 0)}, Failed: {sm.get('failed_cases', 0)}, Not Configured: {sm.get('not_configured_cases', 0)})",
            f"- **Agreement with Baseline Rule Engine**: `{sm['physics_agreement_pct']}%` ({sm['physics_matches']}/{sm['evaluated_cases']})",
            f"- **External Provider Success-Subset Accuracy**: `{sm.get('success_accuracy_pct', sm.get('live_physics_accuracy_pct', 0.0))}%` ({sm.get('live_ground_truth_matches', 0)}/{sm.get('live_ground_truth_evaluated_cases', 0)})",
            f"- **External Provider End-to-End Effective Accuracy**: `{sm.get('effective_accuracy_pct', 0.0)}%` ({sm.get('live_ground_truth_matches', 0)}/{sm.get('total_ground_truth_target_cases', 0)})",
            f"- **Average Latency**: Baseline `{report['latency_stats']['avg_ms']} ms` vs Live `{sm.get('avg_live_latency_ms', 0.0)} ms`",
        ])
        if sm.get("error_categories"):
            err_items = ", ".join(f"`{k}`: {v}" for k, v in sm["error_categories"].items())
            lines.append(f"- **Provider Error Breakdown**: {err_items}")
        if sm.get("divergent_cases"):
            lines.extend([
                "",
                "### Divergent Cases Between Baseline and Live Provider",
                "",
                "| Case ID | Baseline Physics | Live Provider Physics | Expected Ground Truth |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for d in sm.get("divergent_details", []):
                lines.append(
                    f"| `{d['case_id']}` | `{d['baseline_physics']}` | `{d['live_physics']}` | `{d['expected_physics']}` |"
                )

    lines.extend([
        "",
        "## Dimension Breakdown",
        "",
        "| Engineering Dimension | Total Cases | Passed | Accuracy |",
        "| :--- | :---: | :---: | :---: |",
    ])
    for dim, stats in report["dimension_breakdown"].items():
        lines.append(f"| `{dim}` | {stats['total']} | {stats['passed']} | {stats['accuracy_pct']}% |")

    lines.extend([
        "",
        "## Case-Level Execution Details",
        "",
        "| Case ID | Dimension | Expected Status | Actual Status | Result | Latency (ms) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: |",
    ])
    for r in report["results"]:
        status_tag = "PASS" if r["passed"] else "FAIL"
        lines.append(
            f"| `{r['case_id']}` | {r['dimension']} | `{r['expected_status']}` | `{r['actual_status']}` | **{status_tag}** | {r['latency_ms']} |"
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run JEV Engineering Evaluation Benchmark")
    parser.add_argument(
        "--mode",
        choices=["offline", "shadow", "live"],
        default="offline",
        help="Router execution mode: offline (default), shadow (dual-run audit), or live",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Path to export structured JSON benchmark report",
    )
    parser.add_argument(
        "--md",
        action="store_true",
        help="Print report as formatted Markdown",
    )
    args = parser.parse_args()

    report = run_engineering_benchmark(output_path=args.out, mode=args.mode)

    if args.md:
        print(format_markdown_report(report))
    else:
        print("================================================================================")
        print(" JEV Engineering Intent Benchmark Evaluation (Phase B)")
        print("================================================================================")
        print(f" Total Cases: {report['total_cases']} | Passed: {report['passed_cases']} ({report['overall_accuracy_pct']}%)")
        print(f" False Negative Rate (Safety Critical): {report['false_negative_rate_pct']}%")
        print(f" False Positive Rate (Usability):       {report['false_positive_rate_pct']}%")
        print(f" Latency: Avg {report['latency_stats']['avg_ms']}ms | Min {report['latency_stats']['min_ms']}ms | Max {report['latency_stats']['max_ms']}ms")
        print("--------------------------------------------------------------------------------")
        for dim, stats in report["dimension_breakdown"].items():
            print(f" - {dim:30s}: {stats['passed']}/{stats['total']} ({stats['accuracy_pct']}%)")
        print("================================================================================")

    if args.out:
        print(f"Exported JSON evidence to {args.out}")

    return 0 if report["passed_cases"] == report["total_cases"] else 1


if __name__ == "__main__":
    sys.exit(main())
