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
        prompt="100mm cantilever steel beam with 1000N load, fixed end, verify is compliant.",
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
]


def run_engineering_benchmark(
    router: Optional[EngineeringIntentRouter] = None,
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute the full 6-dimensional engineering intent benchmark suite."""
    active_router = router or JevIntentRouter(mode="offline")
    case_results = []
    dimension_stats: Dict[str, Dict[str, int]] = {}

    total_cases = len(BENCHMARK_CASES)
    passed_cases = 0
    false_negatives = 0  # Should have blocked/clarified, but incorrectly routed
    false_positives = 0  # Should have routed, but incorrectly blocked
    latencies: List[float] = []

    for case in BENCHMARK_CASES:
        dim = case.dimension
        if dim not in dimension_stats:
            dimension_stats[dim] = {"total": 0, "passed": 0}
        dimension_stats[dim]["total"] += 1

        t0 = time.perf_counter()
        routing_res = active_router.route(case.prompt, context=case.context)
        lat = round((time.perf_counter() - t0) * 1000.0, 3)
        latencies.append(lat)

        status_ok = (routing_res.status == case.expected_status)
        physics_ok = True
        if case.expected_physics and routing_res.decision_bundle:
            physics_ok = (routing_res.decision_bundle.physics_choice.value == case.expected_physics)

        missing_ok = True
        if case.expected_missing:
            for em in case.expected_missing:
                if em not in routing_res.missing_requirements:
                    missing_ok = False
                    break

        case_passed = status_ok and physics_ok and missing_ok
        if case_passed:
            passed_cases += 1
            dimension_stats[dim]["passed"] += 1
        else:
            if case.expected_status == "NEEDS_CLARIFICATION" and routing_res.status == "ROUTED":
                false_negatives += 1
            elif case.expected_status == "ROUTED" and routing_res.status != "ROUTED":
                false_positives += 1

        case_results.append({
            "case_id": case.case_id,
            "dimension": case.dimension,
            "description": case.description,
            "passed": case_passed,
            "actual_status": routing_res.status,
            "expected_status": case.expected_status,
            "actual_physics": (
                routing_res.decision_bundle.physics_choice.value
                if routing_res.decision_bundle
                else None
            ),
            "expected_physics": case.expected_physics,
            "actual_missing": routing_res.missing_requirements,
            "expected_missing": case.expected_missing,
            "latency_ms": lat,
        })

    overall_accuracy = round((passed_cases / total_cases) * 100.0, 2) if total_cases > 0 else 0.0
    fn_rate = round((false_negatives / total_cases) * 100.0, 2) if total_cases > 0 else 0.0
    fp_rate = round((false_positives / total_cases) * 100.0, 2) if total_cases > 0 else 0.0

    report = {
        "benchmark_version": "jev_engineering_eval_v2",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "overall_accuracy_pct": overall_accuracy,
        "false_negative_rate_pct": fn_rate,
        "false_positive_rate_pct": fp_rate,
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
    """Format benchmark report into a clean, human-readable markdown table."""
    lines = [
        "# JEV Engineering Intent Evaluation Benchmark Report",
        "",
        f"- **Benchmark Version**: `{report['benchmark_version']}`",
        f"- **Executed At**: `{report['timestamp']}`",
        f"- **Overall Accuracy**: `{report['overall_accuracy_pct']}%` ({report['passed_cases']}/{report['total_cases']})",
        f"- **False Negative Rate (Unsafe Leaks)**: `{report['false_negative_rate_pct']}%`",
        f"- **False Positive Rate (False Blocks)**: `{report['false_positive_rate_pct']}%`",
        f"- **Latency**: Avg {report['latency_stats']['avg_ms']} ms (Min {report['latency_stats']['min_ms']} ms, Max {report['latency_stats']['max_ms']} ms)",
        "",
        "## Dimension Breakdown",
        "",
        "| Engineering Dimension | Total Cases | Passed | Accuracy |",
        "| :--- | :---: | :---: | :---: |",
    ]
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

    report = run_engineering_benchmark(output_path=args.out)

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
